"""Real gongwen-kit integration: generation, two-layer review, external check/fix, tool failures.

Skipped unless node and backend/third_party/gongwen-kit (with node_modules) exist.
"""
import dataclasses
import hashlib
import json
import re
import shutil
import time
import zipfile
from pathlib import Path

import pytest

from app.services.gongwen import catalog
from app.services.gongwen.bridge import render_docx
from app.services.gongwen.checker import check_docx
from app.services.gongwen.fixer import fix_copy
from app.services.gongwen.review import (DRAFT_MARK, REVIEW_ISSUE_KEYS, render_notice,
                                         review_external_docx, review_notice)
from app.services.gongwen.runner import GongwenToolError
from app.services.gongwen.schema import NoticeDraft
from app.services.gongwen.settings import DEFAULT_KIT, GongwenSettings

HERE = Path(__file__).resolve().parent
NOTICES = HERE / "fixtures" / "gongwen" / "notices"
INNET = HERE / "fixtures" / "gongwen" / "innet"
SETTINGS = GongwenSettings()

pytestmark = pytest.mark.skipif(
    not shutil.which("node") or not (DEFAULT_KIT / "node_modules").is_dir(),
    reason="node or backend/third_party/gongwen-kit not installed",
)


def load(name: str) -> NoticeDraft:
    return NoticeDraft.model_validate(json.loads((NOTICES / f"{name}.json").read_text(encoding="utf-8")))


def xml(docx: Path, part: str = "word/document.xml") -> str:
    return zipfile.ZipFile(docx).read(part).decode("utf-8")


def text_of(docx: Path) -> str:
    return "".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", xml(docx)))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── 标准通知生成 ──────────────────────────────────────────────────────────
def test_standard_notice_renders_gbt9704_docx_that_passes_the_kit_check(tmp_path):
    out = tmp_path / "notice.docx"
    meta = render_notice(load("standard_notice"), out, SETTINGS, internal_draft=False)
    assert meta["toolVersion"] == "0.4.4" and out.stat().st_size > 5000
    doc = xml(out)
    pg = re.search(r"<w:pgSz [^>]*>", doc).group(0)
    assert 'w:w="11906"' in pg and 'w:h="16838"' in pg                      # A4
    mar = re.search(r"<w:pgMar [^>]*>", doc).group(0)
    assert all(f'w:{k}="{v}"' in mar for k, v in
               {"top": 2098, "bottom": 1984, "left": 1587, "right": 1474}.items())   # 37/35/28/26 mm
    assert 'w:linePitch="579"' in doc
    body = text_of(out)
    for expected in ["示例单位办公室文件", "示办发〔2026〕8号", "示例单位办公室关于开展公文格式", "规范培训工作的通知",
                     "各部门、各直属单位：", "培训任务", "讲解公文版心与行字数要求", "表1　参训名额", "合计",
                     "附件：参训人员名单", "2026年10月26日", "抄送：示例单位领导班子成员", "印发",
                     "（联系人：×××，联系电话：×××-××××××××）"]:
        assert expected in body, expected
    assert "一、培训任务" not in body and "【待补充" not in body   # numbering comes from the numbering part
    assert doc.count("<w:numPr>") >= 6
    result = check_docx(out, SETTINGS)
    assert result["success"] and result["status"] == "pass" and result["hits"] == []


def test_internal_draft_is_marked_unreviewed_in_every_header(tmp_path):
    out = tmp_path / "draft.docx"
    render_notice(load("standard_notice"), out, SETTINGS, internal_draft=True)
    names = [n for n in zipfile.ZipFile(out).namelist() if re.match(r"word/header\d*\.xml", n)]
    assert len(names) >= 2 and all(DRAFT_MARK in xml(out, n) for n in names)
    formal = tmp_path / "formal.docx"
    render_notice(load("standard_notice"), formal, SETTINGS, internal_draft=False)
    assert DRAFT_MARK not in "".join(xml(formal, n) for n in zipfile.ZipFile(formal).namelist() if n.endswith(".xml"))


# ── 双层审校 ──────────────────────────────────────────────────────────────
def assert_review_shape(result: dict):
    assert result["origin"] == "backend"
    for issue in result["issues"]:
        assert set(issue) <= set(REVIEW_ISSUE_KEYS), issue
        assert {"id", "severity", "source", "title", "description", "locationLabel", "anchor", "section"} <= set(issue)
        assert issue["severity"] in catalog.SEVERITIES and issue["source"] == "rule"
        assert "suggestion" not in issue
        assert issue["id"] in result["issueDetails"]
    assert len({i["id"] for i in result["issues"]}) == len(result["issues"])
    assert result["summary"] == {s: sum(i["severity"] == s for i in result["issues"]) for s in catalog.SEVERITIES}


