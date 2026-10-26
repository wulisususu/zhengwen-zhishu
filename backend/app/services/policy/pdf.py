"""Policy-only PDF import. ARM64-validated text parsing, existing OCR fallback."""
from pathlib import Path
import hashlib
import re
import tempfile
import subprocess
from app.services.opendataloader_pdf_adapter import AdapterConfig, parse_pdf
from app.services.policy import errors
from app.services.policy.errors import PolicyError


def legacy_extract(path):
    from app.services import file_parse_service as legacy
    markdown, metadata, ocr = legacy._extract_pdf(path)
    if metadata.get("source") == "poppler_pdf_hybrid":
        # The legacy Markdown compacts blank pages and may glue page headings
        # together. Re-read its original text source, retaining form feeds.
        raw = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, timeout=60, encoding="utf-8")
        if raw.returncode != 0:
            raise RuntimeError("无法核对原始PDF物理页号")
        parts = raw.stdout.split("\f")
        if parts and not parts[-1].strip():
            parts.pop()
        count = metadata.get("page_count", len(parts))
        if len(parts) != count:
            raise RuntimeError("PDF物理页数无法核对")
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        images = set(metadata.get("image_pages", []))
        pages = []
        for number, text in enumerate(parts, start=1):
            if number in images:
                # MiniCPM image summaries have strict 96/128-token budgets.
                # Policy import requires full-page transcription, so reuse the
                # original renderer/CPU OCR without a model-summary token cap.
                image = legacy._render_pdf_page(path, digest, number)
                full_text = legacy._run_cpu_ocr(image)
                if not full_text.strip():
                    raise RuntimeError("扫描页没有完整OCR结果")
                text = full_text
            pages.append({"page": number, "text": text.strip(), "blocks": []})
        metadata = {**metadata, "_policy_pages": pages, "policy_ocr": "full_page_cpu" if images else "text_layer",
                    "visual_pages": sorted(images)}
    return markdown, metadata, ocr


def normalize_cjk(text):
    # PDF line layout sometimes inserts spaces inside Chinese words. Do not join
    # paragraph boundaries, Latin words, numbers or punctuation.
    return re.sub(r"(?<=[\u3400-\u9fff])[ \t]+(?=[\u3400-\u9fff])", "", text)


def _legacy_pages(markdown, metadata):
    if "_policy_pages" in metadata:
        return metadata["_policy_pages"]
    matches = list(re.finditer(r"(?m)^(?:## Page\s+(\d+)[^\n]*|### 第(\d+)页图片分析)\s*\n", markdown))
    if not matches:
        if metadata.get("page_count", 1) > 1:
            raise RuntimeError("OCR未提供完整的逐页结果")
        body = re.sub(r"(?m)^#.*\n?|^- Total pages:.*\n?", "", markdown).strip()
        return [{"page": 1, "text": body, "blocks": []}]
    return [{"page": int(m.group(1) or m.group(2)), "text": markdown[m.end():matches[i+1].start() if i+1 < len(matches) else len(markdown)].strip(), "blocks": []} for i, m in enumerate(matches)]


def extract_pdf(data):
    from app.config import get_config
    from app.services.policy.extract import ExtractedDocument
    if not data.lstrip().startswith(b"%PDF-"):
        raise PolicyError(errors.EXTRACT_FAILED, "上传内容不是有效PDF文件。")
    section = (get_config() or {}).get("policy_pdf", {})
    config = AdapterConfig(jar_path=section.get("jar_path"), java_bin=section.get("java_bin", "java"),
                           timeout_seconds=min(120, max(0.01, float(section.get("timeout_seconds", 60)))),
                           jvm_options=("-Xmx512m",), max_concurrent=1)
    reason = "legacy_selected"
    envelope = None
    try:
        with tempfile.TemporaryDirectory(prefix="policy-pdf-") as tmp:
            path = Path(tmp)/"policy.pdf"
            path.write_bytes(data)
            if section.get("engine") == "opendataloader":
                try:
                    envelope = parse_pdf(str(path), config=config)
                except Exception as exc:
                    reason = "adapter_failure:" + type(exc).__name__
                if envelope:
                    reason = envelope.get("error") or "partial_or_image_pages"
                    pages = envelope.get("pages", [])
                    # Mixed scans can have a text header. Any image block or empty
                    # page is conservatively routed through the original OCR path.
                    complete = envelope.get("success") and pages and len(pages) == envelope.get("page_count") and all(
                        p.get("text", "").strip() and not any(b.get("type") == "image" for b in p.get("blocks", [])) for p in pages)
                    if complete:
                        normalized = [{**p, "text": normalize_cjk(p["text"])} for p in pages]
                        tables = any(b.get("type") == "table" for p in pages for b in p.get("blocks", []))
                        return ExtractedDocument(text="\n".join(p["text"] for p in normalized), reliable=not tables,
                            meta={"pdf_pages": normalized, "pdf_sha256": hashlib.sha256(data).hexdigest(),
                                  "parser": "opendataloader_pdf", "warnings": envelope.get("warnings", []), "fallback": False})
            markdown, metadata, _ = legacy_extract(str(path))
            missing = set(metadata.get("image_pages", [])) - set(metadata.get("visual_pages", []))
            if missing:
                raise RuntimeError("扫描页OCR未完整识别，缺少页：" + ",".join(map(str, sorted(missing))))
            pages = _legacy_pages(markdown, metadata)
            if not all(p["text"].strip() for p in pages) or len(pages) != metadata.get("page_count", len(pages)):
                raise RuntimeError("PDF逐页解析不完整，未写入部分正文")
            for page in pages:
                page["text"] = normalize_cjk(page["text"])
            return ExtractedDocument(text="\n".join(p["text"] for p in pages), reliable=False,
                meta={"pdf_pages": pages, "pdf_sha256": hashlib.sha256(data).hexdigest(), "parser": metadata.get("source", "legacy_pdf"),
                      "fallback": True, "fallback_reason": reason, "warnings": ["已使用原PDF/OCR链路，逐页文字及条款切分须人工复核。"]})
    except PolicyError:
        raise
    except Exception:
        raise PolicyError(errors.EXTRACT_FAILED, "PDF解析或OCR失败，未获取完整逐页正文；未写入政策，请检查文件及OCR服务。") from None
