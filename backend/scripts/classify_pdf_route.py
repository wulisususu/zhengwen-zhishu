#!/usr/bin/env python3
"""Classify a PDF and recommend a parsing route for OpenClaw."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


BOARD_LOCAL = "board_local"
REMOTE_FAST_OCR = "remote_fast_ocr"
HYBRID_VISUAL_PAGES = "hybrid_visual_pages"


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _tool(name: str) -> str | None:
    return shutil.which(name)


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _read_page_count(pdf_path: Path) -> tuple[int, str]:
    pdfinfo = _tool("pdfinfo")
    if pdfinfo:
        proc = _run([pdfinfo, str(pdf_path)], timeout=20)
        if proc.returncode == 0:
            match = re.search(r"^Pages:\s*(\d+)\s*$", proc.stdout, flags=re.MULTILINE)
            if match:
                return int(match.group(1)), "pdfinfo"
    try:
        from pypdf import PdfReader  # type: ignore

        return len(PdfReader(str(pdf_path)).pages), "pypdf"
    except Exception:
        return 0, "unavailable"


def _extract_text(pdf_path: Path) -> tuple[str, dict[str, Any]]:
    pdftotext = _tool("pdftotext")
    if not pdftotext:
        return "", {"available": False, "returncode": None, "error": "pdftotext not found"}
    try:
        proc = _run([pdftotext, "-layout", str(pdf_path), "-"], timeout=45)
    except Exception as exc:
        return "", {"available": True, "returncode": None, "error": str(exc)}
    return proc.stdout or "", {
        "available": True,
        "returncode": proc.returncode,
        "stderr_tail": (proc.stderr or "")[-500:],
    }


def _image_infos(pdf_path: Path, page_count: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pdfimages = _tool("pdfimages")
    if not pdfimages:
        return [], {"available": False, "returncode": None, "error": "pdfimages not found"}
    try:
        proc = _run([pdfimages, "-list", str(pdf_path)], timeout=30)
    except Exception as exc:
        return [], {"available": True, "returncode": None, "error": str(exc)}
    if proc.returncode != 0:
        return [], {"available": True, "returncode": proc.returncode, "stderr_tail": (proc.stderr or "")[-500:]}

    infos: list[dict[str, Any]] = []
    for raw in (proc.stdout or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("page ") or line.startswith("---"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            page = int(parts[0])
            number = int(parts[1])
            width = int(parts[3])
            height = int(parts[4])
        except Exception:
            continue
        if page <= 0 or (page_count and page > page_count):
            continue
        infos.append({
            "page": page,
            "num": number,
            "type": parts[2],
            "width": width,
            "height": height,
            "pixels": width * height,
            "raw": line,
        })
    return infos, {"available": True, "returncode": proc.returncode}


def _garbled_score(text: str) -> dict[str, Any]:
    compact = _compact_text(text)
    total = len(compact)
    if total == 0:
        return {"is_garbled": False, "bad_ratio": 0, "cjk_ratio": 0, "bad_chars": 0, "compact_chars": 0}
    bad_chars = compact.count("?") + compact.count("\ufffd")
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", compact))
    bad_ratio = bad_chars / total
    cjk_ratio = cjk_chars / total
    is_garbled = total >= 20 and bad_chars >= max(8, int(total * 0.22)) and cjk_chars < max(6, int(total * 0.08))
    return {
        "is_garbled": bool(is_garbled),
        "bad_ratio": round(bad_ratio, 4),
        "cjk_ratio": round(cjk_ratio, 4),
        "bad_chars": bad_chars,
        "compact_chars": total,
    }


def _classify(metrics: dict[str, Any]) -> tuple[str, str, str]:
    text_chars_per_page = float(metrics.get("text_chars_per_page") or 0)
    image_page_ratio = float(metrics.get("image_page_ratio") or 0)
    image_pages = list(metrics.get("image_pages") or [])
    garbled = bool(metrics.get("garbled"))

    if garbled:
        return "image_heavy_pdf" if image_pages else "unknown", REMOTE_FAST_OCR, "文本层疑似乱码，远端视觉 OCR 更稳"
    if text_chars_per_page < 80 and image_page_ratio >= 0.5:
        return "scanned_pdf", REMOTE_FAST_OCR, "文本层很少且多数页面含图片，疑似扫描件"
    if text_chars_per_page < 40 and image_pages:
        return "scanned_pdf", REMOTE_FAST_OCR, "文本层几乎为空且检测到图片页"
    if image_page_ratio > 0.35:
        return "image_heavy_pdf", REMOTE_FAST_OCR, "图片页占比较高，远端高速 OCR 更合适"
    if text_chars_per_page >= 250 and image_page_ratio < 0.2:
        return "text_pdf", BOARD_LOCAL, "文本层充足且图片较少，板端文本解析最快"
    if image_pages:
        return "mixed", HYBRID_VISUAL_PAGES, "文本和图片混合，建议板端解析文本并按页补充视觉 OCR"
    if text_chars_per_page >= 80:
        return "text_pdf", BOARD_LOCAL, "文本层可用，板端解析优先"
    return "unknown", REMOTE_FAST_OCR, "文本层不足且类型不明确，远端 OCR 更保险"


def classify_pdf(pdf_path: Path) -> dict[str, Any]:
    page_count, page_count_source = _read_page_count(pdf_path)
    if page_count <= 0:
        raise RuntimeError("cannot read PDF page count")

    text, text_tool = _extract_text(pdf_path)
    compact = _compact_text(text)
    text_chars = len(compact)
    text_chars_per_page = text_chars / max(1, page_count)
    garbled_info = _garbled_score(text)

    image_infos, image_tool = _image_infos(pdf_path, page_count)
    image_pages = sorted({int(info["page"]) for info in image_infos if int(info.get("page") or 0) > 0})
    image_page_ratio = len(image_pages) / max(1, page_count)
    large_images = [info for info in image_infos if int(info.get("pixels") or 0) >= 80 * 80]

    result: dict[str, Any] = {
        "pdf_path": str(pdf_path),
        "page_count": page_count,
        "page_count_source": page_count_source,
        "text_chars": text_chars,
        "text_chars_per_page": round(text_chars_per_page, 2),
        "image_count": len(image_infos),
        "large_image_count": len(large_images),
        "image_pages": image_pages,
        "image_page_ratio": round(image_page_ratio, 4),
        "garbled": garbled_info["is_garbled"],
        "garbled_score": garbled_info,
        "tools": {"pdftotext": text_tool, "pdfimages": image_tool},
    }
    pdf_type, route, reason = _classify(result)
    result.update({
        "pdf_type": pdf_type,
        "recommended_route": route,
        "reason": reason,
        "route_options": {
            "board_local": "板端本地文本/混合解析",
            "remote_fast_ocr": "上传到高速 OCR 服务器做整页视觉 OCR",
            "hybrid_visual_pages": "板端解析文本，只把图片页交给高速 OCR",
        },
    })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify a PDF and recommend board/remote OCR route.")
    parser.add_argument("pdf", type=Path, help="Input PDF path")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args(argv)

    pdf_path = args.pdf.expanduser().resolve()
    if not pdf_path.exists():
        print(json.dumps({"error": "file not found", "pdf_path": str(pdf_path)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if pdf_path.suffix.lower() != ".pdf":
        print(json.dumps({"error": "input is not a PDF", "pdf_path": str(pdf_path)}, ensure_ascii=False), file=sys.stderr)
        return 2

    try:
        result = classify_pdf(pdf_path)
    except Exception as exc:
        print(json.dumps({"error": str(exc), "pdf_path": str(pdf_path)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
