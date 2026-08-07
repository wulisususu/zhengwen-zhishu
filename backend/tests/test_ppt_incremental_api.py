from __future__ import annotations

import json
import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.deps import get_current_user
from app.models import User


@pytest.fixture()
def api_context(monkeypatch):
    import app.PPT_master.incremental_router as incremental_router
    from app.PPT_master.router import router as ppt_router

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    owner = User(id=1, username="api-owner", password_hash="x")
    other = User(id=2, username="api-other", password_hash="x")
    db.add_all([owner, other])
    db.commit()

    async def fake_workflow(**kwargs):
        await kwargs["event_sink"](
            {
                "event_id": "evt_api_1",
                "event_type": "planning.started",
                "task_id": kwargs["task_id"],
                "project_id": kwargs["project_id"],
                "sequence": 1,
                "timestamp": "2026-07-19T00:00:00Z",
                "data": {"status": "planning"},
            }
        )

    monkeypatch.setattr(incremental_router, "run_incremental_workflow", fake_workflow)
    monkeypatch.setattr(
        incremental_router,
        "generation_limiter",
        incremental_router.GenerationLimiter(max_global=1, max_per_user=1),
    )

    app = FastAPI()
    app.include_router(ppt_router, prefix="/api/v1")

    def override_db():
        yield db

    def override_owner():
        return owner

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_owner
    try:
        yield app, db, owner, other, incremental_router
    finally:
        db.close()
        engine.dispose()


def _valid_body(request_id: str = "incremental-api-001") -> dict:
    return {
        "user_input": "Four page integration topic",
        "page_count": 4,
        "page_format": "ppt169",
        "sources": [],
        "request_id": request_id,
    }


def test_incremental_generate_requires_authentication(api_context):
    app, db, _owner, _other, _router = api_context
    app.dependency_overrides.pop(get_current_user)
    with TestClient(app) as client:
        response = client.post("/api/v1/ppt-master/generate-incremental", json=_valid_body())
    assert response.status_code == 401


def test_incremental_generate_rejects_nonempty_sources(api_context):
    app, _db, _owner, _other, _router = api_context
    body = {**_valid_body(), "sources": ["file:///etc/passwd"]}
    with TestClient(app) as client:
        response = client.post("/api/v1/ppt-master/generate-incremental", json=body)
    assert response.status_code == 422


def test_incremental_generate_streams_standard_event_and_creates_task(api_context):
    from app.models import PPTIncrementalTask

    app, db, _owner, _other, _router = api_context
    with TestClient(app) as client:
        response = client.post("/api/v1/ppt-master/generate-incremental", json=_valid_body())

    assert response.status_code == 200
    assert "event: planning.started" in response.text
    data_line = next(line for line in response.text.splitlines() if line.startswith("data: "))
    event = json.loads(data_line.removeprefix("data: "))
    assert event["event_type"] == "planning.started"
    assert event["sequence"] == 1
    task = db.query(PPTIncrementalTask).filter(PPTIncrementalTask.request_id == "incremental-api-001").one()
    assert task.user_id == 1


def test_incremental_generate_persists_explicit_source_manifest(api_context, monkeypatch):
    from app.PPT_master.source_context import SourceContextResult
    from app.models import PPTIncrementalTask

    app, db, _owner, _other, router = api_context
    captured = {}

    def fake_resolve(**kwargs):
        captured["resolve"] = kwargs
        return SourceContextResult(
            source_context="【来源：brief.docx】\n收入增长 18%",
            source_manifest=[{
                "kind": "file", "file_id": 12, "parsed_file_id": 22,
                "filename": "brief.docx", "chunk_id": 3,
                "page_start": 1, "page_end": 1, "content_sha256": "abc",
            }],
            attachment_file_ids=[12],
            knowledge_doc_ids=[101],
            skipped_sources=[],
        )

    async def fake_workflow(**kwargs):
        captured["workflow"] = kwargs
        await kwargs["event_sink"]({
            "event_id": "evt_source_1", "event_type": "planning.started",
            "task_id": kwargs["task_id"], "project_id": kwargs["project_id"],
            "sequence": 1, "timestamp": "2026-07-21T00:00:00Z", "data": {"status": "planning"},
        })

    monkeypatch.setattr(router, "resolve_ppt_sources", fake_resolve, raising=False)
    monkeypatch.setattr(router, "run_incremental_workflow", fake_workflow)
    body = {
        **_valid_body("incremental-api-sources"),
        "attachment_file_ids": [12],
        "knowledge_doc_ids": [101],
        "source_policy": "parsed_only",
    }
    with TestClient(app) as client:
        response = client.post("/api/v1/ppt-master/generate-incremental", json=body)

    assert response.status_code == 200
    assert captured["resolve"]["attachment_file_ids"] == [12]
    assert captured["workflow"]["source_context"] == "【来源：brief.docx】\n收入增长 18%"
    task = db.query(PPTIncrementalTask).filter(PPTIncrementalTask.request_id == "incremental-api-sources").one()
    assert task.source_refs_json
    snapshot = router._store.snapshot(db, task.task_id, 1)
    assert snapshot["sources"]["knowledge_doc_ids"] == [101]
    assert snapshot["sources"]["source_manifest"][0]["file_id"] == 12


