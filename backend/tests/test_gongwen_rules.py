"""Own review rules, spec conversion, kit-report parsing and issue mapping. No Node needed."""
import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.gongwen import catalog, rules
from app.services.gongwen.checker import KitHit, parse_report
from app.services.gongwen.converter import COMPONENT_TYPES, build_spec
from app.services.gongwen.review import (REVIEW_ISSUE_KEYS, dedupe_kit_hits, evaluate_gate,
                                         issue_from_finding, issue_from_kit_hit)
from app.services.gongwen.runner import GongwenToolError
from app.services.gongwen.schema import NoticeDraft

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gongwen" / "notices"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def draft(data: dict) -> NoticeDraft:
    return NoticeDraft.model_validate(data)


def codes(findings) -> list[str]:
    return sorted(f.code for f in findings)


def set_text(data: dict, block_id: str, text: str) -> dict:
    data = copy.deepcopy(data)
    block = next(b for b in data["blocks"] if b["id"] == block_id)
    block["segments"] = [{"kind": "text", "text": text}]
    return data


# ── schema ────────────────────────────────────────────────────────────────
def test_standard_notice_validates_and_ignores_frontend_extras():
    data = load("standard_notice")
    data.update(origin="demo", status="draft", issues=[], history=[])
    assert draft(data).title.endswith("通知")


@pytest.mark.parametrize("patch", [
    {"title": "标题\x00"},
    {"docType": "report"},
    {"blocks": [{"id": "a b", "kind": "paragraph", "segments": []}]},
    {"blocks": [{"id": "t", "kind": "table", "table": {"head": ["a", "b"], "rows": [["1"]]}}]},
    {"blocks": [{"id": "dup", "kind": "paragraph", "segments": []}, {"id": "dup", "kind": "paragraph", "segments": []}]},
    {"titleLines": ["不一致的", "标题"]},
])
def test_invalid_drafts_are_rejected(patch):
    data = load("standard_notice")
    data.update(patch)
    with pytest.raises(ValidationError):
        draft(data)


# ── 1 要素 ───────────────────────────────────────────────────────────────
def test_standard_notice_has_no_element_numbering_or_count_findings():
    d = draft(load("standard_notice"))
    assert rules.check_elements(d) + rules.check_numbering(d) + rules.check_counts(d) == []


def test_missing_elements_are_reported_with_required_fields_and_real_anchors():
    data = load("standard_notice")
    data["fields"] = {"recipient": "", "issuer": "", "undertaker": ""}
    data["title"], data["titleLines"], data["docNumber"]["text"] = "", None, ""
    data["signDate"], data["banji"] = "", None
    findings = rules.check_elements(draft(data))
    by_code = {f.code: f for f in findings}
    assert set(by_code) == {"ELEM_TITLE", "ELEM_ISSUER", "ELEM_RECIPIENT", "ELEM_UNDERTAKER",
                            "ELEM_DOCNO", "ELEM_SIGN_DATE", "ELEM_BANJI"}
    assert (by_code["ELEM_ISSUER"].anchor, by_code["ELEM_RECIPIENT"].anchor) == ("seg-issuer", "seg-recipient")
    assert by_code["ELEM_DOCNO"].anchor == "seg-docno"
    assert by_code["ELEM_SIGN_DATE"].anchor == "blk-sign"
    assert by_code["ELEM_BANJI"].anchor == "" and by_code["ELEM_BANJI"].precision == "none"
    issues = {f.code: issue_from_finding(f)[0] for f in findings}
    assert issues["ELEM_ISSUER"]["requiredField"] == "issuer"
    assert issues["ELEM_RECIPIENT"]["requiredField"] == "recipient"
    assert issues["ELEM_UNDERTAKER"]["requiredField"] == "undertaker"
    assert "requiredField" not in issues["ELEM_DOCNO"]


