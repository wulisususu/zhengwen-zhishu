"""Tests for the Guided Strategist API (P3-B, Sub2).

Runs fully offline:
  * Sub1's ``guided_models``/``guided_state_machine`` are absent, so the
    service uses its built-in fallback model (contract-faithful). The test
    creates the table via ``guided_service.ensure_guided_tables``.
  * Sub3's strategist/generation adapters are mocked via monkeypatch, so the
    real generation chain is never invoked.

Coverage (P3B_SPEC.md §10): feature-flag 403, ownership 404, create 201,
wrong-revision 409, stage gate, confirm stage1->stage2 recommendations,
confirm stage3 -> confirmed, generate idempotency, retry from failed.
"""
from __future__ import annotations

import os
from typing import Any, Dict

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .. import guided_service as svc
from .. import guided_router as gr_mod
from ..guided_router import router

# --------------------------------------------------------------------------- #
# App + DB + auth fixtures
# --------------------------------------------------------------------------- #
# StaticPool keeps a single shared in-memory connection so the table created by
# ensure_guided_tables is visible to every test session.
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
svc.ensure_guided_tables(engine)


class FakeUser:
    def __init__(self, uid: int):
        self.id = uid


_STATE: Dict[str, Any] = {"user": FakeUser(123)}


def get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user():
    return _STATE["user"]


app = FastAPI()
app.include_router(router, prefix="/api/v1/ppt-master")
app.dependency_overrides[gr_mod._repo_get_db] = get_db
app.dependency_overrides[gr_mod._repo_get_current_user] = get_current_user


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _feature_flag(monkeypatch):
    # Default: current test user (123) is allowed.
    monkeypatch.setenv("PPT_GUIDED_STRATEGIST_ALLOWED_USERS", "123")
    yield


@pytest.fixture(autouse=True)
def _reset_user():
    # The current user is process-global state in this test harness; reset it
    # before every test so cross-test leakage (e.g. switching to user 456) cannot
    # affect unrelated tests.
    _STATE["user"] = FakeUser(123)
    yield


@pytest.fixture(autouse=True)
def _mock_sub3(monkeypatch):
    """Stage2 recommendation generation is exercised synchronously by
    ``confirm_stage`` (stage1 -> stage2), so it is mocked. The actual deck
    generation runs as a DETACHED background task (see guided_router
    ._run_guided_background) and is NOT invoked through this seam, so it is left
    unmocked here."""

    def fake_recs(stage1):
        return {
            "directions": [
                {"direction_id": "safe", "name": "Safe", "visual_style": "classic"},
                {"direction_id": "shifted", "name": "Shifted", "visual_style": "modern"},
                {"direction_id": "bold", "name": "Bold", "visual_style": "expressive"},
            ]
        }

    monkeypatch.setattr(svc, "_lazy_generate_stage2_recommendations", fake_recs)


