"""政策问答接入既有政策库（T1/T3）后的回归。

对应审查发现与待办：
- 发现 1 / 待办 1：普通账号不能修改、删除政策；核验与状态变更只有审核人能做。
- 发现 4 / 待办 3：导入默认待核实，只有人工核验为现行且在有效期内的政策才能作为依据。
- 发现 6 / 待办 7：混合 PDF 走 T3 逐页入口，扫描页 OCR 不完整时不入库。
- 待办 6：只有一套政策资料；问答引用 citation_id 与 /gov/citations/batch 同一格式。
原作者自检脚本（test_policy_pipeline.py）中的检索与问答行为一并迁移到 T1 数据上。
"""
from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.policy.fetcher import SafeFetcher
from app.services.policy.library import ImportRequest, PolicyLibraryService, get_policy_library
from app.services.policy.settings import settings_from_mapping
from app.services.policy.store import PolicyStore
from policy_support import FakeClock, block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")

SAMPLE = """示例市小微企业首次贷款贴息管理办法
第一条 为支持小微企业发展，规范首次贷款贴息管理，制定本办法。
第二条 本办法适用于本市行政区域内依法登记注册的小微企业。
第三条 申请贴息应当同时具备下列条件：在本市依法登记注册并正常经营满一年；近两年内无严重失信记录；贷款用于生产经营。
第四条 贷款合同应当签订于本办法施行之后，且为借款人首次取得的经营性贷款。
第五条 申请材料包括营业执照、贷款合同、还款凭证和银行出具的利息清单。
第六条 贴息按实际支付利息的百分之五十给予补贴，单户年度上限二十万元。
第七条 申请人应当在贷款发放后六个月内提出申请，逾期不再受理。
第八条 主管部门应当对贴息资金使用情况进行监督检查，发现虚报冒领的追回资金并依法处理。
第九条 本办法由市地方金融管理局负责解释。"""

DEPRECATED = """示例市政务数据共享管理办法
第一条 为规范政务数据共享，制定本办法。
第十二条 数据提供部门应当在收到共享申请后十五个工作日内予以答复。"""

CURRENT_REPLACEMENT = """示例市政务数据共享办法
第一条 为规范政务数据共享，提高行政效率，制定本办法。
第八条 数据提供部门应当在收到共享申请后十个工作日内予以答复；不予共享的，应当说明理由。"""

LOAN_Q = "小微企业首次贷款贴息的补贴比例是多少"
SHARE_Q = "政务数据共享申请多少个工作日内答复"

DRAFTER = SimpleNamespace(id=11, username="role-entry-drafter", is_admin=False, gov_role="drafter")
OTHER_DRAFTER = SimpleNamespace(id=12, username="drafter-b", is_admin=False, gov_role=None)
REVIEWER = SimpleNamespace(id=13, username="role-entry-reviewer", is_admin=False, gov_role="reviewer")


def _offline(*_a, **_k):
    raise RuntimeError("test: model deliberately unavailable")


@pytest.fixture()
def api(tmp_path):
    from app import models  # noqa: F401
    from app.database import Base, get_db
    from app.deps import get_current_user
    from app.policy import router as qa_router
    from app.routers import gov_policy

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    settings = settings_from_mapping({"enabled": True, "base_url": "https://example.invalid", "db_path": str(tmp_path / "p.db")})
    clock = FakeClock()

    def no_opener(*a, **k):
        raise AssertionError("tests must not fetch")

    fetcher = SafeFetcher(settings.fetch, resolver=lambda *a, **k: [], opener=no_opener, mode_provider=lambda: "cloud_allowed",
                          sleep=clock.sleep, clock=clock.monotonic)
    library = PolicyLibraryService(settings, PolicyStore(settings.db_path), fetcher)

    app = FastAPI()
    app.include_router(gov_policy.router, prefix="/api/v1")
    app.include_router(qa_router.router, prefix="/api/v1")

    def _db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_policy_library] = lambda: library
    holder = {"user": DRAFTER}
    app.dependency_overrides[get_current_user] = lambda: holder["user"]

    def login(user):
        holder["user"] = user

    stream_db = patch("app.policy.router.SessionLocal", sessions)
    stream_db.start()
    try:
        yield SimpleNamespace(client=TestClient(app), login=login, library=library, sessions=sessions)
    finally:
        stream_db.stop()


