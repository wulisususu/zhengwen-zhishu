"""HTTP layer of /api/v1/gov notices + docx endpoints (minimal app, no heavy imports)."""
import base64
import dataclasses
import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.deps import get_current_user
from app.routers import gov_docs
from app.services.gongwen import catalog
from app.services.gongwen.review import DRAFT_MARK
from app.services.gongwen.settings import DEFAULT_KIT, GongwenSettings

HERE = Path(__file__).resolve().parent
NOTICES = HERE / "fixtures" / "gongwen" / "notices"
INNET = HERE / "fixtures" / "gongwen" / "innet"
HAS_KIT = bool(shutil.which("node")) and (DEFAULT_KIT / "node_modules").is_dir()
needs_kit = pytest.mark.skipif(not HAS_KIT, reason="node or backend/third_party/gongwen-kit not installed")

USER = SimpleNamespace(id=1, username="drafter", is_admin=False)
ADMIN = SimpleNamespace(id=2, username="admin", is_admin=True)


def notice(name: str) -> dict:
    return json.loads((NOTICES / f"{name}.json").read_text(encoding="utf-8"))


def make_client(user=USER, settings: GongwenSettings | None = None, auth_override=True):
    api = FastAPI()
    api.include_router(gov_docs.router, prefix="/api/v1")
    api.dependency_overrides[get_db] = lambda: iter([None])
    api.dependency_overrides[gov_docs.get_gongwen_settings] = lambda: settings or GongwenSettings()
    if auth_override:
        api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def upload(client, path: str, content: bytes, name: str):
    return client.post(f"/api/v1/gov/{path}", files={"file": (name, content, "application/octet-stream")})


# ── 认证与参数校验（不需要 gongwen-kit）──────────────────────────────────
def test_every_endpoint_requires_login():
    client = make_client(auth_override=False)
    body = {"draft": notice("standard_notice"), "kind": "internal_draft"}
    assert client.post("/api/v1/gov/notices/review", json=notice("standard_notice")).status_code == 401
    assert client.post("/api/v1/gov/notices/export", json=body).status_code == 401
    for path in ("docx/check", "docx/fix"):
        assert upload(client, path, b"PK\x03\x04", "a.docx").status_code == 401


def test_invalid_draft_is_rejected_before_any_tool_runs():
    client = make_client(settings=GongwenSettings(node_bin="/nonexistent/node"))
    bad = notice("standard_notice") | {"docType": "report"}
    assert client.post("/api/v1/gov/notices/review", json=bad).status_code == 422
    assert client.post("/api/v1/gov/notices/export", json={"draft": notice("standard_notice"), "kind": "print"}).status_code == 422


def test_formal_export_needs_formal_issue_permission():
    client = make_client(USER)
    resp = client.post("/api/v1/gov/notices/export", json={"draft": notice("standard_notice"), "kind": "formal"})
    assert resp.status_code == 403


@pytest.mark.parametrize("name,content,size_limit", [
    ("a.txt", b"PK\x03\x04rest", None),
    ("renamed.docx", b"plain text, not a zip", None),
    ("big.docx", b"PK\x03\x04" + b"0" * 2000, 1000),
])
def test_upload_type_and_size_limits(name, content, size_limit):
    settings = GongwenSettings(max_upload_bytes=size_limit or 10 * 1024 * 1024)
    for path in ("docx/check", "docx/fix"):
        body = upload(make_client(settings=settings), path, content, name).json()
        assert body["code"] == 40000, body


# ── 生成、导出与审校门槛 ──────────────────────────────────────────────────
@needs_kit
def test_review_returns_review_issues_and_gate():
    body = make_client().post("/api/v1/gov/notices/review", json=notice("defective_notice")).json()
    assert body["code"] == 0
    data = body["data"]
    assert data["origin"] == "backend" and data["formatCheck"]["status"] == "hit"
    assert data["gate"]["canApprove"] is False and data["gate"]["canExportFormal"] is False
    keys = {"id", "severity", "source", "title", "description", "locationLabel", "anchor", "section",
            "suggestion", "requiredField"}
    assert all(set(i) <= keys and "suggestion" not in i for i in data["issues"])
    assert {i.get("requiredField") for i in data["issues"]} >= {"recipient", "undertaker"}


