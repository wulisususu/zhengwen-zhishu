"""Policy router: authentication, admin-only sync, envelopes. No real network."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.policy import errors
from app.services.policy.client import PolicyClient
from app.services.policy.service import PolicyRetrievalService, get_policy_service
from app.services.policy.settings import settings_from_mapping
from app.services.policy.store import PolicyStore
from policy_support import FakeClock, FakeHttp, FakeResponse, block_network, load_fixture  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


@pytest.fixture()
def api(monkeypatch, tmp_path):
    from app import models  # noqa: F401
    from app.database import Base, get_db
    from app.deps import get_current_user
    from app.routers import policy

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    holder = {"mode": "cloud_allowed", "user": None}
    settings = settings_from_mapping({"enabled": True, "base_url": "https://example.invalid/data", "db_path": str(tmp_path / "p.db")})
    clock = FakeClock()
    http = FakeHttp([FakeResponse(load_fixture("search_page.json"))])
    monkeypatch.setattr(requests, "get", http)
    mode = lambda: holder["mode"]  # noqa: E731
    client = PolicyClient(settings, sleep=clock.sleep, clock=clock.monotonic, mode_provider=mode)
    service = PolicyRetrievalService(settings, PolicyStore(settings.db_path), client, mode_provider=mode)

    app = FastAPI()
    app.include_router(policy.router, prefix="/api/v1")

    def _db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_policy_service] = lambda: service

    def login(user):
        if user is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: user

    return SimpleNamespace(client=TestClient(app), login=login, holder=holder, http=http, service=service)


USER = SimpleNamespace(id=1, username="u", is_admin=False)
ADMIN = SimpleNamespace(id=2, username="admin", is_admin=True)


@pytest.mark.parametrize(
    "method, path",
    [("get", "/api/v1/policy/search?q=数据"), ("get", "/api/v1/policy/documents"), ("get", "/api/v1/policy/documents/1"), ("post", "/api/v1/policy/sync")],
)
def test_unauthenticated_requests_get_401(api, method, path):
    api.login(None)
    kwargs = {"json": {"topic": "数据"}} if method == "post" else {}
    assert getattr(api.client, method)(path, **kwargs).status_code == 401


def test_non_admin_cannot_sync(api):
    api.login(USER)
    response = api.client.post("/api/v1/policy/sync", json={"topic": "数据安全"})
    assert response.status_code == 403
    assert api.http.calls == []


def test_admin_can_sync_and_documents_are_listed(api):
    api.login(ADMIN)
    body = api.client.post("/api/v1/policy/sync", json={"topic": "数据安全", "pages": 1, "per_page": 20}).json()
    assert body["code"] == 0
    assert body["data"]["inserted"] == 3
    api.login(USER)
    listed = api.client.get("/api/v1/policy/documents?page=1&page_size=2").json()["data"]
    assert listed["total"] == 3 and len(listed["items"]) == 2
    doc_id = listed["items"][0]["id"]
    detail = api.client.get(f"/api/v1/policy/documents/{doc_id}").json()
    assert detail["code"] == 0 and detail["data"]["id"] == doc_id
    assert api.client.get("/api/v1/policy/documents/99999").json()["code"] == 40400


def test_search_returns_hits_with_source(api):
    api.login(USER)
    body = api.client.get("/api/v1/policy/search", params={"q": "数据安全", "limit": 5}).json()
    assert body["code"] == 0
    assert body["data"]["source"] == "local+remote"
    assert {"title", "doc_number", "issuer", "publish_date", "url", "verified_status"} <= set(body["data"]["hits"][0])


def test_search_in_intranet_mode_is_local_only_with_no_request(api):
    api.holder["mode"] = "intranet"
    api.login(USER)
    body = api.client.get("/api/v1/policy/search", params={"q": "数据安全"}).json()
    assert body["code"] == 0
    assert body["data"]["source"] == "local_only"
    assert body["data"]["error"]["code"] == errors.EGRESS_BLOCKED
    assert api.http.calls == []


def test_sync_in_offline_mode_reports_error_code(api):
    api.holder["mode"] = "offline"
    api.login(ADMIN)
    body = api.client.post("/api/v1/policy/sync", json={"topic": "数据安全"}).json()
    assert body["code"] == 50200
    assert body["data"]["error"]["code"] == errors.EGRESS_BLOCKED
    assert api.http.calls == []


def test_query_validation(api):
    api.login(USER)
    assert api.client.get("/api/v1/policy/search", params={"q": ""}).status_code == 422
    assert api.client.get("/api/v1/policy/search", params={"q": "x" * 101}).status_code == 422
    assert api.client.get("/api/v1/policy/search", params={"q": "  "}).json()["code"] == 40000
    api.login(ADMIN)
    assert api.client.post("/api/v1/policy/sync", json={"topic": "数据", "pages": 21}).status_code == 422
