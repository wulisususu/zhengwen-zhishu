"""Real JWT + real SQLite API contract; no mocked network or document storage."""
from contextlib import contextmanager
import importlib

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
    monkeypatch.setattr(config, "_config", {"jwt": {"secret": "isolated-gov-test-secret", "algorithm": "HS256", "expire_minutes": 60}})
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    try:
        gov = importlib.import_module("app.gov.router")
    except ModuleNotFoundError as exc:
        if exc.name not in {"app.gov", "app.gov.router"}:
            raise
        gov = None
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for name, admin in [("writer", False), ("other", False), ("reviewer", True)]:
            db.add(User(username=name, nickname=name, password_hash=PASSWORD_HASH, is_admin=admin))
        db.commit()
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    if gov:
        app.include_router(gov.router, prefix="/api/v1")
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        tokens = {}
        for name in ["writer", "other", "reviewer"]:
            result = client.post("/api/v1/auth/login", json={"username": name, "password": "local-test-password"})
            tokens[name] = {"Authorization": "Bearer " + result.json()["data"]["access_token"]}
        yield client, tokens, factory
    engine.dispose()


def create(client, headers, **extra):
    body = {"title": "测试通知", "docType": "notice", "body": "一、工作安排\n请各单位认真落实。", "fields": {"recipient": "各单位", "issuer": "测试办公室", "undertaker": "张三"}, "signDate": "2026年10月26日",
            "docNumber": {"text": "测办发〔2026〕8号"}, "banji": {"printer": "测试办公室", "printDate": "2026年10月26日"}} | extra
    response = client.post("/api/v1/gov/documents", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def action(client, token, doc, name, **extra):
    return client.post(f"/api/v1/gov/documents/{doc['id']}/{name}", headers=token, json={"version": doc["version"]} | extra)


def test_actor_requires_real_login(app_client):
    client, tokens, _ = app_client
    assert client.get("/api/v1/gov/actor").status_code == 401
    actor = client.get("/api/v1/gov/actor", headers=tokens["writer"]).json()["data"]
    assert actor["origin"] == "backend" and actor["account"] == "writer"
    assert actor["roles"] == ["drafter"] and actor["canFormalIssue"] is False
    reviewer = client.get("/api/v1/gov/actor", headers=tokens["reviewer"]).json()["data"]
    assert "reviewer" in reviewer["roles"] and reviewer["canFormalIssue"] is False


def test_create_save_and_reload_are_persistent(app_client):
    client, tokens, factory = app_client
    doc = create(client, tokens["writer"])
    assert doc["origin"] == "backend" and doc["authorAccount"] == "writer"
    assert doc["status"] == "draft" and doc["checkStatus"] == "not_run"
    response = client.put(f"/api/v1/gov/documents/{doc['id']}", headers=tokens["writer"], json={"version": doc["version"], "title": "修订通知", "body": "新正文"})
    assert response.status_code == 200
    saved = response.json()["data"]
    assert saved["version"] == doc["version"] + 1
    loaded = client.get(f"/api/v1/gov/documents/{doc['id']}", headers=tokens["writer"]).json()["data"]
    assert loaded == saved
    assert any("新正文" in s.get("text", "") for b in loaded["blocks"] for s in b["segments"])
    assert any(r["action"] == "保存草稿" for r in loaded["history"])
    from app.gov.models import GovDocument
    with factory() as db:
        assert db.get(GovDocument, doc["id"]).version == saved["version"]


def test_other_user_cannot_read_edit_or_list_document(app_client):
    client, tokens, _ = app_client
    doc = create(client, tokens["writer"])
    path = f"/api/v1/gov/documents/{doc['id']}"
    assert client.get(path, headers=tokens["other"]).status_code == 404
    assert client.put(path, headers=tokens["other"], json={"version": 1, "title": "覆盖"}).status_code == 404
    assert client.get("/api/v1/gov/documents", headers=tokens["other"]).json()["data"] == []
    assert client.get(path, headers=tokens["reviewer"]).status_code == 404  # private draft


def test_stale_version_does_not_overwrite_new_content(app_client):
    client, tokens, _ = app_client
    doc = create(client, tokens["writer"])
    path = f"/api/v1/gov/documents/{doc['id']}"
    assert client.put(path, headers=tokens["writer"], json={"version": doc["version"], "title": "最新版本"}).status_code == 200
    assert client.put(path, headers=tokens["writer"], json={"version": doc["version"], "title": "过期覆盖"}).status_code == 409
    assert client.get(path, headers=tokens["writer"]).json()["data"]["title"] == "最新版本"


def test_return_revise_resubmit_and_approve(app_client):
    client, tokens, _ = app_client
    doc = create(client, tokens["writer"])
    pending = action(client, tokens["writer"], doc, "submit").json()["data"]
    assert pending["status"] == "pending"
    path = f"/api/v1/gov/documents/{doc['id']}"
    assert client.put(path, headers=tokens["writer"], json={"version": pending["version"], "title": "锁定时修改"}).status_code == 409
    assert action(client, tokens["writer"], pending, "approve").status_code == 403
    assert action(client, tokens["reviewer"], pending, "return", opinion="").status_code == 422
    returned = action(client, tokens["reviewer"], pending, "return", opinion="请完善说明").json()["data"]
    assert returned["status"] == "returned"
    revised = client.put(path, headers=tokens["writer"], json={"version": returned["version"], "body": "已完善的正文"}).json()["data"]
    pending = action(client, tokens["writer"], revised, "submit").json()["data"]
    approved = action(client, tokens["reviewer"], pending, "approve", opinion="人工核对通过").json()["data"]
    assert approved["status"] == "approved" and approved["checkStatus"] == "completed"
    assert approved["history"][-1]["actor"] == "reviewer"
    assert "人工" in approved["history"][-1]["note"]
    assert action(client, tokens["reviewer"], approved, "approve").status_code == 409


def test_admin_cannot_review_own_document(app_client):
    client, tokens, _ = app_client
    doc = create(client, tokens["reviewer"])
    pending = action(client, tokens["reviewer"], doc, "submit").json()["data"]
    assert action(client, tokens["reviewer"], pending, "approve").status_code == 403
    assert action(client, tokens["reviewer"], pending, "return", opinion="自己退回").status_code == 403


@pytest.mark.parametrize("extra", [{"title": ""}, {"docType": "unknown"}, {"authorAccount": "other"}, {"status": "approved"}])
def test_invalid_or_forged_create_payload_is_rejected(app_client, extra):
    client, tokens, _ = app_client
    response = client.post("/api/v1/gov/documents", headers=tokens["writer"], json={"title": "通知", "docType": "notice"} | extra)
    assert response.status_code == 422


def test_auto_review_failure_is_explicit_and_never_a_pass(app_client, monkeypatch):
    from app.services.gongwen.settings import GongwenSettings
    from app.gov import proofread
    monkeypatch.setattr(proofread, "load_settings", lambda: GongwenSettings(node_bin="missing-node-test-only"))
    client, tokens, _ = app_client
    doc = create(client, tokens["writer"])
    response = action(client, tokens["writer"], doc, "check")
    assert response.status_code == 200
    review = response.json()["data"]["review"]
    assert review["formatCheck"]["status"] == "unavailable" and not review["gate"]["canApprove"]


def test_upload_associate_unlink_does_not_delete_file(app_client, tmp_path, monkeypatch):
    client, tokens, factory = app_client
    monkeypatch.setenv("GOV_DATA_DIR", str(tmp_path / "uploads"))
    doc = create(client, tokens["writer"])
    uploaded = client.post("/api/v1/gov/materials", headers=tokens["writer"], files={"file": ("工作材料.txt", "会议安排".encode(), "text/plain")})
    assert uploaded.status_code == 200
    material = uploaded.json()["data"]
    response = client.post(f"/api/v1/gov/documents/{doc['id']}/materials", headers=tokens["writer"], json={"version": doc["version"], "fileIds": [int(material["id"])]})
    assert response.status_code == 200
    linked = response.json()["data"]
    assert linked["materials"][0]["name"] == "工作材料.txt"
    assert client.get(f"/api/v1/gov/materials/{material['id']}/download", headers=tokens["other"]).status_code == 404
    unlinked = client.delete(f"/api/v1/gov/documents/{doc['id']}/materials/{material['id']}?version={linked['version']}", headers=tokens["writer"])
    assert unlinked.status_code == 200 and unlinked.json()["data"]["materials"] == []
    result = client.get(f"/api/v1/gov/materials/{material['id']}/download", headers=tokens["writer"])
    assert result.content == "会议安排".encode()


def test_foreign_material_and_stale_material_update_are_rejected(app_client, tmp_path, monkeypatch):
    client, tokens, _ = app_client
    monkeypatch.setenv("GOV_DATA_DIR", str(tmp_path / "uploads"))
    uploaded = client.post("/api/v1/gov/materials", headers=tokens["other"], files={"file": ("其他人.txt", b"private", "text/plain")})
    assert uploaded.status_code == 200
    file_id = int(uploaded.json()["data"]["id"])
    doc = create(client, tokens["writer"])
    path = f"/api/v1/gov/documents/{doc['id']}/materials"
    assert client.post(path, headers=tokens["writer"], json={"version": 1, "fileIds": [file_id]}).status_code == 404
    assert client.get(f"/api/v1/gov/documents/{doc['id']}", headers=tokens["writer"]).json()["data"]["version"] == 1


def test_internal_export_is_real_a4_docx_with_watermark(app_client):
    import io
    import zipfile
    import xml.etree.ElementTree as ET
    client, tokens, _ = app_client
    doc = create(client, tokens["writer"])
    path = f"/api/v1/gov/documents/{doc['id']}/export"
    assert client.post(path, headers=tokens["other"], json={"kind": "internal_draft"}).status_code == 404
    assert client.post(path, headers=tokens["writer"], json={"kind": "formal"}).status_code == 403
    response = client.post(path, headers=tokens["writer"], json={"kind": "internal_draft"})
    assert response.status_code == 200
    assert "wordprocessingml" in response.headers["content-type"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        text = z.read("word/document.xml").decode()
        assert "测试通知" in text and "请各单位认真落实" in text
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        size = ET.fromstring(text).find(".//w:pgSz", ns)
        assert abs(int(size.attrib['{' + ns['w'] + '}w']) - 11906) <= 1
        assert abs(int(size.attrib['{' + ns['w'] + '}h']) - 16838) <= 1
        headers = b"".join(z.read(n) for n in z.namelist() if n.startswith("word/header"))
        assert "内部草稿".encode() in headers and "未审核".encode() in headers


@pytest.mark.parametrize("filename", ["script.exe", "noextension"])
def test_material_upload_validates_type(app_client, filename):
    client, tokens, _ = app_client
    assert client.post("/api/v1/gov/materials", headers=tokens["writer"], files={"file": (filename, b"test")}).status_code == 422


def generation_module():
    import importlib.util
    assert importlib.util.find_spec("app.gov.generation") is not None, "model generation boundary is missing"
    return importlib.import_module("app.gov.generation")


@pytest.mark.parametrize("result", [{"error": "unavailable"}, {"text": ""}])
def test_model_failure_keeps_saved_document(app_client, monkeypatch, result):
    client, tokens, _ = app_client
    module = generation_module()
    monkeypatch.setattr(module, "generate_text", lambda prompt: result)
    doc = create(client, tokens["writer"])
    response = action(client, tokens["writer"], doc, "generate", prompt="请起草通知")
    assert response.status_code == 503
    loaded = client.get(f"/api/v1/gov/documents/{doc['id']}", headers=tokens["writer"]).json()["data"]
    assert loaded["version"] == doc["version"] and loaded["body"] == doc["body"]


def test_model_success_is_persisted_with_server_version(app_client, monkeypatch):
    client, tokens, _ = app_client
    module = generation_module()
    monkeypatch.setattr(module, "generate_text", lambda prompt: {"text": "真实模型接口测试替身输出"})
    doc = create(client, tokens["writer"])
    response = action(client, tokens["writer"], doc, "generate", prompt="请起草通知")
    assert response.status_code == 200
    saved = response.json()["data"]
    assert saved["body"] == "真实模型接口测试替身输出" and saved["version"] == doc["version"] + 1
    assert saved["checkStatus"] == "not_run"


def test_model_result_does_not_overwrite_concurrent_edit(app_client, monkeypatch):
    client, tokens, factory = app_client
    module = generation_module()
    doc = create(client, tokens["writer"])
    def generate(prompt):
        from sqlalchemy import update
        from app.gov.models import GovDocument
        with factory() as db:
            db.execute(update(GovDocument).where(GovDocument.id == doc["id"]).values(version=99))
            db.commit()
        return {"text": "过期生成结果"}
    monkeypatch.setattr(module, "generate_text", generate)
    assert action(client, tokens["writer"], doc, "generate", prompt="起草").status_code == 409


def test_blank_saved_title_is_validation_error_not_server_error(app_client):
    client, tokens, _ = app_client
    doc = create(client, tokens["writer"])
    assert client.put(f"/api/v1/gov/documents/{doc['id']}", headers=tokens["writer"], json={"version": doc["version"], "title": "   "}).status_code == 422


def test_future_version_cannot_cross_concurrent_submit_lock(app_client, monkeypatch):
    from app.gov import service
    from app.gov.models import GovDocument
    from sqlalchemy import update
    client, tokens, factory = app_client
    doc = create(client, tokens["writer"])
    original = service.write_revision
    def concurrent_submit(db, current, version, **kwargs):
        with factory() as other:
            other.execute(update(GovDocument).where(GovDocument.id == doc["id"]).values(status="pending", version=2))
            other.commit()
        return original(db, current, version, **kwargs)
    monkeypatch.setattr(service, "write_revision", concurrent_submit)
    response = client.put(f"/api/v1/gov/documents/{doc['id']}", headers=tokens["writer"], json={"version": 2, "body": "不应写入的正文"})
    assert response.status_code == 409
    loaded = client.get(f"/api/v1/gov/documents/{doc['id']}", headers=tokens["writer"]).json()["data"]
    assert loaded["body"] == doc["body"] and loaded["status"] == "pending"


def test_legacy_delete_cannot_remove_linked_review_material(app_client, tmp_path, monkeypatch):
    client, tokens, _ = app_client
    from app.routers import files
    client.app.include_router(files.router, prefix="/api/v1")
    monkeypatch.setenv("GOV_DATA_DIR", str(tmp_path / "uploads"))
    doc = create(client, tokens["writer"])
    uploaded = client.post("/api/v1/gov/materials", headers=tokens["writer"], files={"file": ("审核依据.txt", b"evidence")}).json()["data"]
    linked = client.post(f"/api/v1/gov/documents/{doc['id']}/materials", headers=tokens["writer"], json={"version": 1, "fileIds": [int(uploaded["id"])]}).json()["data"]
    pending = action(client, tokens["writer"], linked, "submit").json()["data"]
    assert client.delete(f"/api/v1/files/{uploaded['id']}", headers=tokens["writer"]).status_code == 409
    loaded = client.get(f"/api/v1/gov/documents/{doc['id']}", headers=tokens["writer"]).json()["data"]
    assert loaded["version"] == pending["version"] and len(loaded["materials"]) == 1
    assert client.get(f"/api/v1/gov/materials/{uploaded['id']}/download", headers=tokens["writer"]).content == b"evidence"


def test_long_valid_chinese_material_is_not_reported_as_bad_encoding(app_client, tmp_path, monkeypatch):
    client, tokens, _ = app_client
    module = generation_module()
    monkeypatch.setattr(module, "generate_text", lambda prompt: {"text": "不应静默截断生成"})
    monkeypatch.setenv("GOV_DATA_DIR", str(tmp_path / "uploads"))
    doc = create(client, tokens["writer"])
    uploaded = client.post("/api/v1/gov/materials", headers=tokens["writer"], files={"file": ("长材料.txt", ("中" * 30000).encode())}).json()["data"]
    linked = client.post(f"/api/v1/gov/documents/{doc['id']}/materials", headers=tokens["writer"], json={"version": 1, "fileIds": [int(uploaded["id"])]}).json()["data"]
    response = action(client, tokens["writer"], linked, "generate", prompt="起草")
    assert response.status_code == 422 and "过长" in response.json()["detail"]
    assert "编码" not in response.json()["detail"]