def test_undertaker_only_required_when_referenced():
    data = load("standard_notice")
    data["fields"]["undertaker"] = ""
    data = set_text(data, "blk-s3-p", "各单位于 2026年10月30日前报送名单。")
    assert "ELEM_UNDERTAKER" not in codes(rules.check_elements(draft(data)))


@pytest.mark.parametrize("value,code", [
    ("2026-10-26", "SIGN_DATE_FORMAT"),
    ("2026年10月", "SIGN_DATE_FORMAT"),
    ("2026.10.26", "SIGN_DATE_FORMAT"),
    ("2026年2月30日", "SIGN_DATE_INVALID"),
    ("2026年13月1日", "SIGN_DATE_INVALID"),
])
def test_bad_sign_dates(value, code):
    data = load("standard_notice")
    data["signDate"] = value
    assert code in codes(rules.check_elements(draft(data)))


@pytest.mark.parametrize("value", ["2026年10月26日", "2026年1月5日", "二〇二六年十月二十六日", "2026年10月06日"])
def test_recognisable_sign_dates_are_left_to_gongwen_kit(value):
    # 写法问题（虚位、汉字数字）由 gongwen-kit 报，本层不重复
    data = load("standard_notice")
    data["signDate"] = value
    assert not [c for c in codes(rules.check_elements(draft(data))) if c.startswith("SIGN_DATE")]


def test_title_without_doc_type_is_a_warning():
    data = load("standard_notice")
    data["title"], data["titleLines"] = "示例单位办公室关于开展公文格式规范培训工作的安排", None
    assert "TITLE_DOC_TYPE" in codes(rules.check_elements(draft(data)))


# ── 2 层次序号 ────────────────────────────────────────────────────────────
def test_heading_gap_is_reported_once_at_the_gap():
    data = set_text(load("standard_notice"), "blk-s3", "四、有关要求")
    findings = rules.check_numbering(draft(data))
    assert [(f.code, f.anchor, f.extra) for f in findings] == [
        ("NUMBERING_GAP", "blk-s3", {"expected": 3, "actual": 4})]
    assert "应为「三、」" in findings[0].description


def test_second_level_gap_and_level_mismatch():
    data = set_text(load("standard_notice"), "blk-s1-3", "（四）组织常见格式差错案例研讨")
    assert [(f.code, f.anchor) for f in rules.check_numbering(draft(data))] == [("NUMBERING_GAP", "blk-s1-3")]
    data = set_text(load("standard_notice"), "blk-s2", "（二）参训人员")
    assert codes(rules.check_numbering(draft(data))) == ["NUMBERING_LEVEL"]


def test_paragraph_markers_and_inline_markers():
    data = load("standard_notice")
    data["blocks"].insert(9, {"id": "p-a", "kind": "paragraph", "section": "s2", "segments": [{"kind": "text", "text": "1. 综合处负责汇总。"}]})
    data["blocks"].insert(10, {"id": "p-b", "kind": "paragraph", "section": "s2", "segments": [{"kind": "text", "text": "3. 业务处负责通知。"}]})
    data["blocks"].insert(11, {"id": "p-c", "kind": "paragraph", "section": "s2", "segments": [{"kind": "text", "text": "要求如下：一是按时报送，二是如实填写，四是注意保密。"}]})
    found = [(f.code, f.anchor) for f in rules.check_numbering(draft(data))]
    assert found == [("NUMBERING_GAP", "p-b"), ("NUMBERING_GAP", "p-c")]


def test_headings_without_typed_numbers_are_fine():
    data = load("standard_notice")
    for b in data["blocks"]:
        if b["kind"].startswith("heading"):
            text = b["segments"][0]["text"]
            b["segments"][0]["text"] = text[text.index("、") + 1:] if "、" in text[:4] else text[3:]
    assert rules.check_numbering(draft(data)) == []


