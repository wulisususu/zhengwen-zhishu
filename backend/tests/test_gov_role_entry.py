"""Role entry (no login page): real JWT + real SQLite, same style as test_gov_basic_api."""
import importlib
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import config
from app.database import Base, _bootstrap_admin, get_db
from app.deps import hash_password
from app.models import User
from app.routers import auth, gov_policy, users
from app.services.policy.library import get_policy_library

SETTINGS = {"jwt": {"secret": "isolated-role-entry-secret", "algorithm": "HS256", "expire_minutes": 60}}
from app.services.gongwen.settings import DEFAULT_KIT

KIT_READY = bool(shutil.which("node")) and (DEFAULT_KIT / "node_modules").is_dir()


class FakeLibrary:
    def __init__(self):
        self.verified_by = None

    def verify(self, policy_id, *, status, note, fields, verifier):
        self.verified_by = verifier
        return {"policy": {"id": policy_id, "status": status}}

    def import_policy(self, req):
        return {"policy": {"id": 1, "title": req.title or "x"}}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_config", dict(SETTINGS))
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(User(username="admin", nickname="admin", password_hash=hash_password("pw-admin"), is_admin=True))
        db.commit()
    gov = importlib.import_module("app.gov.router")
    library = FakeLibrary()
    app = FastAPI()
    for module in (auth, users, gov_policy):
        app.include_router(module.router, prefix="/api/v1")
    app.include_router(gov.router, prefix="/api/v1")

    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_policy_library] = lambda: library
    with TestClient(app) as client:
        yield client, factory, library, engine
    engine.dispose()


def enter(client, role):
    response = client.post("/api/v1/gov/entry", json={"role": role})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    return {"Authorization": "Bearer " + data["access_token"]}, data


def create(client, headers):
    body = {"title": "测试通知", "docType": "notice", "body": "一、工作安排\n请各单位认真落实。",
            "fields": {"recipient": "各单位", "issuer": "测试办公室", "undertaker": "张三"}, "signDate": "2026年10月26日",
            "docNumber": {"text": "测办发〔2026〕8号"}, "banji": {"printer": "测试办公室", "printDate": "2026年10月26日"}}
    return client.post("/api/v1/gov/documents", headers=headers, json=body)


def act(client, headers, doc, name, **extra):
    return client.post(f"/api/v1/gov/documents/{doc['id']}/{name}", headers=headers, json={"version": doc["version"]} | extra)


# ── 入口本身 ──────────────────────────────────────────────────────────────
def test_entry_options_are_public(env):
    client, *_ = env
    data = client.get("/api/v1/gov/entry").json()["data"]
    assert data["enabled"] is True
    assert [(r["role"], r["label"]) for r in data["roles"]] == [("drafter", "起草人"), ("reviewer", "审核人")]


def test_each_role_gets_its_own_single_role_account(env):
    client, factory, *_ = env
    drafter, d = enter(client, "drafter")
    reviewer, r = enter(client, "reviewer")
    assert (d["role"], d["actor"]["roles"], d["actor"]["name"]) == ("drafter", ["drafter"], "起草人")
    assert (r["role"], r["actor"]["roles"], r["actor"]["name"]) == ("reviewer", ["reviewer"], "审核人")
    assert client.get("/api/v1/gov/actor", headers=drafter).json()["data"]["account"] == "role-entry-drafter"
    assert client.get("/api/v1/gov/actor", headers=reviewer).json()["data"]["account"] == "role-entry-reviewer"
    enter(client, "drafter")   # idempotent: still one account per role
    with factory() as db:
        rows = db.query(User).filter(User.username.like("role-entry-%")).all()
        assert sorted((u.username, u.gov_role, u.is_admin) for u in rows) == [
            ("role-entry-drafter", "drafter", False), ("role-entry-reviewer", "reviewer", False)]


def test_invalid_role_is_rejected(env):
    client, *_ = env
    assert client.post("/api/v1/gov/entry", json={"role": "admin"}).status_code == 422


def test_entry_can_be_switched_off(env, monkeypatch):
    client, *_ = env
    monkeypatch.setattr(config, "_config", SETTINGS | {"gov_entry": {"enabled": False}})
    assert client.get("/api/v1/gov/entry").json()["data"]["enabled"] is False
    assert client.post("/api/v1/gov/entry", json={"role": "drafter"}).status_code == 404


# ── 角色账号不是管理员，也打不开 ──────────────────────────────────────────
def test_role_accounts_have_no_admin_rights(env):
    client, *_ = env
    for role in ("drafter", "reviewer"):
        headers, _ = enter(client, role)
        assert client.get("/api/v1/users", headers=headers).status_code == 403


def test_role_accounts_cannot_be_opened_with_a_password(env):
    client, *_ = env
    enter(client, "reviewer")
    for password in ("", "role-entry-reviewer", "password"):
        body = client.post("/api/v1/auth/login", json={"username": "role-entry-reviewer", "password": password}).json()
        assert body["code"] != 0 and not (body.get("data") or {}).get("access_token")


def test_reserved_names_cannot_be_registered_or_created(env):
    client, *_ = env
    body = client.post("/api/v1/auth/register", json={"username": "role-entry-reviewer", "password": "x123456", "nickname": "x"}).json()
    assert body["code"] == 40000
    admin = client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw-admin"}).json()["data"]["access_token"]
    body = client.post("/api/v1/users", headers={"Authorization": "Bearer " + admin},
                       json={"username": "Role-Entry-drafter", "password": "x123456", "nickname": "x"}).json()
    assert body["code"] == 40000