def test_review_of_standard_notice_passes_both_layers():
    result = review_notice(load("standard_notice"), SETTINGS)
    assert_review_shape(result)
    assert result["formatCheck"]["status"] == "pass" and result["formatCheck"]["toolVersion"] == "0.4.4"
    assert [result["issueDetails"][i["id"]]["code"] for i in result["issues"]] == ["POLICY_REF_UNVERIFIED"]
    assert result["policyVerification"]["status"] == "not_available"
    gate = result["gate"]
    assert gate["canApprove"] is True and gate["canExportFormal"] is False


def test_review_of_defective_notice_reports_both_layers_with_real_anchors():
    result = review_notice(load("defective_notice"), SETTINGS)
    assert_review_shape(result)
    found = {(result["issueDetails"][i["id"]]["code"], i["anchor"]) for i in result["issues"]}
    assert {("ELEM_RECIPIENT", "seg-recipient"), ("SIGN_DATE_FORMAT", "blk-sign"), ("ELEM_BANJI", ""),
            ("NUMBERING_GAP", "blk-s4"), ("COUNT_MISMATCH", "blk-s1-p"), ("ELEM_UNDERTAKER", "seg-undertaker"),
            ("POLICY_REF_UNLINKED", "blk-intro"), ("GWK_DOCNO", "seg-docno"), ("GWK_DATE_PAD", "blk-s2-p"),
            ("GWK_HALF_PUNCT", "blk-intro")} <= found
    assert result["formatCheck"]["status"] == "hit"
    assert result["gate"]["canApprove"] is False and len(result["gate"]["blockingIssueIds"]) >= 8


def test_overlapping_kit_hits_are_merged_and_hints_are_kept():
    draft = load("standard_notice")
    data = draft.model_dump()
    data["blocks"][11]["segments"][0]["text"] = "各单位于 2026年10月30日前将参训人员名单报送(208室)"
    data["blocks"][9]["table"]["rows"][-1] = ["合计", "26"]
    result = review_notice(NoticeDraft.model_validate(data), SETTINGS)
    details = {result["issueDetails"][i["id"]]["code"]: (i, result["issueDetails"][i["id"]]) for i in result["issues"]}
    assert "GWK_HALF_PUNCT" not in details
    assert details["GWK_HALF_PAREN"][1]["mergedRules"] == ["中文里的半角标点"]
    issue, detail = details["GWK_TOTAL"]
    assert issue["anchor"] == "blk-s2-t" and issue["severity"] == "critical"   # kit tables declare a header row


# ── 桥：只接受固定构件，文本只是数据 ──────────────────────────────────────
def test_bridge_rejects_unknown_components_and_extra_keys(tmp_path):
    base = {"version": 1, "docType": "notice", "title": "t", "draftMark": None}
    for comps in ([{"type": "eval", "code": "1"}], [{"type": "p", "text": "x", "onload": "y"}],
                  [{"type": "table", "head": ["a"], "rows": [["1", "2"]], "widths": [900]}]):
        with pytest.raises(GongwenToolError) as exc:
            render_docx({**base, "components": comps}, tmp_path / "x.docx", SETTINGS)
        assert exc.value.code == catalog.TOOL_RENDER_REJECTED
    with pytest.raises(GongwenToolError) as exc:   # gongwen-kit's own refusal
        render_docx({**base, "components": [{"type": "letterhead", "agency": "长" * 31, "docNo": "x"}]},
                    tmp_path / "x.docx", SETTINGS)
    assert exc.value.code == catalog.TOOL_RENDER_REJECTED and "发文机关标志" in exc.value.message


def test_text_that_looks_like_code_is_rendered_literally(tmp_path):
    marker = tmp_path / "pwned"
    payload = f"\"); require('fs').writeFileSync('{marker}', 'x'); //"
    data = load("standard_notice").model_dump()
    data["blocks"][1]["segments"] = [{"kind": "text", "text": payload}]
    out = tmp_path / "n.docx"
    render_notice(NoticeDraft.model_validate(data), out, SETTINGS, internal_draft=False)
    assert not marker.exists()
    assert "require(&apos;fs&apos;)" in xml(out) or "require('fs')" in text_of(out)


# ── 外来 Word：检查与可选修复，原件不动 ──────────────────────────────────
def test_external_check_and_fix_never_touch_the_original(tmp_path):
    src = tmp_path / "关于 开展培训的通知（第2稿）.docx"
    shutil.copy(INNET / "innet_01_markdown_to_docx.docx", src)
    before = sha(src)
    result = review_external_docx(src, SETTINGS)
    assert_review_shape(result)
    assert [result["issueDetails"][i["id"]]["code"] for i in result["issues"]] == ["GWK_LAYOUT", "GWK_LAYOUT"]
    out = tmp_path / "fixed.docx"
    fixed = fix_copy(src, out, SETTINGS)
    assert sha(src) == before == fixed["srcSha256"] and out.is_file() and sha(out) != before
    assert "原文件未改动" in fixed["report"]
    assert review_external_docx(out, SETTINGS)["formatCheck"]["status"] == "pass"
    with pytest.raises(GongwenToolError):
        fix_copy(src, src, SETTINGS)
    assert sha(src) == before