# ── 3 数量 ────────────────────────────────────────────────────────────────
def test_count_mismatch_against_following_headings():
    data = set_text(load("standard_notice"), "blk-s1-p", "本次培训共 5 项任务：")
    findings = rules.check_counts(draft(data))
    assert [(f.code, f.anchor, f.extra) for f in findings] == [
        ("COUNT_MISMATCH", "blk-s1-p", {"stated": 5, "listed": 3})]


@pytest.mark.parametrize("text,code", [
    ("本次培训包括以下五项任务：一是讲版心，二是讲层次，三是讲日期。", "COUNT_MISMATCH"),
    ("共 4 项任务：讲解版心；讲解层次；组织研讨。", "COUNT_MISMATCH_INLINE"),
    ("共两项任务：（一）讲版心（二）讲层次（三）研讨。", "COUNT_MISMATCH"),
])
def test_inline_count_mismatch(text, code):
    data = set_text(load("standard_notice"), "blk-intro", text)
    assert codes(rules.check_counts(draft(data))) == [code]


@pytest.mark.parametrize("text", [
    "本次培训共 3 项任务已全部完成。",      # 不是列举引导句
    "共 3 项任务：讲解版心；讲解层次；组织研讨。",
    "以下三点：一是讲版心，二是讲层次，三是讲日期。",
])
def test_consistent_or_non_enumerating_counts_are_not_reported(text):
    data = set_text(load("standard_notice"), "blk-intro", text)
    assert rules.check_counts(draft(data)) == []


# ── 4 政策引用 ────────────────────────────────────────────────────────────
def test_policy_refs_existence_only_and_never_claim_validity():
    data = load("standard_notice")
    data["policyRefs"].append({"id": "ref-2", "title": "未引用的办法", "status": "current"})
    data = set_text(data, "blk-s2-p", "依据《另一个规定》第三条，名额分配如下：")
    findings, verification = rules.check_policy_refs(draft(data))
    assert codes(findings) == ["POLICY_REF_UNCITED", "POLICY_REF_UNLINKED", "POLICY_REF_UNVERIFIED"]
    assert verification["status"] == "not_available"
    assert all(ref["verified"] is False for ref in verification["refs"])
    # client says "current"; the backend must not repeat that as a verified result
    assert "current" not in json.dumps(verification) and "现行有效" not in json.dumps(verification)


def test_no_policy_findings_without_refs_or_citations():
    data = load("standard_notice")
    data["policyRefs"] = []
    data = set_text(data, "blk-intro", "为规范公文格式，现就有关事项通知如下。")
    assert rules.check_policy_refs(draft(data))[0] == []


# ── converter ─────────────────────────────────────────────────────────────
def test_spec_uses_whitelisted_components_and_strips_typed_numbers():
    spec, index = build_spec(draft(load("standard_notice")))
    types = [c["type"] for c in spec["components"]]
    assert set(types) <= set(COMPONENT_TYPES)
    assert types[:3] == ["letterhead", "title", "zhusong"] and types[-3:] == ["luokuan", "fuzhu", "banji"]
    heads = [c["text"] for c in spec["components"] if c["type"] in ("h1", "h2")]
    assert heads[:2] == ["培训任务", "讲解公文版心与行字数要求"]
    table = next(c for c in spec["components"] if c["type"] == "table")
    assert sum(table["widths"]) <= 8844 and len(table["widths"]) == 2
    assert next(c for c in spec["components"] if c["type"] == "fujian")["items"] == ["参训人员名单"]
    assert {e.anchor for e in index} >= {"seg-docno", "seg-recipient", "seg-cite", "blk-s1", "blk-sign"}
    assert json.loads(json.dumps(spec)) == spec   # plain data only


def test_spec_uses_visible_placeholders_for_missing_fields():
    data = load("standard_notice")
    data["fields"]["issuer"] = ""
    data["signDate"] = ""
    spec, _ = build_spec(draft(data))
    assert spec["components"][0]["type"] == "title"   # no letterhead without an issuer
    luokuan = next(c for c in spec["components"] if c["type"] == "luokuan")
    assert luokuan == {"type": "luokuan", "unit": "【待补充：发文机关】", "date": "【待补充：成文日期】"}


