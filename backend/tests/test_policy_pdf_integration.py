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


def test_legacy_mixed_pages_keep_original_page_numbers_despite_merged_markdown(pdf_module, monkeypatch, tmp_path):
    import subprocess
    from app.services import file_parse_service as legacy
    from types import SimpleNamespace
    path = tmp_path / "mixed.pdf"; path.write_bytes(DATA)
    # The old renderer can append a page heading with no newline and renumbers
    # nonempty text pages. Recover original text-layer pages and cached OCR.
    monkeypatch.setattr(legacy, "_extract_pdf", lambda p: ("## Page 1\n第二页文字## Page 1 图片分析（MiniCPM-V）扫描文字", {"source": "poppler_pdf_hybrid", "page_count": 2, "image_pages": [1], "visual_pages": [1]}, []))
    monkeypatch.setattr(legacy, "_cached_pdf_page_visual_by_sha", lambda sha, page: "第一条 扫描文字" if page == 1 else None)
    monkeypatch.setattr(legacy, "_render_pdf_page", lambda *a: "image.png")
    monkeypatch.setattr(legacy, "_run_cpu_ocr", lambda *a: "第一条 扫描文字")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="\f第二条 原始第二页文字。\f"))
    markdown, metadata, _ = pdf_module.legacy_extract(str(path))
    pages = pdf_module._legacy_pages(markdown, metadata)
    assert [p["page"] for p in pages] == [1, 2]
    assert "扫描文字" in pages[0]["text"] and "第二页文字" in pages[1]["text"]


def test_policy_scan_uses_full_page_transcription_instead_of_image_summary(pdf_module, monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace
    from app.services import file_parse_service as legacy
    path=tmp_path/'scan.pdf';path.write_bytes(DATA)
    monkeypatch.setattr(legacy,'_extract_pdf',lambda p: ('一段96tokens图片摘要',{'source':'poppler_pdf_hybrid','page_count':1,'image_pages':[1],'visual_pages':[1]},[]))
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: SimpleNamespace(returncode=0,stdout='\f'))
    monkeypatch.setattr(legacy,'_render_pdf_page',lambda *a:'full-page.png')
    text='\n'.join(f'第{i}条 完整条款正文。' for i in range(1,61))
    monkeypatch.setattr(legacy,'_run_cpu_ocr',lambda image: text)
    markdown,metadata,_=pdf_module.legacy_extract(str(path))
    pages=pdf_module._legacy_pages(markdown,metadata)
    assert '第60条' in pages[0]['text'] and '96tokens' not in pages[0]['text']