def _err_code(r):
    """FastAPI wraps HTTPException detail under 'detail'."""
    return r.json()["detail"]["error_code"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _create(client: TestClient, **kw) -> Dict[str, Any]:
    r = client.post("/api/v1/ppt-master/guided-projects", json=kw)
    assert r.status_code == 201, r.text
    return r.json()


def _confirm_stage1(client, pid, rev):
    r = client.post(
        f"/api/v1/ppt-master/guided-projects/{pid}/confirm",
        json={"expected_revision": rev, "stage": {"audience": {"value": "exec"}}},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _confirm_stage2(client, pid, rev):
    r = client.post(
        f"/api/v1/ppt-master/guided-projects/{pid}/confirm",
        json={"expected_revision": rev, "stage": {"direction_id": "safe"}},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _confirm_stage3(client, pid, rev):
    r = client.post(
        f"/api/v1/ppt-master/guided-projects/{pid}/confirm",
        json={"expected_revision": rev, "stage": {"page_count": 6, "animation_policy": "none"}},
    )
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_feature_flag_denies_403(client, monkeypatch):
    monkeypatch.setenv("PPT_GUIDED_STRATEGIST_ALLOWED_USERS", "999")
    r = client.post("/api/v1/ppt-master/guided-projects", json={"title": "x"})
    assert r.status_code == 403
    assert _err_code(r) == "feature_denied"


def test_ownership_404_other_user(client):
    created = _create(client, title="mine")
    pid = created["guided_project_id"]
    # Switch identity to a different user; lookup must 404 (not 403).
    _STATE["user"] = FakeUser(456)
    r = client.get(f"/api/v1/ppt-master/guided-projects/{pid}")
    assert r.status_code == 404
    assert _err_code(r) == "not_found"


def test_create_201(client):
    created = _create(client, title="Demo", prompt="hello")
    assert created["current_stage"] == "stage1_draft"
    assert created["status"] == "draft"
    assert created["revision"] == 1


def test_patch_wrong_revision_409(client):
    created = _create(client)
    pid = created["guided_project_id"]
    r = client.patch(
        f"/api/v1/ppt-master/guided-projects/{pid}/stage",
        json={"expected_revision": 999, "stage_data": {"audience": {"value": "x"}}},
    )
    assert r.status_code == 409
    assert _err_code(r) == "revision_conflict"


def test_patch_then_stage_gate_rejection(client):
    created = _create(client)
    pid = created["guided_project_id"]
    rev = created["revision"]
    # valid patch on stage1_draft
    r = client.patch(
        f"/api/v1/ppt-master/guided-projects/{pid}/stage",
        json={"expected_revision": rev, "stage_data": {"audience": {"value": "exec"}}},
    )
    assert r.status_code == 200
    assert r.json()["revision"] == rev + 1

    # Drive to confirmed so a later PATCH must be rejected (not a draft stage).
    _confirm_stage1(client, pid, r.json()["revision"])
    s2 = client.get(f"/api/v1/ppt-master/guided-projects/{pid}/stage").json()
    _confirm_stage2(client, pid, s2["revision"])
    s3 = client.get(f"/api/v1/ppt-master/guided-projects/{pid}/stage").json()
    _confirm_stage3(client, pid, s3["revision"])
    confirmed = client.get(f"/api/v1/ppt-master/guided-projects/{pid}/stage").json()
    assert confirmed["current_stage"] == "confirmed"

    # PATCH after confirmation -> 400 stage_gate_invalid
    r = client.patch(
        f"/api/v1/ppt-master/guided-projects/{pid}/stage",
        json={"expected_revision": confirmed["revision"], "stage_data": {"audience": {"value": "y"}}},
    )
    assert r.status_code == 400
    assert _err_code(r) == "stage_gate_invalid"


def test_confirm_stage1_produces_stage2_recommendations(client):
    created = _create(client)
    pid = created["guided_project_id"]
    rev = created["revision"]
    _confirm_stage1(client, pid, rev)
    stage = client.get(f"/api/v1/ppt-master/guided-projects/{pid}/stage").json()
    assert stage["current_stage"] == "stage2_draft"
    detail = client.get(f"/api/v1/ppt-master/guided-projects/{pid}").json()
    dirs = detail["recommendations_json"]["directions"]
    assert len(dirs) >= 3
    assert all(d["direction_id"] in ("safe", "shifted", "bold") for d in dirs)


def test_confirm_stage3_sets_confirmed(client):
    created = _create(client)
    pid = created["guided_project_id"]
    rev = created["revision"]
    _confirm_stage1(client, pid, rev)
    s2 = client.get(f"/api/v1/ppt-master/guided-projects/{pid}/stage").json()
    _confirm_stage2(client, pid, s2["revision"])
    s3 = client.get(f"/api/v1/ppt-master/guided-projects/{pid}/stage").json()
    _confirm_stage3(client, pid, s3["revision"])
    detail = client.get(f"/api/v1/ppt-master/guided-projects/{pid}").json()
    assert detail["status"] == "confirmed"
    assert detail["current_stage"] == "confirmed"
    assert detail["result_json"] is not None
    assert detail["confirmed_values_json"] is not None


def test_generate_idempotency(client):
    created = _create(client)
    pid = created["guided_project_id"]
    rev = created["revision"]
    _confirm_stage1(client, pid, rev)
    s2 = client.get(f"/api/v1/ppt-master/guided-projects/{pid}/stage").json()
    _confirm_stage2(client, pid, s2["revision"])
    s3 = client.get(f"/api/v1/ppt-master/guided-projects/{pid}/stage").json()
    _confirm_stage3(client, pid, s3["revision"])

    g1 = client.post(f"/api/v1/ppt-master/guided-projects/{pid}/generate").json()
    assert g1["status"] == "generating"
    assert g1["generation_task_id"]

    g2 = client.post(f"/api/v1/ppt-master/guided-projects/{pid}/generate").json()
    assert g2["generation_task_id"] == g1["generation_task_id"]


def test_generate_requires_confirmed(client):
    created = _create(client)
    pid = created["guided_project_id"]
    r = client.post(f"/api/v1/ppt-master/guided-projects/{pid}/generate")
    assert r.status_code == 400
    assert _err_code(r) == "stage_gate_invalid"


def test_retry_from_failed(client):
    created = _create(client)
    pid = created["guided_project_id"]
    rev = created["revision"]
    _confirm_stage1(client, pid, rev)
    s2 = client.get(f"/api/v1/ppt-master/guided-projects/{pid}/stage").json()
    _confirm_stage2(client, pid, s2["revision"])
    s3 = client.get(f"/api/v1/ppt-master/guided-projects/{pid}/stage").json()
    _confirm_stage3(client, pid, s3["revision"])

    # generate() returns IMMEDIATELY with a generation task id; the real chain
    # runs as a detached background task (P3B_SPEC §6 — poll GET /{id}). It does
    # NOT return 500 synchronously on failure.
    r = client.post(f"/api/v1/ppt-master/guided-projects/{pid}/generate")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "generating"
    first_task_id = r.json()["generation_task_id"]
    assert first_task_id

    # Simulate the background chain having failed. The worker marks the project
    # failed (this mirrors guided_router._run_guided_background's except branch).
    # We drive it through the SAME in-memory DB the HTTP layer uses, so the test
    # stays deterministic and DB-backed instead of racing the detached task.
    with TestingSessionLocal() as db:
        gp = db.query(svc.GuidedProject).filter(
            svc.GuidedProject.guided_project_id == pid
        ).first()
        assert gp is not None
        gp.status = "failed"
        gp.error_json = {"message": "generation exploded", "type": "RuntimeError"}
        gp.completed_at = svc._now()
        db.commit()

    detail = client.get(f"/api/v1/ppt-master/guided-projects/{pid}").json()
    assert detail["status"] == "failed"
    assert detail["error_json"]["message"] == "generation exploded"

    # retry from failed -> 200, fresh task id, back to generating.
    rr = client.post(f"/api/v1/ppt-master/guided-projects/{pid}/retry")
    assert rr.status_code == 200, rr.text
    assert rr.json()["status"] == "generating"
    second_task_id = rr.json()["generation_task_id"]
    assert second_task_id
    assert second_task_id != first_task_id
