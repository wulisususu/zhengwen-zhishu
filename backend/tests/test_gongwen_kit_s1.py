"""S1 characterization of gongwen-kit `check --json` against tests/fixtures/gongwen.

Pins the measured behaviour behind the no-go decision (docs/spike/gongwen-kit.md).
The five planted-error samples are xfail(strict=True): if a future gongwen-kit
starts catching one of them, that test fails and S1 should be re-run.
Skipped unless node and backend/third_party/gongwen-kit (with node_modules) exist.
"""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
KIT = BACKEND / "third_party" / "gongwen-kit"
FIXTURES = BACKEND / "tests" / "fixtures" / "gongwen"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    not NODE or not (KIT / "bin" / "gongwen.js").exists() or not (KIT / "node_modules").exists(),
    reason="node or backend/third_party/gongwen-kit not installed",
)


def check(path: Path) -> tuple[int, dict]:
    proc = subprocess.run(
        [NODE, str(KIT / "bin" / "gongwen.js"), "check", str(path), "--json"],
        capture_output=True, text=True, timeout=60,
    )
    return proc.returncode, json.loads(proc.stdout)


def blocking_rules(report: dict) -> list[str]:
    return [h["rule"] for c in report["checks"] for h in c["hits"] if h["blocking"]]


@pytest.mark.parametrize("name", [
    "baseline_control.docx",
    "ok_01_upstream_notice.docx",
    "ok_02_upstream_qingshi.docx",
])
def test_compliant_samples_pass(name):
    code, report = check(FIXTURES / name)
    assert (code, report["status"], blocking_rules(report)) == (0, "pass", [])


def test_markdown_to_docx_sample_hits_real_layout_deviation():
    # Not a false positive: markdown_to_docx writes US Letter with Word default margins.
    code, report = check(FIXTURES / "ok_03_markdown_to_docx.docx")
    assert code == 1 and report["status"] == "hit"
    assert blocking_rules(report) == ["公文版式", "公文版式"]


def test_enumeration_probe_hits_with_yixia_phrasing():
    code, report = check(FIXTURES / "probe_01b_count_yixia.docx")
    assert code == 1 and blocking_rules(report) == ["计数与列举"]


@pytest.mark.xfail(strict=True, reason="gongwen-kit 0.4.4 misses this planted error (S1 no-go)")
@pytest.mark.parametrize("name", [
    "bad_01_count_mismatch.docx",
    "bad_02_heading_gap.docx",
    "bad_03_no_letterhead.docx",
    "bad_04_date_iso.docx",
    "bad_05_no_banji.docx",
])
def test_planted_error_is_detected(name):
    code, report = check(FIXTURES / name)
    assert code == 1 and report["status"] == "hit"


def test_report_metadata_and_sha256(tmp_path):
    src = FIXTURES / "baseline_control.docx"
    _, report = check(src)
    assert report["toolVersion"] == "0.4.4"
    assert report["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert report["generatedAt"]


@pytest.mark.parametrize("content", [b"not a zip", b"PK\x03\x04garbage"])
def test_unreadable_file_is_fault_not_pass(tmp_path, content):
    bad = tmp_path / "broken.docx"
    bad.write_bytes(content)
    code, report = check(bad)
    assert (code, report["status"]) == (2, "fault")


def test_missing_file_is_fault(tmp_path):
    code, report = check(tmp_path / "missing.docx")
    assert (code, report["status"]) == (2, "fault")


def test_check_does_not_modify_input_and_handles_odd_names(tmp_path):
    odd = tmp_path / "关于 开展培训的通知（第2稿）[终版].docx"
    shutil.copy(FIXTURES / "ok_03_markdown_to_docx.docx", odd)
    before = hashlib.md5(odd.read_bytes()).hexdigest()
    code, report = check(odd)
    assert code == 1 and report["file"] == odd.name
    assert hashlib.md5(odd.read_bytes()).hexdigest() == before
