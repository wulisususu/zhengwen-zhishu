"""/api/v1/gov policy endpoints: auth, admin-only writes, multipart import, citations."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.policy import errors
from app.services.policy.fetcher import SafeFetcher
from app.services.policy.library import PolicyLibraryService, get_policy_library
from app.services.policy.settings import settings_from_mapping
from app.services.policy.store import PolicyStore
from policy_support import FakeClock, block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")

TEXT = "示例办法（演示）\n第一条　为了规范政务数据共享，制定本办法。\n第二条　数据提供部门应当在10个工作日内予以答复。\n第三条　本办法自发布之日起施行。"
USER = SimpleNamespace(id=1, username="u", is_admin=False)
ADMIN = SimpleNamespace(id=2, username="admin", is_admin=True)


@pytest.fixture()
def api(tmp_path):
    from app import models  # noqa: F401
    from app.database import Base, get_db
    from app.deps import get_current_user
    from app.routers import gov_policy

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)

    settings = settings_from_mapping({"enabled": True, "base_url": "https://example.invalid", "db_path": str(tmp_path / "p.db")})
    clock = FakeClock()

    def no_opener(*a, **k):
        raise AssertionError("router tests must not fetch")

    fetcher = SafeFetcher(settings.fetch, resolver=lambda *a, **k: [], opener=no_opener, mode_provider=lambda: "cloud_allowed", sleep=clock.sleep, clock=clock.monotonic)
    library = PolicyLibraryService(settings, PolicyStore(settings.db_path), fetcher)

    app = FastAPI()
    app.include_router(gov_policy.router, prefix="/api/v1")

    def _db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_policy_library] = lambda: library

    def login(user):
        if user is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: user

    return SimpleNamespace(client=TestClient(app), login=login, library=library)


def _import(api, text=TEXT, **form):
    return api.client.post(
        "/api/v1/gov/policies/import",
        data={"source_url": "https://www.gov.cn/zhengce/content/202501/content_9.htm", **form},
        files={"file": ("policy.txt", text.encode("utf-8"), "text/plain")},
    )


ENDPOINTS = [
    ("post", "/api/v1/gov/policies/import", {"data": {"url": "https://www.gov.cn/x"}}),
    ("get", "/api/v1/gov/policies", {}),
    ("post", "/api/v1/gov/policies/search", {"json": {"query": "数据"}}),
    ("post", "/api/v1/gov/citations/batch", {"json": {"ids": ["clause:1"]}}),
    ("post", "/api/v1/gov/policies/1/verify", {"json": {"status": "current"}}),
]


@pytest.mark.parametrize("method, path, kwargs", ENDPOINTS)
def test_all_endpoints_require_login(api, method, path, kwargs):
    api.login(None)
    assert getattr(api.client, method)(path, **kwargs).status_code == 401


@pytest.mark.parametrize("method, path, kwargs", [ENDPOINTS[0], ENDPOINTS[4]])
def test_import_and_verify_are_admin_only(api, method, path, kwargs):
    api.login(USER)
    assert getattr(api.client, method)(path, **kwargs).status_code == 403


def test_import_list_verify_search_and_cite(api):
    api.login(ADMIN)
    imported = _import(api, title="示例办法（演示）", issuer="示例市政务服务管理局（演示机关）").json()
    assert imported["code"] == 0
    policy_id = imported["data"]["policy"]["id"]
    assert imported["data"]["clause_count"] == 4

    api.login(USER)
    assert api.client.post("/api/v1/gov/policies/search", json={"query": "工作日"}).json()["data"]["hits"] == []
    listed = api.client.get("/api/v1/gov/policies", params={"status": "unverified"}).json()["data"]
    assert listed["total"] == 1 and listed["items"][0]["verified_status"] == "unverified"
    assert api.client.get("/api/v1/gov/policies", params={"status": "current"}).json()["data"]["total"] == 0

    api.login(ADMIN)
    verified = api.client.post(f"/api/v1/gov/policies/{policy_id}/verify", json={"status": "current", "status_note": "核验（演示）", "effective_date": "2025-03-01"}).json()
    assert verified["code"] == 0 and verified["data"]["policy"]["verified_by"] == "admin"

    api.login(USER)
    hits = api.client.post("/api/v1/gov/policies/search", json={"query": "工作日"}).json()["data"]["hits"]
    assert len(hits) == 1 and hits[0]["status"] == "current"
    citations = api.client.post("/api/v1/gov/citations/batch", json={"ids": [hits[0]["citation_id"]]}).json()["data"]["citations"]
    cite = citations[0]
    assert cite["effectiveOn"] == "2025-03-01"
    assert cite["text"]["highlight"] == "工作日"
    assert cite["previousClause"].startswith("第一条") and cite["nextClause"].startswith("第三条")


def test_validation_errors(api):
    api.login(USER)
    assert api.client.post("/api/v1/gov/policies/search", json={"query": "数据", "statuses": ["draft"]}).status_code == 422
    assert api.client.get("/api/v1/gov/policies", params={"status": "pending"}).status_code == 422
    assert api.client.post("/api/v1/gov/citations/batch", json={"ids": []}).status_code == 422
    api.login(ADMIN)
    assert api.client.post("/api/v1/gov/policies/1/verify", json={"status": "draft"}).status_code == 422
    missing = api.client.post("/api/v1/gov/policies/999/verify", json={"status": "current"}).json()
    assert missing["code"] == 40400
    bad_date = api.client.post("/api/v1/gov/policies/999/verify", json={"status": "current", "effective_date": "2025/3/1"}).json()
    assert bad_date["code"] == 40000


def test_import_without_source_is_a_param_error(api):
    api.login(ADMIN)
    body = api.client.post("/api/v1/gov/policies/import", data={}).json()
    assert body["code"] == 40000
    assert body["data"]["error"]["code"] == errors.INVALID_QUERY


def test_import_url_failure_offers_manual_upload(api):
    api.login(ADMIN)
    body = api.client.post("/api/v1/gov/policies/import", data={"url": "https://evil.example.com/x"}).json()
    assert body["code"] == 50200
    assert body["data"]["error"]["code"] == errors.FETCH_HOST_NOT_ALLOWED
    assert "人工上传" in body["data"]["error"]["fallback"]
