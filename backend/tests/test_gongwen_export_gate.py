"""公文导出只走既有文稿流程（审查发现 3 / 待办 4、6）。

- 不再有「客户端交 IR 即可导出」的入口；
- 导出以后端保存的版本为准，任意内容都不能经导出请求注入；
- 请示、报告、函、纪要用新渲染器出内部草稿，每页页眉带「未审核 · 内部草稿」；
- 正式版受审核与权限限制（目前不开放），他人与审核人看不到未送审草稿。
Real JWT + real SQLite, same setup as test_gov_basic_api.
"""
import importlib
import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config
from app.database import Base, get_db
from app.deps import hash_password
from app.models import User
from app.routers import auth

PASSWORD_HASH = hash_password("local-test-password")


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_config", {"jwt": {"secret": "isolated-gongwen-export-secret", "algorithm": "HS256", "expire_minutes": 60}})
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    gov = importlib.import_module("app.gov.router")
    gongwen = importlib.import_module("app.gongwen.router")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for name, admin, role in [("writer", False, None), ("other", False, None), ("role-entry-reviewer", False, "reviewer")]:
            db.add(User(username=name, nickname=name, password_hash=PASSWORD_HASH, is_admin=admin, gov_role=role))
        db.commit()
    app = FastAPI()
    for router in (auth.router, gov.router, gongwen.router):
        app.include_router(router, prefix="/api/v1")

    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        tokens = {}
        for name in ["writer", "other"]:
            token = client.post("/api/v1/auth/login", json={"username": name, "password": "local-test-password"}).json()["data"]["access_token"]
            tokens[name] = {"Authorization": "Bearer " + token}
        from app.deps import create_token
        with factory() as db:
            reviewer = db.query(User).filter_by(username="role-entry-reviewer").one()
            tokens["reviewer"] = {"Authorization": "Bearer " + create_token(reviewer.id)}
        yield client, tokens
    engine.dispose()


def create(client, headers, **extra):
    body = {"title": "关于申请调整数据平台运维经费的请示", "docType": "request",
            "body": "一、基本情况\n目前平台运维经费不足。\n二、请示事项\n拟申请调整运维经费。\n妥否，请批示。",
            "fields": {"recipient": "示例市财政局", "issuer": "示例市数据管理局", "undertaker": ""},
            "signDate": "2026年10月26日", "docNumber": {"text": "示数发〔2026〕3号"}} | extra
    response = client.post("/api/v1/gov/documents", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def export(client, headers, doc, kind="internal_draft", **extra):
    return client.post(f"/api/v1/gov/documents/{doc['id']}/export", headers=headers, json={"kind": kind, **extra})


def docx_parts(content: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return {n: z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.startswith("word/") and n.endswith(".xml")}


def test_client_supplied_ir_can_no_longer_be_exported(app_client):
    client, tokens = app_client
    resp = client.post("/api/v1/gongwen/render", headers=tokens["writer"], json={"ir": {"doc_type": "通知", "title": "x", "body": ["一、任务"]}})
    assert resp.status_code in (404, 405)


@pytest.mark.parametrize("doc_type,label", [("request", "请示"), ("report", "报告"), ("letter", "函"), ("minutes", "纪要")])
def test_saved_draft_exports_as_marked_internal_draft(app_client, doc_type, label):
    client, tokens = app_client
    doc = create(client, tokens["writer"], docType=doc_type, title=f"关于测试事项的{label}")
    resp = export(client, tokens["writer"], doc)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("application/vnd.openxmlformats")
    parts = docx_parts(resp.content)
    headers = [xml for name, xml in parts.items() if name.startswith("word/header")]
    assert len(headers) >= 2 and all("未审核" in h and "内部草稿" in h for h in headers)
    assert f"关于测试事项的{label}" in parts["word/document.xml"]
    assert 'w:w="11906"' in parts["word/document.xml"]                       # A4，新渲染器版式


def test_export_uses_the_saved_version_not_request_content(app_client):
    client, tokens = app_client
    doc = create(client, tokens["writer"])
    saved = client.put(f"/api/v1/gov/documents/{doc['id']}", headers=tokens["writer"],
                       json={"version": doc["version"], "body": "一、基本情况\n修订后的保存正文。\n妥否，请批示。"}).json()["data"]
    content = docx_parts(export(client, tokens["writer"], saved).content)["word/document.xml"]
    assert "修订后的保存正文" in content and "目前平台运维经费不足" not in content
    assert export(client, tokens["writer"], saved, body="注入内容").status_code == 422   # 导出请求不能夹带正文
    assert export(client, tokens["writer"], saved, ir={"title": "注入"}).status_code == 422


def test_formal_export_is_refused_and_others_cannot_export(app_client):
    client, tokens = app_client
    doc = create(client, tokens["writer"])
    assert export(client, tokens["writer"], doc, kind="formal").status_code == 403
    assert export(client, tokens["other"], doc).status_code == 404
    assert export(client, tokens["reviewer"], doc).status_code == 404          # 未送审草稿不对审核人可见


def test_reviewer_role_cannot_create_drafts_from_the_drafting_page(app_client):
    client, tokens = app_client
    resp = client.post("/api/v1/gov/documents", headers=tokens["reviewer"], json={"title": "审核人起草", "docType": "request", "body": "一、内容"})
    assert resp.status_code == 403


@pytest.mark.parametrize("urgency", ["急件", "特急"])
@pytest.mark.parametrize("doc_type", ["request", "notice"])
def test_saved_urgency_survives_update_and_docx_export(app_client, urgency, doc_type):
    client, tokens = app_client
    doc = create(client, tokens["writer"], docType=doc_type, urgency=urgency)
    assert doc["urgency"] == urgency
    response = client.put(f"/api/v1/gov/documents/{doc['id']}", headers=tokens["writer"], json={"version": doc["version"], "body": "一、工作安排\n请认真落实。"})
    assert response.status_code == 200
    saved = response.json()["data"]
    assert saved["urgency"] == urgency
    response = export(client, tokens["writer"], saved)
    assert response.status_code == 200
    assert urgency in docx_parts(response.content)["word/document.xml"]
