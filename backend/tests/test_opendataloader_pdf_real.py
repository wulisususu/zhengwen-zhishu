"""OpenDataLoader adapter — REAL parse tests (runs the actual JVM; opt-in).

    ODL_REAL=1 [ODL_JAR=/path/to/opendataloader-pdf-cli.jar] \
    [ODL_REAL_SAMPLES=/srv/box/in/policy-pdfs] pytest tests/test_opendataloader_pdf_real.py

Skipped unless ODL_REAL=1 and Java 11+ plus the jar (installed package or
ODL_JAR) are available. Synthetic samples live in tests/fixtures/pdf; the
gov.cn samples (A-D) are not committed and are used only when
ODL_REAL_SAMPLES points at them.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.services import opendataloader_pdf_adapter as odl
from app.services.opendataloader_pdf_adapter import AdapterConfig, OpenDataLoaderError

FIX = Path(__file__).resolve().parent / "fixtures" / "pdf"


def _config() -> AdapterConfig:
    return AdapterConfig(jar_path=os.environ.get("ODL_JAR") or None, timeout_seconds=600)


def _available() -> str | None:
    if os.environ.get("ODL_REAL") != "1":
        return "set ODL_REAL=1 to run real parse tests"
    try:
        odl.locate_jar(_config())
        odl.check_java("java")
    except OpenDataLoaderError as exc:
        return str(exc)
    return None


_reason = _available()
pytestmark = pytest.mark.skipif(_reason is not None, reason=_reason or "")


def _samples() -> dict[str, Path]:
    root = os.environ.get("ODL_REAL_SAMPLES")
    if not root:
        return {}
    return {p.name[0]: p for p in sorted(Path(root).glob("*.pdf")) if p.name[:1] in "ABCD"}


def nws(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


# ---------------------------------------------------------------- synthetic samples (committed)

def test_real_text_pdf_pages_and_text():
    env = odl.parse_pdf(str(FIX / "text_3p.pdf"), config=_config())
    assert env["success"] is True, env["error"]
    assert env["page_count"] == 3 and [p["page"] for p in env["pages"]] == [1, 2, 3]
    assert "第一条" in env["pages"][0]["text"] and "第五条" in env["pages"][1]["text"]
    assert env["metadata"]["mode"] == "local" and env["metadata"]["java"]


def test_real_table_pdf_keeps_cells():
    env = odl.parse_pdf(str(FIX / "table_1p.pdf"), config=_config())
    table = next(b for b in env["pages"][0]["blocks"] if b["type"] == "table")
    assert (table["rows"], table["columns"]) == (4, 4)
    assert [c["text"] for c in table["cells"] if c["row"] == 1] == ["序号", "事项名称", "责任单位", "完成时限"]


def test_real_scanned_pdf_reports_no_ocr():
    env = odl.parse_pdf(str(FIX / "scanned_1p.pdf"), config=_config())
    assert env["success"] is False and env["markdown"] == ""
    assert any("OCR" in w for w in env["warnings"])


def test_real_corrupt_pdf_reports_cli_error():
    env = odl.parse_pdf(str(FIX / "corrupt.pdf"), config=_config())
    assert env["success"] is False and env["error"].startswith("CLI_FAILED: 'corrupt.pdf'")


# ---------------------------------------------------------------- gov.cn samples (ODL_REAL_SAMPLES)

@pytest.fixture(scope="module")
def gov_batch():
    samples = _samples()
    if len(samples) != 4:
        pytest.skip("ODL_REAL_SAMPLES with A-D not provided")
    keys = ["A", "B", "C", "D"]
    return dict(zip(keys, odl.parse_pdfs([str(samples[k]) for k in keys], config=_config())))


@pytest.mark.parametrize("key, pages", [("A", 12), ("B", 14), ("D", 28)])
def test_gov_text_pdfs_parse_with_page_mapping(gov_batch, key, pages):
    env = gov_batch[key]
    assert env["success"] is True, env["error"]
    assert env["page_count"] == pages
    assert [p["page"] for p in env["pages"]] == list(range(1, pages + 1))
    assert all(p["text"].strip() for p in env["pages"]), [p["page"] for p in env["pages"] if not p["text"].strip()]
    assert all(b["page"] == p["page"] and b["bbox"] for p in env["pages"] for b in p["blocks"])
    assert env["metadata"]["batch_size"] == 4


@pytest.mark.parametrize("key", ["A", "B"])
def test_gov_indicator_tables_keep_cell_structure(gov_batch, key):
    tables = [b for p in gov_batch[key]["pages"] for b in p["blocks"] if b["type"] == "table" and b["text"].strip()]
    assert tables, "expected at least one non-empty table (专栏 indicators)"
    assert all(len(t["cells"]) and all(isinstance(c["row"], int) and isinstance(c["col"], int) for c in t["cells"]) for t in tables)


def test_gov_scanned_pdf_is_reported_honestly(gov_batch):
    env = gov_batch["C"]
    assert env["success"] is False and env["markdown"] == ""
    assert env["page_count"] == 16
    assert env["warnings"][0].startswith("整份文件没有可提取的文本层")