@pytest.mark.parametrize("is_admin,gov_role", [(True, "reviewer"), (False, None)])
def test_conflicting_existing_account_is_never_adopted(env, is_admin, gov_role):
    client, factory, *_ = env
    with factory() as db:
        db.add(User(username="role-entry-reviewer", nickname="x", password_hash=hash_password("x"),
                    is_admin=is_admin, gov_role=gov_role))
        db.commit()
    response = client.post("/api/v1/gov/entry", json={"role": "reviewer"})
    assert response.status_code == 409 and "access_token" not in response.text


def test_admin_bootstrap_skips_role_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_config", dict(SETTINGS))
    engine = create_engine(f"sqlite:///{tmp_path / 'boot.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (username, password_hash, nickname, is_admin, gov_role) "
                          "VALUES ('role-entry-drafter', 'x', '', 0, 'drafter')"))
        _bootstrap_admin(conn)
        assert conn.execute(text("SELECT COUNT(*) FROM users WHERE is_admin = 1")).scalar() == 0
        conn.execute(text("INSERT INTO users (username, password_hash, nickname, is_admin) VALUES ('alice', 'x', '', 0)"))
        _bootstrap_admin(conn)
        admins = conn.execute(text("SELECT username FROM users WHERE is_admin = 1")).scalars().all()
    assert admins == ["alice"]
    monkeypatch.setattr(config, "_config", SETTINGS | {"security": {"admin_username": "role-entry-drafter"}})
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET is_admin = 0"))
        _bootstrap_admin(conn)
        assert conn.execute(text("SELECT COUNT(*) FROM users WHERE is_admin = 1")).scalar() == 0
    engine.dispose()


# ── 两条业务流程 ──────────────────────────────────────────────────────────
def test_drafter_flow_and_reviewer_flow_are_separated(env):
    client, *_ = env
    drafter, _ = enter(client, "drafter")
    reviewer, _ = enter(client, "reviewer")
    assert create(client, reviewer).status_code == 403          # 审核人不起草
    created = create(client, drafter)
    assert created.status_code == 200
    doc = created.json()["data"]
    assert client.get("/api/v1/gov/documents", headers=reviewer).json()["data"] == []   # 草稿只给起草人看
    submitted = act(client, drafter, doc, "submit").json()["data"]
    assert act(client, drafter, submitted, "return", opinion="自己退回").status_code == 403   # 起草人不能审核
    listed = client.get("/api/v1/gov/documents", headers=reviewer).json()["data"]
    assert [d["id"] for d in listed] == [doc["id"]] and listed[0]["status"] == "pending"
    returned = act(client, reviewer, submitted, "return", opinion="请补充附件说明")
    assert returned.status_code == 200 and returned.json()["data"]["status"] == "returned"
    saved = client.put(f"/api/v1/gov/documents/{doc['id']}", headers=reviewer,
                       json={"version": returned.json()["data"]["version"], "title": "审核人改稿"})
    assert saved.status_code in (403, 404)                       # 审核人不能改别人的稿


@pytest.mark.skipif(not KIT_READY, reason="approval runs the gongwen-kit review")
def test_reviewer_can_approve_a_submitted_notice(env):
    client, *_ = env
    drafter, _ = enter(client, "drafter")
    reviewer, _ = enter(client, "reviewer")
    doc = act(client, drafter, create(client, drafter).json()["data"], "submit").json()["data"]
    approved = act(client, reviewer, doc, "approve", opinion="同意")
    assert approved.status_code == 200 and approved.json()["data"]["status"] == "approved"


def test_policy_library_maintenance_is_for_reviewers(env):
    client, _, library, _ = env
    drafter, _ = enter(client, "drafter")
    reviewer, _ = enter(client, "reviewer")
    body = {"status": "current", "status_note": "人工核验"}
    assert client.post("/api/v1/gov/policies/1/verify", headers=drafter, json=body).status_code == 403
    assert client.post("/api/v1/gov/policies/1/verify", headers=reviewer, json=body).json()["code"] == 0
    assert library.verified_by == "role-entry-reviewer"
    assert client.post("/api/v1/gov/policies/import", headers=drafter, data={"url": "https://www.gov.cn/x"}).status_code == 403


@pytest.mark.parametrize("role", ["drafter", "reviewer"])
def test_role_account_cannot_be_promoted_by_admin(env, role):
    client, factory, *_ = env
    headers, _ = enter(client, role)
    with factory() as db:
        target_id = db.query(User).filter_by(gov_role=role).one().id
    admin = client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw-admin"}).json()["data"]["access_token"]
    response = client.put(f"/api/v1/users/{target_id}", headers={"Authorization": "Bearer " + admin}, json={"is_admin": True})
    assert response.status_code == 403
    assert client.get("/api/v1/users", headers=headers).status_code == 403
    with factory() as db:
        assert db.get(User, target_id).is_admin is False


def test_role_account_password_cannot_be_changed(env):
    client, factory, *_ = env
    headers, _ = enter(client, "reviewer")
    with factory() as db:
        user = db.query(User).filter_by(gov_role="reviewer").one()
        target_id, original_hash = user.id, user.password_hash
    response = client.put(f"/api/v1/users/{target_id}", headers=headers, json={"password": "chosen-password"})
    assert response.status_code == 403
    with factory() as db:
        assert db.get(User, target_id).password_hash == original_hash


def test_role_account_rejects_password_login_even_with_known_hash(env):
    client, factory, *_ = env
    enter(client, "reviewer")
    with factory() as db:
        db.query(User).filter_by(gov_role="reviewer").one().password_hash = hash_password("known-password")
        db.commit()
    response = client.post("/api/v1/auth/login", json={"username": "role-entry-reviewer", "password": "known-password"}).json()
    assert response["code"] != 0
    assert not (response.get("data") or {}).get("access_token")
