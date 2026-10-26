"""Policy PDF import must retain source/page anchors and never lose scan pages."""
import pytest
from app.services.policy.extract import extract_file
from app.services.policy.errors import PolicyError
from app.services.policy.library import ImportRequest
from test_policy_library import make

DATA = b"%PDF-1.7\nunit-test-input"


def parsed(*, blank=False):
    return {"success": True, "error": None, "page_count": 2, "markdown": "ignored",
            "pages": [{"page": 1, "text": "第一条 第十 五个五年计划。", "blocks": []},
                      {"page": 2, "text": "" if blank else "第二条 ABC DEF 不应合并英文单词。", "blocks": []}],
            "metadata": {"title": "C:\\private\\misleading.pdf"}, "warnings": []}


@pytest.fixture()
def pdf_module(monkeypatch):
    from app.services.policy import pdf
    from app import config
    monkeypatch.setattr(config, "_config", {"policy_pdf": {"engine": "opendataloader"}})
    monkeypatch.setattr(pdf, "parse_pdf", lambda *a, **k: parsed())
    return pdf


def test_text_pdf_keeps_pages_normalizes_cjk_and_ignores_title_metadata(pdf_module):
    doc = extract_file("policy.pdf", DATA)
    assert "第十五个五年" in doc.text and "ABC DEF" in doc.text
    assert doc.title == "" and [p["page"] for p in doc.meta["pdf_pages"]] == [1, 2]
    assert doc.meta["pdf_sha256"] and doc.meta["parser"] == "opendataloader_pdf"


@pytest.mark.parametrize("mode", ["scan", "mixed", "timeout"])
def test_scan_partial_and_adapter_failure_use_existing_ocr(pdf_module, monkeypatch, mode):
    calls = []
    monkeypatch.setattr(pdf_module, "parse_pdf", lambda *a, **k: parsed(blank=True) if mode == "mixed" else {"success": False, "error": mode})
    def legacy(path):
        calls.append(path)
        return "# policy.pdf\n\n- Total pages: 2\n\n## Page 1\n第一条 文字。\n\n## Page 2\n第二条 扫描识别正文。", {"source": "poppler_pdf_hybrid", "page_count": 2, "image_pages": [2], "visual_pages": [2]}, []
    monkeypatch.setattr(pdf_module, "legacy_extract", legacy)
    doc = extract_file("policy.pdf", DATA)
    assert len(calls) == 1 and "第二条扫描识别正文" in doc.text
    assert doc.meta["parser"] == "poppler_pdf_hybrid" and doc.reliable is False


def test_failed_ocr_does_not_write_an_empty_or_partial_policy(pdf_module, monkeypatch, tmp_path):
    monkeypatch.setattr(pdf_module, "parse_pdf", lambda *a, **k: {"success": False, "error": "NO_TEXT"})
    monkeypatch.setattr(pdf_module, "legacy_extract", lambda *a: (_ for _ in ()).throw(RuntimeError("OCR unavailable")))
    library, _ = make(tmp_path)
    result = library.import_policy(ImportRequest(filename="policy.pdf", title="真实输入标题", data=DATA))
    assert result["error"]["code"] == "EXTRACT_FAILED"
    assert library.store.count(include_history=True) == 0


def test_incomplete_ocr_is_rejected_instead_of_silently_omitting_pages(pdf_module, monkeypatch):
    monkeypatch.setattr(pdf_module, "parse_pdf", lambda *a, **k: {"success": False, "error": "NO_TEXT"})
    monkeypatch.setattr(pdf_module, "legacy_extract", lambda *a: ("第一条 部分识别", {"page_count": 2, "image_pages": [1, 2], "visual_pages": [1]}, []))
    with pytest.raises(PolicyError, match="完整|失败|缺"):
        extract_file("policy.pdf", DATA)


def test_import_persists_pdf_page_and_hash_in_source_anchor(pdf_module, tmp_path):
    library, _ = make(tmp_path)
    result = library.import_policy(ImportRequest(filename="policy.pdf", title="输入的政策名称", data=DATA))
    assert result.get("error") is None, result
    assert result["policy"]["title"] == "输入的政策名称"
    clauses = library.store.clauses_for(result["policy"]["id"])
    assert [c.page_number for c in clauses] == [1, 2]
    assert all("sha256:" in c.source_anchor for c in clauses)
    citation = library.citations([f"clause:{clauses[1].id}"])["citations"][0]
    assert citation["pageNumber"] == 2 and "PDF" in citation["sourceAnchor"]


def test_pdf_requires_real_pdf_signature():
    with pytest.raises(PolicyError):
        extract_file("pretend.pdf", b"not pdf")
