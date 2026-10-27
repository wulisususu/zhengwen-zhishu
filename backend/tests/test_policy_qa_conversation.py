"""政策问答放开（依据分层、对话路线、按名匹配、多轮上下文）的行为测试。

对应计划：docs/superpowers/plans/2026-10-27-policy-qa-conversational.md
设计说明：docs/superpowers/specs/2026-10-27-policy-qa-conversational-design.md
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.policy import conversation, qa
from app.policy.corpus import PolicyView
from app.policy.titles import STRONG, match_titles
from policy_support import block_network  # noqa: F401  # pytest 经模块命名空间解析该 fixture
from test_policy_qa_t1 import (  # noqa: F401
    CURRENT_REPLACEMENT,
    LOAN_Q,
    SAMPLE,
    SHARE_Q,
    add,
    api,
    ask,
)

pytestmark = pytest.mark.usefixtures("block_network")


# ---------------------------------------------------------------- Task 1：依据分层

def test_unverified_policy_answers_with_fixed_notice(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法")      # 不核验
    res = ask(api, LOAN_Q)                                               # 默认 scope = all
    assert res["status"] == "answered" and res["basis"] == "unverified"
    assert res["basis_notice"] == qa.UNVERIFIED_NOTICE
    assert res["citations"][0]["status"] == "待核实" and "[1]" in res["conclusion"]
    assert res["sufficiency"] == "partial"


def test_verified_clause_wins_over_unverified(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    add(api.library, SAMPLE.replace("示例市", "另一市"), "另一市小微企业首次贷款贴息管理办法")
    res = ask(api, LOAN_Q)
    assert res["basis"] == "verified" and res["basis_notice"] == ""
    assert {c["status"] for c in res["citations"]} == {"现行有效"}
    # 未核验的那份进「待人工确认」，不进引用
    assert any("另一市小微企业首次贷款贴息管理办法" in m for m in res["manual_confirm"])


def test_strict_scope_still_excludes_unverified(api):
    add(api.library, SAMPLE, "未核验贴息办法")
    res = ask(api, LOAN_Q, scope="current")
    assert res["status"] != "answered"


@pytest.mark.parametrize("effective,expire", [("2020-01-01", "2021-01-01"), ("2099-01-01", None)])
def test_not_in_force_reason_does_not_blame_the_threshold(api, effective, expire):
    add(api.library, SAMPLE, "日期不在有效期内的办法", verify="current", effective=effective, expire=expire)
    res = ask(api, LOAN_Q)
    assert res["status"] == "no_basis" and res["reason_code"] == "not_in_force"
    assert "未达到可信阈值" not in res["reason"]


def test_stream_evidence_event_carries_the_notice(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法")      # 不核验
    with patch("app.services.llm_chat.stream", return_value=iter(["贴息比例为百分之五十[1]。"])):
        text = api.client.post("/api/v1/policy/qa/stream", json={"question": LOAN_Q}).text
    events = [json.loads(line[5:]) for line in text.splitlines()
              if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]")]
    evidence = next(e for e in events if e.get("type") == "evidence")
    final = next(e for e in events if e.get("type") == "final")["data"]
    assert evidence["basis"] == "unverified" and evidence["basis_notice"] == qa.UNVERIFIED_NOTICE
    assert final["basis"] == "unverified"


# ---------------------------------------------------------------- Task 2：对话路线

def test_greeting_gets_a_friendly_reply_not_a_refusal(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    with patch("app.services.llm_chat.chat", return_value="您好！我可以帮您查政策条款……"):
        res = api.client.post("/api/v1/policy/qa", json={"question": "你好"}).json()["data"]
    assert res["status"] == "chat" and res["reply"].startswith("您好")
    assert res["citations"] == [] and res["meta"]["generated_by"] == "chat_llm"


@pytest.mark.parametrize("question,kind", [
    ("你好", "greeting"),
    ("外地户籍人员申请人才公寓补贴需要什么材料", "policy"),
    ("电脑命令行怎么查看IP地址", "other"),
])
def test_model_unavailable_uses_rotating_fallback(api, question, kind):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    res = ask(api, question)                       # ask() 已把模型打桩为不可用
    assert res["status"] == "chat" and res["meta"]["kind"] == kind
    assert res["meta"]["generated_by"] == "chat_fallback" and res["reply"]
    assert "已检索" not in res["reply"]


def test_fallback_wording_varies_between_questions():
    ctx = conversation.ChatContext(kind="other", stats={"total": 1, "verified": 1, "unverified": 0},
                                   known_titles=set())
    replies = {conversation.fallback_reply(ctx, q)
               for q in ["电脑怎么关机", "打印机连不上怎么办", "WPS怎么改页边距", "Excel公式怎么写"]}
    assert len(replies) >= 2


def test_chat_reply_naming_unknown_policy_falls_back():
    known = {"示例市小微企业首次贷款贴息管理办法"}
    assert conversation.guard_reply("根据《某市人才安居办法》，可以申请。", known) is None
    assert conversation.guard_reply("可以参考《示例市小微企业首次贷款贴息管理办法》。", known)


def test_chat_reply_with_code_block_falls_back():
    assert conversation.guard_reply("建议咨询信息部门。\n```\nipconfig\n```", set()) is None


def test_chat_reply_strips_citation_markers_and_doc_numbers_fall_back():
    assert "[1]" not in conversation.guard_reply("您好[1]，请问需要查哪方面的政策？", set())
    assert conversation.guard_reply("见示政发〔2024〕3号。", set()) is None


def test_chat_stream_emits_mode_then_replace_when_guarded(api):
    with patch("app.services.llm_chat.stream", return_value=iter(["根据《不存在办法》", "可以申请。"])):
        text = api.client.post("/api/v1/policy/qa/stream", json={"question": "有没有人才公寓补贴"}).text
    events = [json.loads(line[5:]) for line in text.splitlines()
              if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]")]
    kinds = [e.get("type") for e in events]
    # stage（检索提示）在 mode 之前发出，属于既有行为
    assert "mode" in kinds and next(e for e in events if e["type"] == "mode")["mode"] == "chat"
    assert "delta" in kinds and "replace" in kinds and "final" in kinds
    final = next(e for e in events if e["type"] == "final")["data"]
    replaced = next(e for e in events if e["type"] == "replace")["text"]
    assert final["reply"] == replaced and "不存在办法" not in final["reply"]
    assert final["meta"]["generated_by"] == "chat_fallback"


def test_chat_turn_is_logged_with_chat_status(api):
    with patch("app.services.llm_chat.chat", return_value="您好！需要查哪方面的政策？"):
        api.client.post("/api/v1/policy/qa", json={"question": "你好"})
    items = api.client.get("/api/v1/policy/qa/logs").json()["data"]["items"]
    assert items and items[0]["status"] == "chat"
    assert items[0]["answer"] == "您好！需要查哪方面的政策？"


# ---------------------------------------------------------------- Task 3：按政策名匹配

def view(pid, title, status="现行有效"):
    return PolicyView(id=pid, title=title, doc_no="", issuer="", status=status,
                      verified_status="current" if status == "现行有效" else "unverified",
                      status_note="", publish_date="", effective_date="", expire_date="",
                      source_url="", version=1, is_current_version=True)


def test_match_titles_scores_bookmarked_and_loose_names():
    p = [view(1, "示例市小微企业首次贷款贴息管理办法"), view(2, "示例市政务数据共享办法")]
    assert match_titles("帮我看看《示例市小微企业首次贷款贴息管理办法》", p)[0].policy.id == 1
    assert match_titles("能帮我看看小微企业首次贷款贴息办法吗", p)[0].score >= STRONG
    assert match_titles("你好", p) == []


def test_plain_question_is_not_treated_as_a_title_lookup():
    p = [view(1, "示例市小微企业首次贷款贴息管理办法")]
    assert match_titles("贷款贴息比例是多少", p) == []


def test_named_policy_gets_an_overview_with_citations(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    add(api.library, CURRENT_REPLACEMENT, "示例市政务数据共享办法", verify="current")
    res = ask(api, "能帮我看看小微企业首次贷款贴息办法吗")
    assert res["status"] == "answered" and res["meta"]["mode"] == "overview"
    assert {c["policy_title"] for c in res["citations"]} == {"示例市小微企业首次贷款贴息管理办法"}
    assert res["meta"]["generated_by"] == "extractive_overview"      # ask() 下模型不可用


def test_named_policy_with_specific_question_answers_inside_that_policy(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    res = ask(api, "《示例市小微企业首次贷款贴息管理办法》的补贴比例是多少")
    assert res["meta"]["mode"] == "answer" and "第六条" in [c["clause_no"] for c in res["citations"]]


def test_ambiguous_title_asks_back_with_suggestions(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法")
    add(api.library, SAMPLE.replace("管理办法", "管理办法实施细则"), "示例市小微企业首次贷款贴息管理办法实施细则")
    res = ask(api, "帮我看看小微企业贴息的办法")
    assert res["status"] == "chat"
    assert {s["title"] for s in res["suggestions"]} == {
        "示例市小微企业首次贷款贴息管理办法", "示例市小微企业首次贷款贴息管理办法实施细则"}


def test_unverified_overview_carries_the_notice(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法")
    res = ask(api, "帮我看看示例市小微企业首次贷款贴息管理办法")
    assert res["meta"]["mode"] == "overview" and res["basis_notice"] == qa.UNVERIFIED_NOTICE