def test_external_numbering_gap_is_reported_by_paragraph(tmp_path):
    src = tmp_path / "gap.docx"
    shutil.copy(HERE / "fixtures" / "gongwen" / "bad_02_heading_gap.docx", src)
    result = review_external_docx(src, SETTINGS)
    gaps = [i for i in result["issues"] if result["issueDetails"][i["id"]]["code"] == "NUMBERING_GAP"]
    assert len(gaps) == 1 and gaps[0]["anchor"].startswith("p-") and gaps[0]["locationLabel"].startswith("第 ")


# ── 工具异常：绝不判为通过 ────────────────────────────────────────────────
def fake_kit(tmp_path: Path, script: str) -> GongwenSettings:
    kit = tmp_path / "fake-kit"
    (kit / "bin").mkdir(parents=True)
    (kit / "node_modules").mkdir()
    (kit / "bin" / "gongwen.js").write_text(script, encoding="utf-8")
    return dataclasses.replace(SETTINGS, kit_path=kit, check_timeout_seconds=1.5)


def docx_copy(tmp_path: Path) -> Path:
    path = tmp_path / "in.docx"
    shutil.copy(HERE / "fixtures" / "gongwen" / "baseline_control.docx", path)
    return path


@pytest.mark.parametrize("script,code", [
    ("console.log('garbage')", catalog.TOOL_BAD_OUTPUT),
    ("console.log(JSON.stringify({status:'fault',message:'boom',checks:[]})); process.exit(2)", catalog.TOOL_FAULT),
    ("console.log(JSON.stringify({status:'pass',blocking:0,checks:[{check:'x',hits:[]}]})); process.exit(1)",
     catalog.TOOL_INCONSISTENT),
    ("process.exit(2)", catalog.TOOL_BAD_OUTPUT),
])
def test_broken_tool_output_is_an_error(tmp_path, script, code):
    result = check_docx(docx_copy(tmp_path), fake_kit(tmp_path, script))
    assert result["success"] is False and result["status"] is None and result["error"]["code"] == code


def test_hanging_tool_is_killed_at_the_timeout(tmp_path):
    settings = fake_kit(tmp_path, "setTimeout(() => {}, 60000)")
    start = time.monotonic()
    result = check_docx(docx_copy(tmp_path), settings)
    assert result["error"]["code"] == catalog.TOOL_TIMEOUT and time.monotonic() - start < 10


@pytest.mark.parametrize("change,code", [
    ({"node_bin": "/nonexistent/node"}, catalog.TOOL_NODE_NOT_FOUND),
    ({"kit_path": Path("/nonexistent/gongwen-kit")}, catalog.TOOL_KIT_NOT_FOUND),
])
def test_missing_node_or_kit_makes_review_unavailable_not_passed(change, code):
    settings = dataclasses.replace(SETTINGS, **change)
    result = review_notice(load("standard_notice"), settings)
    assert result["formatCheck"] == {"status": "unavailable", "errorCode": code,
                                     "message": result["formatCheck"]["message"]}
    unavailable = [i for i in result["issues"] if i["id"] == "own-format_check_unavailable"]
    assert unavailable and unavailable[0]["severity"] == "critical"
    assert result["gate"]["canApprove"] is False


@pytest.mark.parametrize("name,content", [("a.txt", None), ("renamed.docx", b"plain text")])
def test_non_docx_input_is_rejected(tmp_path, name, content):
    path = tmp_path / name
    if content is None:
        shutil.copy(HERE / "fixtures" / "gongwen" / "baseline_control.docx", path)
    else:
        path.write_bytes(content)
    assert check_docx(path, SETTINGS)["error"]["code"] == catalog.TOOL_INVALID_INPUT


def test_review_is_fast_enough_for_a_synchronous_request():
    start = time.monotonic()
    review_notice(load("standard_notice"), SETTINGS)
    assert time.monotonic() - start < 10


def test_relative_paths_work_for_render_check_and_fix(tmp_path, monkeypatch):
    # regression: node runs with cwd=<file's dir>, so relative paths used to resolve twice
    monkeypatch.chdir(tmp_path)
    Path("sub").mkdir()
    render_notice(load("standard_notice"), Path("sub/n.docx"), SETTINGS, internal_draft=False)
    assert check_docx(Path("sub/n.docx"), SETTINGS)["status"] == "pass"
    fix_copy(Path("sub/n.docx"), Path("sub/fixed.docx"), SETTINGS)
    assert Path("sub/fixed.docx").is_file()
