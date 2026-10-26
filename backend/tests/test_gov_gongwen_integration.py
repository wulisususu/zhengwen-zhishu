"""Persistent notice integration: real JWT/SQLite and server-owned review gates."""
import io
import json
import zipfile
import pytest
from test_gov_basic_api import app_client, action, create


def notice(client, token, **extra):
    return create(client, token, docNumber={"text": "测办发〔2026〕8号"},
                  banji={"printer": "测试办公室", "printDate": "2026年10月26日", "copyTo": []},
                  signDate="2026年10月26日", **extra)


def report(critical=False, unavailable=False):
    issues = [{"id": "server-critical", "severity": "critical", "source": "rule", "title": "严重问题",
               "description": "必须修改", "anchor": "", "section": "document", "locationLabel": "全文"}] if critical else []
    return {"origin": "backend", "issues": issues, "issueDetails": {}, "reviewedAt": "2026-10-26T00:00:00Z",
            "summary": {"critical": int(critical), "warning": 0, "hint": 0},
            "formatCheck": {"status": "unavailable" if unavailable else "pass"},
            "gate": {"canApprove": not (critical or unavailable), "canExportFormal": False,
                     "reasons": ["格式机检未完成" if unavailable else "严重问题"] if (critical or unavailable) else []}}


def test_notice_metadata_and_tables_survive_reload(app_client):
    client, tokens, _ = app_client
    doc = notice(client, tokens["writer"], tables=[{"caption": "任务", "head": ["事项", "数量"], "rows": [["甲", "2"]]}])
    loaded = client.get(f"/api/v1/gov/documents/{doc['id']}", headers=tokens["writer"]).json()["data"]
    assert loaded["docNumber"]["text"] == "测办发〔2026〕8号"
    assert loaded["banji"]["printer"] == "测试办公室"
    assert any(b["kind"] == "heading1" for b in loaded["blocks"])
    assert next(b for b in loaded["blocks"] if b["kind"] == "table")["table"]["rows"] == [["甲", "2"]]


def test_check_uses_saved_input_and_edit_invalidates_report(app_client, monkeypatch):
    from app.gov import proofread
    client, tokens, _ = app_client
    captured = []
    monkeypatch.setattr(proofread, "run_review", lambda draft: captured.append(draft) or report())
    doc = notice(client, tokens["writer"])
    checked = action(client, tokens["writer"], doc, "check").json()["data"]
    assert checked["checkStatus"] == "completed" and checked["review"]["gate"]["canApprove"]
    assert captured[0].docNumber.text == doc["docNumber"]["text"]
    assert captured[0].blocks[1].segments[0].id in {s.get("id") for b in checked["blocks"] for s in b["segments"]}
    saved = client.put(f"/api/v1/gov/documents/{doc['id']}", headers=tokens["writer"],
                       json={"version": checked["version"], "body": "修改后的正文"}).json()["data"]
    assert saved["checkStatus"] == "not_run" and not saved.get("review")
    assert action(client, tokens["writer"], doc, "check").status_code == 409


@pytest.mark.parametrize("critical,unavailable", [(True, False), (False, True)])
def test_approve_rechecks_and_blocks_server_findings(app_client, monkeypatch, critical, unavailable):
    from app.gov import proofread
    client, tokens, _ = app_client
    calls = []
    monkeypatch.setattr(proofread, "run_review", lambda draft: calls.append(draft) or report(critical, unavailable))
    doc = notice(client, tokens["writer"])
    pending = action(client, tokens["writer"], doc, "submit").json()["data"]
    response = action(client, tokens["reviewer"], pending, "approve", opinion="核对通过")
    assert response.status_code == 409 and len(calls) == 1
    assert client.get(f"/api/v1/gov/documents/{doc['id']}", headers=tokens["writer"]).json()["data"]["status"] == "pending"


def test_approve_runs_fresh_review_even_after_previous_pass(app_client, monkeypatch):
    from app.gov import proofread
    client, tokens, _ = app_client
    reports = iter([report(), report(critical=True)])
    monkeypatch.setattr(proofread, "run_review", lambda draft: next(reports))
    doc = notice(client, tokens["writer"])
    checked = action(client, tokens["writer"], doc, "check").json()["data"]
    pending = action(client, tokens["writer"], checked, "submit").json()["data"]
    assert action(client, tokens["reviewer"], pending, "approve").status_code == 409


def test_concurrent_edit_during_review_cannot_store_stale_report(app_client, monkeypatch):
    from app.gov import proofread
    from app.gov.models import GovDocument
    client, tokens, factory = app_client
    doc = notice(client, tokens["writer"])
    def run(draft):
        with factory() as db:
            stored = db.get(GovDocument, doc["id"])
            stored.version += 1
            db.commit()
        return report()
    monkeypatch.setattr(proofread, "run_review", run)
    assert action(client, tokens["writer"], doc, "check").status_code == 409


def test_real_notice_review_has_both_layers_and_real_anchors(app_client):
    from app.services.gongwen.settings import load_settings
    if not (load_settings().kit_path / "bin/gongwen.js").exists():
        pytest.skip("gongwen-kit runtime required for actual two-layer integration")
    client, tokens, _ = app_client
    doc = notice(client, tokens["writer"], body="一、安排\n三、落实\n请认真落实,及时反馈。")
    result = action(client, tokens["writer"], doc, "check")
    assert result.status_code == 200, result.text
    checked = result.json()["data"]
    assert checked["review"]["formatCheck"]["status"] == "hit"
    assert {d["layer"] for d in checked["review"]["issueDetails"].values()} >= {"own", "gongwen-kit"}
    anchors = {b["id"] for b in checked["blocks"]} | {s["id"] for b in checked["blocks"] for s in b["segments"] if s.get("id")}
    anchors |= {doc["id"] + "-number", doc["id"] + "-banji", doc["id"] + "-title", doc["id"] + "-policies"}
    assert all(not i["anchor"] or i["anchor"] in anchors for i in checked["issues"])
    exported = client.post(f"/api/v1/gov/documents/{doc['id']}/export", headers=tokens["writer"], json={"kind": "internal_draft"})
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as z:
        xml = z.read("word/document.xml").decode()
        assert "测办发〔2026〕8号" in xml and "测试办公室" in xml
        assert any("内部草稿" in z.read(n).decode() for n in z.namelist() if n.startswith("word/header"))


@pytest.mark.parametrize("status,is_current", [("abolished", True), ("current", False)])
def test_policy_verification_is_resolved_server_side(app_client, monkeypatch, status, is_current):
    from app.gov import proofread
    client, tokens, _ = app_client
    monkeypatch.setattr(proofread, "run_review", lambda draft: report())
    monkeypatch.setattr(proofread, "policy_references", lambda payload: [{"id": "clause:1@0-2", "title": "测试政策", "clause": "第一条", "status": status, "isCurrentVersion": is_current, "sourceUrl": "https://www.gov.cn/test", "version": 1}])
    doc = notice(client, tokens["writer"])
    checked = action(client, tokens["writer"], doc, "check").json()["data"]
    assert checked["review"]["policyVerification"]["refs"][0]["status"] == status
    assert any(i["severity"] == "critical" and "政策" in i["title"] for i in checked["issues"])