def test_incremental_duplicate_request_returns_existing_task_id(api_context):
    from app.PPT_master.incremental_store import IncrementalTaskStore

    app, db, _owner, _other, _router = api_context
    IncrementalTaskStore().create_task(
        db,
        task_id="pptinc_existing",
        project_id="pptproj_existing",
        user_id=1,
        request_id="incremental-api-duplicate",
        page_count=4,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ppt-master/generate-incremental",
            json=_valid_body("incremental-api-duplicate"),
        )
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "duplicate_incremental_request",
        "task_id": "pptinc_existing",
    }


def test_task_query_returns_snapshot_and_hides_other_owner(api_context):
    from app.PPT_master.incremental_store import IncrementalTaskStore

    app, db, _owner, other, _router = api_context
    store = IncrementalTaskStore()
    store.create_task(
        db,
        task_id="pptinc_query_001",
        project_id="pptproj_query_001",
        user_id=1,
        request_id="incremental-query-001",
        page_count=4,
    )
    store.append_event(db, "pptinc_query_001", "planning.started", {"status": "planning"})

    with TestClient(app) as client:
        owner_response = client.get("/api/v1/ppt-master/tasks/pptinc_query_001")
    assert owner_response.status_code == 200
    assert owner_response.json()["data"]["sequence"] == 1

    app.dependency_overrides[get_current_user] = lambda: other
    with TestClient(app) as client:
        other_response = client.get("/api/v1/ppt-master/tasks/pptinc_query_001")
    assert other_response.status_code == 404


def test_incremental_and_legacy_routes_share_generation_limiter():
    import app.PPT_master.incremental_router as incremental_router
    from app.PPT_master.admission import generation_limiter

    legacy_router = importlib.import_module("app.PPT_master.router")

    assert legacy_router._generation_limiter is generation_limiter
    assert incremental_router.generation_limiter is generation_limiter


def test_openapi_keeps_legacy_generate_and_adds_incremental_routes(api_context):
    app, _db, _owner, _other, _router = api_context
    paths = app.openapi()["paths"]
    assert "/api/v1/ppt-master/generate" in paths
    assert "/api/v1/ppt-master/generate-incremental" in paths
    assert "/api/v1/ppt-master/tasks/{task_id}" in paths


def test_source_resolution_failure_releases_generation_lease(api_context, monkeypatch):
    from app.PPT_master.source_context import SourceResolutionError
    app, _db, _owner, _other, router = api_context
    class Lease:
        released = False
        async def release(self): self.released = True
    lease = Lease()
    async def acquire(_user_id): return lease
    def fail_resolve(**_kwargs): raise SourceResolutionError("source_not_found")
    monkeypatch.setattr(router.generation_limiter, "acquire_nowait", acquire)
    monkeypatch.setattr(router, "resolve_ppt_sources", fail_resolve)
    with TestClient(app) as client:
        response = client.post("/api/v1/ppt-master/generate-incremental", json=_valid_body("incremental-source-release"))
    assert response.status_code == 422
    assert lease.released is True


def test_legacy_user_owned_image_bypasses_text_source_resolution(api_context, monkeypatch):
    from app.models import File
    from app.PPT_master.source_context import SourceContextResult
    app, db, _owner, _other, router = api_context
    db.add(File(id=77, user_id=1, owner_user_id=None, filename="source.png", filepath="/missing.png", real_path="/missing.png", mime_type=None, filetype=".png")); db.commit()
    captured = {}
    def resolve(**kwargs):
        captured.update(kwargs)
        return SourceContextResult("", [], [], [], [])
    monkeypatch.setattr(router, "resolve_ppt_sources", resolve)
    monkeypatch.setattr(router, "_media_feature_enabled", lambda _user: False)
    with TestClient(app) as client:
        response = client.post("/api/v1/ppt-master/generate-incremental", json={**_valid_body("incremental-legacy-image"), "attachment_file_ids": [77]})
    assert response.status_code == 200
    assert captured["attachment_file_ids"] == []


def test_legacy_image_extension_is_registered_as_media(api_context, monkeypatch):
    from app.models import File

    _app, db, _owner, _other, router = api_context
    db.add(File(id=78, user_id=1, owner_user_id=None, filename="legacy.png", filepath="/missing.png", real_path="/missing.png", mime_type=None, filetype=".png")); db.commit()
    registered = {}

    def register_file(_db, **kwargs):
        registered.update(kwargs)
        return {"asset_id": "pptimg_legacy", "file_id": kwargs["file_id"]}

    monkeypatch.setattr(router._media_resolver, "register_file", register_file)
    monkeypatch.setattr(router._media_adapter, "extract_document_images", lambda *_args, **_kwargs: pytest.fail("image must not use document extractor"))
    assets = router._collect_source_media(db, project_id="pptproj_test", owner_user_id=1, file_ids=[78])

    assert assets == [{"asset_id": "pptimg_legacy", "file_id": 78}]
    assert registered["source_type"] == "uploaded"