def add(library, text, title, *, verify=None, effective="2020-01-01", expire=None):
    result = library.import_policy(ImportRequest(filename=f"{title}.txt", data=text.encode("utf-8"), title=title))
    assert result["error"] is None, result
    pid = result["policy"]["id"]
    if verify:
        fields = {"effective_date": effective, **({"expire_date": expire} if expire else {})}
        assert library.verify(pid, status=verify, note="人工核验", fields=fields, verifier="tester")["error"] is None
    return pid


def ask(api, question, **extra):
    with patch("app.services.llm_chat.chat", _offline):
        resp = api.client.post("/api/v1/policy/qa", json={"question": question, **extra})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    return body["data"]


# ── 待办 3：未核验不能作为现行依据 ────────────────────────────────────────
DENSE_Q = "贴息和补贴怎么给"   # ① 逐条实词覆盖新规则：问法要实词紧凑（见 test_policy_qa_conversation）

def test_import_is_unverified_and_strict_scope_excludes_it(api):
    pid = add(api.library, SAMPLE, "未经核验贷款政策")
    assert api.library.store.get(pid).verified_status == "unverified"
    # 严格模式（仅已核验现行政策）仍然拒答
    assert ask(api, DENSE_Q, scope="current")["status"] != "answered"
    # 默认范围放开后：待核实政策可以作答，但带未核验前提
    res = ask(api, DENSE_Q)
    assert res["status"] == "answered" and res["basis"] == "unverified"
    only = ask(api, DENSE_Q, scope="policy", policy_ids=[pid])           # 审查复现路径：指定该政策
    assert only["status"] == "answered" and only["basis"] == "unverified"
    assert only["citations"] and only["basis_notice"]


def test_verified_current_policy_answers_with_t1_citation_ids(api):
    pid = add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    res = ask(api, DENSE_Q)
    assert res["status"] == "answered" and res["meta"]["generated_by"].startswith("extractive")
    first = res["citations"][0]
    assert first["clause_no"] == "第六条" and "[1]" in res["conclusion"] and first["excerpt"]["hl"]
    assert first["policy_id"] == pid and first["verified_status"] == "current"
    # 问答引用可直接作为文稿 citationIds：与 /gov/citations/batch 同一编号
    batch = api.client.post("/api/v1/gov/citations/batch", json={"ids": [first["citation_id"]]}).json()["data"]
    assert batch["missing"] == [] and batch["citations"][0]["clause"] == "第六条"


@pytest.mark.parametrize("effective,expire", [("2020-01-01", "2021-01-01"), ("2099-01-01", None)])
def test_verified_but_expired_or_not_yet_effective_is_not_a_basis(api, effective, expire):
    add(api.library, SAMPLE, "日期不在有效期内的办法", verify="current", effective=effective, expire=expire)
    assert ask(api, LOAN_Q)["status"] == "no_basis"


# ── 原作者自检：检索与问答行为保留 ───────────────────────────────────────
def test_retrieval_ranks_the_answering_clause_first(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    items = api.client.post("/api/v1/policy/search", json={"query": LOAN_Q}).json()["data"]["items"]
    assert items and items[0]["clause_no"] == "第六条" and items[0]["score"] >= 0.6
    assert items[0]["citation_id"].startswith("clause:")
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True)