# ── kit report parsing ────────────────────────────────────────────────────
def report(status="pass", hits=(), blocking=None, sha="abc", **extra):
    hits = list(hits)
    return json.dumps({"file": "x.docx", "status": status,
                       "blocking": sum(h["blocking"] for h in hits) if blocking is None else blocking,
                       "checks": [{"check": "体例", "file": "x.docx", "hits": hits}],
                       "toolVersion": "0.4.4", "generatedAt": "t", "sha256": sha, **extra})


HINT = {"rule": "合计不符", "detail": "第 1 表合计 26 ≠ 25", "blocking": False, "anchors": [{"text": "26", "table": 0}]}
BLOCK = {"rule": "发文字号", "detail": "年份用六角括号〔〕：[2025]", "blocking": True, "anchors": ["[2025]"]}


def test_hint_only_report_passes_with_exit_zero_but_keeps_the_hint():
    rep, hits = parse_report(report("pass", [HINT]), 0, "abc")
    assert rep["status"] == "pass" and [(h.rule, h.blocking) for h in hits] == [("合计不符", False)]


@pytest.mark.parametrize("stdout,exit_code,code", [
    ("not json", 0, catalog.TOOL_BAD_OUTPUT),
    (json.dumps({"status": "maybe"}), 0, catalog.TOOL_BAD_OUTPUT),
    (report("fault", message="读不进"), 2, catalog.TOOL_FAULT),
    (report("pass"), 2, catalog.TOOL_FAULT),
    (report("pass"), 1, catalog.TOOL_INCONSISTENT),
    (report("hit", [BLOCK]), 0, catalog.TOOL_INCONSISTENT),
    (report("hit", [BLOCK], blocking=0), 1, catalog.TOOL_INCONSISTENT),
    (report("pass", [BLOCK]), 0, catalog.TOOL_INCONSISTENT),
    (report("pass", sha="other"), 0, catalog.TOOL_INCONSISTENT),
    (report("pass", [{"rule": "x", "detail": "y", "blocking": "yes"}], blocking=0), 0, catalog.TOOL_BAD_OUTPUT),
])
def test_bad_or_inconsistent_reports_are_tool_errors_never_pass(stdout, exit_code, code):
    with pytest.raises(GongwenToolError) as exc:
        parse_report(stdout, exit_code, "abc")
    assert exc.value.code == code


# ── issue mapping ─────────────────────────────────────────────────────────
def test_kit_hits_map_to_review_issues_with_anchor_precision():
    _, index = build_spec(draft(load("standard_notice")))
    issue, detail = issue_from_kit_hit(KitHit("体例", "发文字号", "说明", True, ["示办发〔2026〕8号"]), [], index)
    assert set(issue) <= set(REVIEW_ISSUE_KEYS) and "suggestion" not in issue
    assert (issue["severity"], issue["source"], issue["anchor"], issue["section"]) == ("critical", "rule", "seg-docno", "head")
    assert detail["code"] == "GWK_DOCNO" and detail["anchorPrecision"] == "segment"

    hint, hint_detail = issue_from_kit_hit(KitHit("数字自洽", **HINT), [], index)
    assert hint["severity"] == "hint" and hint_detail["blocking"] is False

    layout, layout_detail = issue_from_kit_hit(KitHit("体例", "公文版式", "版心不合", True, []), [], index)
    assert (layout["anchor"], layout["locationLabel"], layout_detail["anchorPrecision"]) == ("", "全文", "none")

    unknown, unknown_detail = issue_from_kit_hit(KitHit("体例", "新规则", "说明", False, []), [], index)
    assert unknown_detail["code"] == catalog.KIT_UNMAPPED and unknown["title"] == "新规则"