@needs_kit
def test_internal_draft_export_returns_marked_docx_even_with_critical_issues():
    client = make_client()
    resp = client.post("/api/v1/gov/notices/export", json={"draft": notice("defective_notice"), "kind": "internal_draft"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(gov_docs.DOCX_MIME)
    assert resp.headers["x-gongwen-export-kind"] == "internal_draft"
    assert "filename*=UTF-8''" in resp.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    headers = [zf.read(n).decode() for n in zf.namelist() if n.startswith("word/header")]
    assert headers and all(DRAFT_MARK in h for h in headers)


@needs_kit
@pytest.mark.parametrize("name,message", [
    ("defective_notice", "严重问题"),
    ("standard_notice", "审批流程尚未接入"),
])
def test_formal_export_is_refused_by_the_backend_gate(name, message):
    body = make_client(ADMIN).post("/api/v1/gov/notices/export", json={"draft": notice(name), "kind": "formal"}).json()
    assert body["code"] == catalog.ERR_GATE and message in body["message"]
    assert body["data"]["gate"]["canExportFormal"] is False
    assert body["data"]["gate"]["canApprove"] is (name == "standard_notice")


def test_tool_failure_is_never_reported_as_pass():
    client = make_client(settings=GongwenSettings(node_bin="/nonexistent/node"))
    data = client.post("/api/v1/gov/notices/review", json=notice("standard_notice")).json()["data"]
    assert data["formatCheck"]["status"] == "unavailable" and data["formatCheck"]["errorCode"] == "NODE_NOT_FOUND"
    assert data["gate"]["canApprove"] is False
    body = client.post("/api/v1/gov/notices/export", json={"draft": notice("standard_notice"), "kind": "internal_draft"}).json()
    assert body["code"] == catalog.ERR_GONGWEN_TOOL and body["data"]["error"]["code"] == "NODE_NOT_FOUND"


# ── 外来 Word：原件保护 ────────────────────────────────────────────────────
@needs_kit
def test_upload_check_reports_and_leaves_the_upload_unchanged():
    content = (INNET / "innet_01_markdown_to_docx.docx").read_bytes()
    body = upload(make_client(), "docx/check", content, "关于 开展培训（第2稿）.docx").json()
    assert body["code"] == 0
    data = body["data"]
    assert data["file"] == {"name": "关于 开展培训（第2稿）.docx", "bytes": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(), "unchanged": True}
    assert data["docType"] == "external_docx" and data["formatCheck"]["status"] == "hit"


@needs_kit
def test_upload_fix_returns_a_copy_and_makes_no_compliance_claim():
    content = (INNET / "innet_01_markdown_to_docx.docx").read_bytes()
    body = upload(make_client(), "docx/fix", content, "通知.docx").json()
    assert body["code"] == 0
    data = body["data"]
    fixed = base64.b64decode(data["docxBase64"])
    assert fixed.startswith(b"PK\x03\x04") and fixed != content
    assert data["original"]["unchanged"] is True and data["original"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert data["filename"] == "通知-修订.docx"
    assert data["complianceClaim"] is False and "不代表符合 GB/T 9704" in data["complianceNote"]
    assert data["postReview"]["formatCheck"]["status"] == "pass"


@needs_kit
def test_fix_tool_timeout_is_reported(tmp_path):
    kit = tmp_path / "kit"
    (kit / "bin").mkdir(parents=True)
    (kit / "node_modules").mkdir()
    (kit / "bin" / "gongwen.js").write_text("setTimeout(() => {}, 60000)", encoding="utf-8")
    settings = dataclasses.replace(GongwenSettings(), kit_path=kit, fix_timeout_seconds=1.0)
    content = (INNET / "innet_01_markdown_to_docx.docx").read_bytes()
    body = upload(make_client(settings=settings), "docx/fix", content, "a.docx").json()
    assert body["code"] == catalog.ERR_GONGWEN_TOOL and body["data"]["error"]["code"] == "TIMEOUT"