def test_unrelated_question_gets_chat_reply_without_citations(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    res = ask(api, "外地户籍人员申请人才公寓补贴需要什么材料")   # ask() 下模型不可用 → 走兜底话术
    assert res["status"] == "chat" and res["citations"] == [] and res["conclusion"] == ""
    assert res["reply"]


def test_abolished_policy_is_excluded_and_listed_as_history(api):
    # 与原作者自检相同：三份政策同库（BM25 的词权重依赖语料规模，两条小政策时分数偏低）
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    add(api.library, CURRENT_REPLACEMENT, "示例市政务数据共享办法", verify="current")
    old = add(api.library, DEPRECATED, "示例市政务数据共享管理办法", verify="abolished")
    res = ask(api, SHARE_Q, scope="all")
    assert res["status"] == "answered"
    assert "第八条" in [c["clause_no"] for c in res["citations"]]
    assert "示例市政务数据共享管理办法" not in {c["policy_title"] for c in res["citations"]}
    assert res["meta"]["excluded_deprecated"] >= 1 and res["deprecated_refs"]
    only_old = ask(api, SHARE_Q, scope="policy", policy_ids=[old])
    assert only_old["status"] == "no_basis" and "已废止" in only_old["reason"]


def test_stream_uses_the_same_rules(api):
    add(api.library, SAMPLE, "未经核验贷款政策")
    with patch("app.services.llm_chat.stream", _offline):
        text = api.client.post("/api/v1/policy/qa/stream", json={"question": DENSE_Q}).text
    assert '"basis": "unverified"' in text and "[DONE]" in text


# ── 待办 1：写入只有审核人能做；不存在另一套改删接口 ──────────────────────
def test_policy_writes_are_reviewer_only_and_the_parallel_endpoints_are_gone(api):
    pid = add(api.library, SAMPLE, "他人导入的政策")
    api.login(DRAFTER)
    form = {"title": "x"}
    files = {"file": ("x.txt", SAMPLE.encode("utf-8"), "text/plain")}
    assert api.client.post("/api/v1/gov/policies/import", data=form, files=files).status_code == 403
    assert api.client.post(f"/api/v1/gov/policies/{pid}/verify", json={"status": "current"}).status_code == 403
    for method in ("patch", "delete"):
        resp = getattr(api.client, method)(f"/api/v1/policy/documents/{pid}", **({"json": {"status": "现行有效"}} if method == "patch" else {}))
        assert resp.status_code in (404, 405)
    assert api.client.post("/api/v1/policy/documents/text", json={"text": SAMPLE}).status_code in (404, 405)
    policy = api.library.store.get(pid)
    assert policy is not None and policy.verified_status == "unverified"
    api.login(REVIEWER)
    assert api.client.post(f"/api/v1/gov/policies/{pid}/verify", json={"status": "current"}).json()["code"] == 0
    assert api.library.store.get(pid).verified_status == "current"


def test_qa_logs_are_private_except_for_reviewers(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    api.login(DRAFTER)
    ask(api, LOAN_Q)
    api.login(OTHER_DRAFTER)
    assert api.client.get("/api/v1/policy/qa/logs").json()["data"]["items"] == []
    api.login(DRAFTER)
    assert len(api.client.get("/api/v1/policy/qa/logs").json()["data"]["items"]) == 1
    api.login(REVIEWER)
    assert len(api.client.get("/api/v1/policy/qa/logs").json()["data"]["items"]) == 1


# ── 待办 6 / 7：只有一套政策资料，PDF 只走 T3 逐页入口 ───────────────────
def test_policy_qa_has_no_storage_or_parser_of_its_own():
    from app.database import Base
    from app.policy import router as qa_router

    assert importlib.util.find_spec("app.policy.parser") is None
    assert "policy_clauses" not in Base.metadata.tables
    paths = {(m, r.path) for r in qa_router.router.routes for m in getattr(r, "methods", ())}
    assert not any(path.startswith("/policy/documents") for _, path in paths)


PDF = b"%PDF-1.7\nunit-test-input"


def _mixed(page2: str):
    return {"success": True, "error": None, "page_count": 2, "markdown": "", "warnings": [], "metadata": {},
            "pages": [{"page": 1, "text": "第一条 文字页规定，申请人应当提交营业执照。", "blocks": []},
                      {"page": 2, "text": page2, "blocks": []}]}


def _import_pdf(api):
    api.login(REVIEWER)
    return api.client.post("/api/v1/gov/policies/import", data={"title": "混合版式政策"},
                           files={"file": ("mixed.pdf", PDF, "application/pdf")}).json()


def test_mixed_pdf_with_incomplete_ocr_is_rejected_without_writing(api, monkeypatch):
    from app import config
    from app.services.policy import pdf

    monkeypatch.setattr(config, "_config", {"policy_pdf": {"engine": "opendataloader"}})
    monkeypatch.setattr(pdf, "parse_pdf", lambda *a, **k: _mixed(""))
    monkeypatch.setattr(pdf, "legacy_extract", lambda *a: ("## Page 1\n第一条 文字。", {"page_count": 2, "image_pages": [2], "visual_pages": []}, []))
    body = _import_pdf(api)
    assert body["code"] != 0 and "未写入" in body["message"]
    assert api.library.store.count(include_history=True) == 0


def test_mixed_pdf_ocr_page_is_kept_with_its_page_number(api, monkeypatch):
    from app import config
    from app.services.policy import pdf

    monkeypatch.setattr(config, "_config", {"policy_pdf": {"engine": "opendataloader"}})
    monkeypatch.setattr(pdf, "parse_pdf", lambda *a, **k: _mixed(""))
    monkeypatch.setattr(pdf, "legacy_extract", lambda *a: (
        "## Page 1\n第一条 文字页规定，申请人应当提交营业执照。\n\n## Page 2\n第二条 扫描页规定，补贴资金按季度拨付。",
        {"source": "poppler_pdf_hybrid", "page_count": 2, "image_pages": [2], "visual_pages": [2]}, []))
    body = _import_pdf(api)
    assert body["code"] == 0, body
    pid = body["data"]["policy"]["id"]
    clauses = api.library.store.clauses_for(pid)
    assert [c.page_number for c in clauses] == [1, 2] and "按季度拨付" in clauses[1].content
    api.library.verify(pid, status="current", note="", fields={"effective_date": "2020-01-01"}, verifier="t")
    res = ask(api, "补贴资金如何拨付")
    assert res["status"] == "answered" and res["citations"][0]["page"] == 2


@pytest.mark.parametrize("streaming", [False, True])
def test_model_refusal_remains_no_basis(api, streaming):
    import json
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    question = "申请贴息要具备什么条件"
    refusal = "现有条款未作规定"
    if streaming:
        with patch("app.services.llm_chat.stream", return_value=iter([refusal])):
            text = api.client.post("/api/v1/policy/qa/stream", json={"question": question}).text
        events = [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:") and line[5:].strip() != "[DONE]"]
        result = next(event["data"] for event in events if event.get("type") == "final")
    else:
        with patch("app.services.llm_chat.chat", return_value=refusal):
            result = api.client.post("/api/v1/policy/qa", json={"question": question}).json()["data"]
    assert result["status"] == "no_basis"
    assert result["sufficient"] is False and result["conclusion"] == "" and result["citations"] == []


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("markers", ["[0]", "[99]", "[1][99]"])
def test_invalid_model_citations_do_not_receive_an_unrelated_source(api, streaming, markers):
    import json
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    question = "申请贴息要具备什么条件"
    unsupported = "所有企业无需审核即可获得贴息" + markers
    if streaming:
        with patch("app.services.llm_chat.stream", return_value=iter([unsupported])):
            text = api.client.post("/api/v1/policy/qa/stream", json={"question": question}).text
        events = [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:") and line[5:].strip() != "[DONE]"]
        result = next(event["data"] for event in events if event.get("type") == "final")
    else:
        with patch("app.services.llm_chat.chat", return_value=unsupported):
            result = api.client.post("/api/v1/policy/qa", json={"question": question}).json()["data"]
    assert "无需审核" not in result["conclusion"]
    assert "[99]" not in result["conclusion"] and "[0]" not in result["conclusion"]
    assert result["meta"]["generated_by"].startswith("extractive")
