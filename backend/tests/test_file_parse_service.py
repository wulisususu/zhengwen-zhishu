from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import json

import pytest


def test_pdf_parser_uses_poppler_when_legacy_runner_is_missing(monkeypatch, tmp_path: Path):
    from app.services import file_parse_service as parser

    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nplaceholder")
    monkeypatch.setattr(parser, "PIPELINE_RUNNER", tmp_path / "missing-runner.py")

    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append([str(part) for part in cmd])
        if cmd[0] == "pdftotext":
            return SimpleNamespace(returncode=0, stdout="Project revenue increased by 18%.", stderr="")
        if cmd[0] == "pdfinfo":
            return SimpleNamespace(returncode=0, stdout="Pages:          1\n", stderr="")
        if cmd[0] == "pdfimages":
            return SimpleNamespace(returncode=0, stdout="page num type width height\n", stderr="")
        raise AssertionError(f"unexpected parser command: {cmd}")

    monkeypatch.setattr(parser.subprocess, "run", fake_run)

    markdown, metadata, ocr_pages = parser._extract_pdf(str(pdf_path))

    assert "Project revenue increased by 18%" in markdown
    assert metadata["source"] == "poppler_pdf_hybrid"
    assert metadata["page_count"] == 1
    assert ocr_pages == []
    assert [call[0] for call in calls] == ["pdfinfo", "pdftotext", "pdfimages"]


def test_image_parser_falls_back_to_cpu_ocr_when_minicpm_fails(monkeypatch):
    from app.services import file_parse_service as parser

    def fail_minicpm(_image_path: str):
        raise RuntimeError("MiniCPM OCR inference timeout")

    monkeypatch.setattr(parser, "_run_minicpm_image", fail_minicpm)
    monkeypatch.setattr(parser, "_run_cpu_ocr", lambda _image_path: "会议主题：年度经营复盘", raising=False)

    markdown, metadata, ocr_pages = parser._extract_image("brief.png")

    assert "年度经营复盘" in markdown
    assert metadata["source"] == "rapidocr_onnxruntime_fallback"
    assert "MiniCPM OCR inference timeout" in metadata["vision_error"]
    assert ocr_pages == [1]


def test_scanned_pdf_image_analysis_falls_back_to_cpu_ocr_when_minicpm_fails(monkeypatch):
    from app.services import file_parse_service as parser

    monkeypatch.setattr(parser, "_pdf_image_pages_from_infos", lambda *_args, **_kwargs: [1])
    monkeypatch.setattr(parser, "_cached_pdf_page_visual_by_sha", lambda *_args: None)
    monkeypatch.setattr(parser, "_extract_pdf_page_images", lambda *_args: ["scan-page.png"])
    monkeypatch.setattr(parser, "_run_minicpm_image", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("NPU unavailable")))
    monkeypatch.setattr(parser, "_run_cpu_ocr", lambda _path: "扫描件标题：年度经营复盘", raising=False)
    cached: list[str] = []
    monkeypatch.setattr(parser, "_write_pdf_page_visual_cache_by_sha", lambda *_args: cached.append(_args[-1]))

    pages = parser._analyze_pdf_image_pages("scan.pdf", "digest", [{"page": 1}])

    assert "年度经营复盘" in pages[1]
    assert "CPU OCR" in pages[1]
    assert cached == [pages[1]]


def test_vectorization_is_submitted_to_a_dedicated_executor(monkeypatch):
    from app.services import file_parse_service as parser

    calls = []

    class RecordingExecutor:
        def submit(self, func, *args):
            calls.append((func, args))

    monkeypatch.setattr(parser, "_vector_executor", RecordingExecutor(), raising=False)

    parser._schedule_vectorization(42)

    assert calls == [(parser._vectorize_parsed_file, (42,))]


def test_minicpm_can_be_disabled_for_cpu_ocr_fallback(monkeypatch, tmp_path: Path):
    from app.services import file_parse_service as parser

    monkeypatch.setattr(parser, "MINICPM_ENABLED", False, raising=False)
    monkeypatch.setattr(parser, "MINICPM_PYTHON", tmp_path / "missing-python")

    with pytest.raises(RuntimeError, match="disabled by configuration"):
        parser._run_minicpm_image("brief.png")


def test_pdf_visual_cache_ignores_previous_minicpm_failure_text(monkeypatch, tmp_path: Path):
    from app.services import file_parse_service as parser

    monkeypatch.setattr(parser, "VISUAL_CACHE_DIR", tmp_path)
    parser._write_pdf_page_visual_cache_by_sha("digest", 1, "MiniCPM 图片分析失败：NPU unavailable")

    assert parser._cached_pdf_page_visual_by_sha("digest", 1) is None


def test_pdf_parse_cache_does_not_reuse_previous_visual_failure_text():
    from app.services import file_parse_service as parser

    parsed = SimpleNamespace(
        markdown="## PDF 图片分析（MiniCPM-V）\nMiniCPM 图片分析失败：NPU unavailable",
        metadata_json=json.dumps({
            "parse_version": parser.PDF_PARSE_VERSION,
            "minicpm_required": True,
            "image_pages": [1],
            "visual_pages": [1],
        }),
    )

    assert parser._cache_compatible(parsed, "brief.pdf") is False