def test_unique_fragment_anchors_to_its_block():
    _, index = build_spec(draft(load("standard_notice")))
    issue, detail = issue_from_kit_hit(KitHit("体例", "月日编虚位", "x", True, ["2026年10月26日"]), [], index)
    assert (issue["anchor"], issue["locationLabel"], detail["anchorPrecision"]) == ("blk-sign", "落款", "block")


def test_ambiguous_fragment_is_marked_and_lists_candidates():
    _, index = build_spec(draft(load("standard_notice")))
    issue, detail = issue_from_kit_hit(KitHit("文风", "异形词", "x", True, ["讲解"]), [], index)
    assert detail["anchorPrecision"] == "text_snippet_ambiguous"
    assert detail["candidates"] == ["blk-s1-1", "blk-s1-2"] and issue["anchor"] == "blk-s1-1"


def test_dedupe_drops_exact_duplicates_and_the_measured_paren_overlap():
    paren = KitHit("体例", "半角括号", "科(，中文用全角（）", True, ["科("])
    punct = KitHit("文风", "中文里的半角标点", "中文里的半角标点 1 处（科(）。一律改全角（GB/T 15834）。", True, [])
    other = KitHit("文风", "中文里的半角标点", "中文里的半角标点 1 处（求,）。一律改全角（GB/T 15834）。", True, [])
    kept = dedupe_kit_hits([paren, paren, punct, other])
    assert [(h.rule, merged) for h, merged in kept] == [("半角括号", ["中文里的半角标点"]), ("中文里的半角标点", [])]
    assert kept[1][0] is other   # a comma is not covered by 半角括号, so it stays


def test_every_own_rule_has_a_valid_severity_and_issue_shape():
    for rule in catalog.OWN_RULES.values():
        assert rule.severity in catalog.SEVERITIES
        issue, _ = issue_from_finding(rules.Finding(rule.code, "说明"))
        assert set(issue) <= set(REVIEW_ISSUE_KEYS)
        assert set(REVIEW_ISSUE_KEYS) - set(issue) <= {"suggestion", "requiredField"}
        assert "suggestion" not in issue


def test_gate_requires_completed_format_check_and_no_critical_issues():
    crit = {"id": "a", "severity": "critical"}
    hint = {"id": "b", "severity": "hint"}
    assert evaluate_gate([hint], True)["canApprove"] is True
    assert evaluate_gate([hint], False)["canApprove"] is False
    gate = evaluate_gate([crit, hint], True)
    assert gate["canApprove"] is False and gate["blockingIssueIds"] == ["a"]
    assert gate["canExportFormal"] is False and gate["canExportInternalDraft"] is True


def test_table_anchored_fragment_is_only_searched_in_tables():
    # regression: {"text": "26", "table": 0} used to match 「示办发〔2026〕8号」
    _, index = build_spec(draft(load("standard_notice")))
    issue, detail = issue_from_kit_hit(KitHit("数字自洽", "合计不符", "x", True, [{"text": "26", "table": 0}]), [], index)
    assert issue["anchor"] == "" and issue["locationLabel"] == "表格"     # no "26" in the table
    issue, _ = issue_from_kit_hit(KitHit("数字自洽", "合计不符", "x", True, [{"text": "25", "table": 0}]), [], index)
    assert issue["anchor"] == "blk-s2-t"


def test_long_title_without_line_breaks_gets_a_hint():
    data = load("standard_notice")
    assert "TITLE_LINE_BREAK" not in codes(rules.check_elements(draft(data)))   # titleLines given
    data["titleLines"] = None
    assert "TITLE_LINE_BREAK" in codes(rules.check_elements(draft(data)))


def test_empty_fields_render_as_visible_placeholders():
    data = load("standard_notice")
    data["fields"]["undertaker"] = ""
    spec, index = build_spec(draft(data))
    para = next(c["text"] for c in spec["components"] if c["type"] == "p" and "报送" in c["text"])
    assert "报送【待补充：承办部门】；" in para
    assert any(e.anchor == "seg-undertaker" and e.text == "【待补充：承办部门】" for e in index)
