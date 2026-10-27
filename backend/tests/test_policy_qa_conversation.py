"""政策问答放开（依据分层、对话路线、按名匹配、多轮上下文）的行为测试。

对应计划：docs/superpowers/plans/2026-10-27-policy-qa-conversational.md
设计说明：docs/superpowers/specs/2026-10-27-policy-qa-conversational-design.md
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.policy import qa
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
