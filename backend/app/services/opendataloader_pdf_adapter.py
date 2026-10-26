"""OpenDataLoader PDF adapter (spike: adapter + validation only, not wired in).

Nothing in the app calls this module by default. The existing PDF chain
(file_parse_service._extract_pdf: pdfinfo/pdftotext + MiniCPM) is unchanged;
:func:`extract_pdf_with_engine` is the only integration point and must be
selected explicitly (engine="opendataloader" or config ``pdf_parser.engine``).
On any adapter failure it falls back to the existing chain untouched.

Verified against opendataloader-pdf 2.5.15 (PyPI, py3-none-any). The wheel is
a thin wrapper around a bundled Java CLI jar (``opendataloader_pdf/jar/
opendataloader-pdf-cli.jar``, needs Java 11+). Its ``convert()`` has no
timeout and writes to stdout, so this adapter runs the bundled jar itself:
argument list (never shell=True), configurable timeout, one JVM per batch.
Local mode only: hybrid (docling/easyocr) is never enabled, so scanned pages
get no OCR and are reported in ``warnings``.

Blocking: a parse is a blocking subprocess call. The backend runs a single
uvicorn worker, so callers in async code must use :func:`parse_pdf_async` /
:func:`parse_pdfs_async` (thread pool) and never call parse_pdf directly on
the event loop. At most ``max_concurrent`` JVMs run at once (default 1).
"""
from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("app.opendataloader_pdf")

PARSER_NAME = "opendataloader-pdf"
PACKAGE_NAME = "opendataloader-pdf"
MODE = "local"
MIN_JAVA_MAJOR = 11
DEFAULT_TIMEOUT_SECONDS = 120.0
BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = BACKEND_ROOT / "data" / "pdf_parse"

_ERROR_LINE = re.compile(r"^Error:\s*'(?P<name>[^']+)'\s*(?P<reason>.*)$", re.MULTILINE)
_JAVA_VERSION = re.compile(r'version\s+"(?P<v>[^"]+)"')


class OpenDataLoaderError(Exception):
    """Explicit adapter failure with a stable code."""

    NOT_INSTALLED = "NOT_INSTALLED"
    JAVA_NOT_FOUND = "JAVA_NOT_FOUND"
    JAVA_TOO_OLD = "JAVA_TOO_OLD"
    INVALID_INPUT = "INVALID_INPUT"
    OUTPUT_DIR_REJECTED = "OUTPUT_DIR_REJECTED"
    TIMEOUT = "TIMEOUT"
    CLI_FAILED = "CLI_FAILED"
    OUTPUT_INVALID = "OUTPUT_INVALID"

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class AdapterConfig:
    java_bin: str = "java"
    #: Bundled jar location; None = find it in the installed opendataloader_pdf package.
    jar_path: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    #: output_dir must resolve inside one of these roots.
    allowed_output_roots: tuple[str, ...] = (str(DEFAULT_OUTPUT_ROOT),)
    #: Extra JVM flags, e.g. ("-Xmx1g",) to cap the heap on the board.
    jvm_options: tuple[str, ...] = ()
    threads: int = 1
    max_concurrent: int = 1
    temp_root: str | None = None


_semaphores: dict[int, threading.BoundedSemaphore] = {}
_semaphore_lock = threading.Lock()


def _semaphore(limit: int) -> threading.BoundedSemaphore:
    with _semaphore_lock:
        if limit not in _semaphores:
            _semaphores[limit] = threading.BoundedSemaphore(max(1, limit))
        return _semaphores[limit]


# ---------------------------------------------------------------- environment

def locate_jar(config: AdapterConfig) -> Path:
    if config.jar_path:
        jar = Path(config.jar_path).expanduser()
        if not jar.is_file():
            raise OpenDataLoaderError(OpenDataLoaderError.NOT_INSTALLED, f"配置的 jar 不存在：{jar}")
        return jar
    spec = importlib.util.find_spec("opendataloader_pdf")
    if spec is None or not spec.origin:
        raise OpenDataLoaderError(
            OpenDataLoaderError.NOT_INSTALLED,
            "未安装 opendataloader-pdf（pip install -r requirements-pdf.txt），或在配置中指定 jar_path。",
        )
    jar = Path(spec.origin).parent / "jar" / "opendataloader-pdf-cli.jar"
    if not jar.is_file():
        raise OpenDataLoaderError(OpenDataLoaderError.NOT_INSTALLED, "opendataloader-pdf 安装不完整：缺少内置 jar。")
    return jar


def package_version() -> str:
    try:
        return importlib.metadata.version(PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


_java_cache: dict[str, str] = {}


def check_java(java_bin: str) -> str:
    """Return the Java version string; raise if missing or older than 11."""
    if java_bin in _java_cache:
        return _java_cache[java_bin]
    try:
        proc = subprocess.run([java_bin, "-version"], capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        raise OpenDataLoaderError(OpenDataLoaderError.JAVA_NOT_FOUND, f"找不到 Java（{java_bin}），需要 JRE {MIN_JAVA_MAJOR}+。") from None
    except subprocess.TimeoutExpired:
        raise OpenDataLoaderError(OpenDataLoaderError.JAVA_NOT_FOUND, "java -version 超时。") from None
    match = _JAVA_VERSION.search((proc.stderr or "") + (proc.stdout or ""))
    if not match:
        raise OpenDataLoaderError(OpenDataLoaderError.JAVA_NOT_FOUND, "无法识别 Java 版本。")
    version = match.group("v")
    first = version.split(".")[0]
    major = int(version.split(".")[1]) if first == "1" else int(re.sub(r"\D.*$", "", first) or 0)
    if major < MIN_JAVA_MAJOR:
        raise OpenDataLoaderError(OpenDataLoaderError.JAVA_TOO_OLD, f"Java {version} 过旧，需要 {MIN_JAVA_MAJOR}+。")
    _java_cache[java_bin] = version
    return version


def resolve_output_dir(output_dir: str | os.PathLike, allowed_roots: tuple[str, ...]) -> Path:
    """Absolute, symlink-resolved path that must lie inside an allowed root."""
    if output_dir is None or str(output_dir).strip() == "":
        raise OpenDataLoaderError(OpenDataLoaderError.OUTPUT_DIR_REJECTED, "output_dir 为空。")
    target = Path(output_dir).expanduser().resolve(strict=False)
    for root in allowed_roots:
        root_path = Path(root).expanduser().resolve(strict=False)
        if target == root_path or root_path in target.parents:
            if target.exists() and not target.is_dir():
                raise OpenDataLoaderError(OpenDataLoaderError.OUTPUT_DIR_REJECTED, "output_dir 已存在且不是目录。")
            return target
    raise OpenDataLoaderError(OpenDataLoaderError.OUTPUT_DIR_REJECTED, "output_dir 不在允许的根目录内。")


def _check_input(pdf_path: str) -> Path:
    path = Path(pdf_path).expanduser()
    if not path.is_file():
        raise OpenDataLoaderError(OpenDataLoaderError.INVALID_INPUT, "文件不存在。")
    if path.stat().st_size == 0:
        raise OpenDataLoaderError(OpenDataLoaderError.INVALID_INPUT, "文件为空（0 字节）。")
    with path.open("rb") as fh:
        head = fh.read(1024)
    if b"%PDF-" not in head:
        raise OpenDataLoaderError(OpenDataLoaderError.INVALID_INPUT, "不是 PDF 文件（缺少 %PDF- 文件头）。")
    return path.resolve()


# ---------------------------------------------------------------- envelope

def _empty_envelope(error: str | None, version: str, extra_meta: dict | None = None) -> dict:
    return {
        "success": False,
        "error": error,
        "markdown": "",
        "page_count": 0,
        "pages": [],
        "metadata": {"parser": PARSER_NAME, "version": version, "mode": MODE, **(extra_meta or {})},
        "warnings": [],
    }


def _bbox(node: dict) -> list[float] | None:
    box = node.get("bounding box")
    return [float(x) for x in box] if isinstance(box, list) and len(box) == 4 else None


def _node_text(node: dict) -> str:
    """All text under a node. A list item carries ``content`` *and* ``kids``;
    lists keep children in ``list items`` and tables in ``rows[].cells``."""
    parts: list[str] = []
    if isinstance(node.get("content"), str) and node["content"]:
        parts.append(node["content"])
    for key in ("kids", "list items"):
        for child in node.get(key) or []:
            if isinstance(child, dict):
                text = _node_text(child)
                if text:
                    parts.append(text)
    for row in node.get("rows") or []:
        cells = [_node_text(c) for c in row.get("cells") or [] if isinstance(c, dict)]
        if any(cells):
            parts.append("\t".join(cells))
    return "\n".join(parts)


#: Containers whose children are emitted as separate blocks (each keeps its own page and bbox).
_CONTAINER_TYPES = {"text block"}


def _flatten(nodes) -> list[dict]:
    flat: list[dict] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        if node.get("type") in _CONTAINER_TYPES and node.get("kids"):
            flat.extend(_flatten(node["kids"]))
        else:
            flat.append(node)
    return flat


def _block(node: dict) -> dict:
    kind = node.get("type") or "unknown"
    block: dict[str, Any] = {
        "id": node.get("id"),
        "type": kind,
        "page": node.get("page number"),
        "bbox": _bbox(node),
    }
    if kind == "heading":
        block["heading_level"] = node.get("heading level")
    if kind == "table":
        cells = []
        for row in node.get("rows") or []:
            for cell in row.get("cells") or []:
                cells.append({
                    "row": cell.get("row number"),
                    "col": cell.get("column number"),
                    "row_span": cell.get("row span", 1),
                    "col_span": cell.get("column span", 1),
                    "is_header": bool(cell.get("is_header")),
                    "text": _node_text(cell),
                    "bbox": _bbox(cell),
                })
        block.update({"rows": node.get("number of rows"), "columns": node.get("number of columns"), "cells": cells})
        by_row: dict[int, list] = {}
        for c in cells:
            by_row.setdefault(c["row"] or 0, []).append(c)
        block["text"] = "\n".join("\t".join(c["text"] for c in sorted(r, key=lambda c: c["col"] or 0)) for _, r in sorted(by_row.items()))
    elif kind == "list":
        items = [
            {"text": _node_text(i), "bbox": _bbox(i), "page": i.get("page number")}
            for i in node.get("list items") or [] if isinstance(i, dict)
        ]
        block["numbering"] = node.get("numbering style")
        block["items"] = items
        block["text"] = "\n".join(i["text"] for i in items if i["text"])
    elif kind == "image":
        block["text"] = ""
    else:
        block["text"] = _node_text(node)
        if node.get("font"):
            block["font"] = node.get("font")
            block["font_size"] = node.get("font size")
    return block


def build_envelope(doc_json: dict, markdown: str, *, version: str, cli_warnings: list[str] | None = None, elapsed_ms: int = 0) -> dict:
    """Map the CLI JSON (verified structure, see docs) to the adapter envelope."""
    if not isinstance(doc_json, dict) or "kids" not in doc_json:
        raise OpenDataLoaderError(OpenDataLoaderError.OUTPUT_INVALID, "解析结果 JSON 结构不符合预期。")
    page_count = int(doc_json.get("number of pages") or 0)
    pages: dict[int, dict] = {n: {"page": n, "text": "", "blocks": []} for n in range(1, page_count + 1)}
    warnings = list(cli_warnings or [])
    for node in _flatten(doc_json.get("kids")):
        block = _block(node)
        page_no = block["page"] if isinstance(block["page"], int) else None
        if page_no is None:
            warnings.append(f"元素 {block['id']}（{block['type']}）缺少页码，未归入任何页。")
            continue
        pages.setdefault(page_no, {"page": page_no, "text": "", "blocks": []})["blocks"].append(block)
        if block["type"] == "table" and block.get("rows") and block.get("columns"):
            expected = block["rows"] * block["columns"]
            covered = sum((c["row_span"] or 1) * (c["col_span"] or 1) for c in block["cells"])
            if covered != expected:
                warnings.append(f"第{page_no}页表格 {block['id']} 单元格数量与行列不一致（{covered}/{expected}），表格结构可能不完整。")
    for page in pages.values():
        page["text"] = "\n".join(b["text"] for b in page["blocks"] if b.get("text"))
        has_image = any(b["type"] == "image" for b in page["blocks"])
        empty_tables = sum(1 for b in page["blocks"] if b["type"] == "table" and not b.get("text", "").strip())
        if empty_tables:
            warnings.append(f"第{page['page']}页检测到 {empty_tables} 个空表格（无单元格文字，常见于扫描件框线），未作为正文。")
        if not page["text"].strip():
            if has_image or empty_tables:
                warnings.append(f"第{page['page']}页无文本层（疑似扫描件）；本地模式不做 OCR，该页正文不可用。")
            else:
                warnings.append(f"第{page['page']}页未提取到任何内容。")
    ordered = [pages[n] for n in sorted(pages)]
    if page_count and len(ordered) != page_count:
        warnings.append(f"页码不连续：声明 {page_count} 页，实际出现 {len(ordered)} 页。")
    has_text = any(p["text"].strip() for p in ordered)
    if ordered and not has_text:
        warnings.insert(0, "整份文件没有可提取的文本层（疑似扫描件）。本地模式不做 OCR（未启用 hybrid）；"
                           "请回退到现有 MiniCPM / CPU OCR 链路。")
    return {
        "success": has_text,
        "error": None if has_text else "NO_TEXT: 未提取到任何正文（扫描件需要 OCR，本地模式不可用）。",
        "markdown": markdown if has_text else "",
        "page_count": page_count,
        "pages": ordered,
        "metadata": {
            "parser": PARSER_NAME,
            "version": version,
            "mode": MODE,
            "title": doc_json.get("title"),
            "elapsed_ms": elapsed_ms,
        },
        "warnings": warnings,
    }


# ---------------------------------------------------------------- execution

_FILE_LINE = re.compile(r"^INFO: File name: (?P<path>.+)$")


def _cli_warnings(log_text: str) -> dict[str, list[str]]:
    """Group the JVM's WARNING lines by the file being processed (log order).

    The CLI logs ``INFO: File name: <path>`` before each file (JVM forced to
    English so the prefixes are stable). Returns {staged file name: [summary]}.
    """
    per_file: dict[str, list[str]] = {}
    current = ""
    for line in (log_text or "").splitlines():
        m = _FILE_LINE.match(line)
        if m:
            current = Path(m.group("path").strip()).name
            continue
        if line.startswith("WARNING:"):
            per_file.setdefault(current, []).append(re.sub(r"\s+", " ", line[len("WARNING:"):].strip())[:80])
    summaries = {}
    for name, lines in per_file.items():
        kinds = sorted(set(lines))
        summaries[name] = [f"解析器报告 {len(lines)} 条警告（字体/编码/版面），例如：{'; '.join(kinds[:3])}"]
    return summaries


def build_command(staged: list[Path], out_dir: Path, *, jar: Path, config: AdapterConfig, java_tmp: Path) -> list[str]:
    """The exact argument list passed to the JVM (also used by the benchmark)."""
    return [
        config.java_bin,
        "-Djava.awt.headless=true",
        "-Duser.language=en",
        "-Duser.country=US",
        f"-Djava.io.tmpdir={java_tmp}",
        *config.jvm_options,
        "-jar", str(jar),
        *[str(p) for p in staged],
        "--output-dir", str(out_dir),
        "--format", "json,markdown",
        "--image-output", "off",
        "--threads", str(max(1, int(config.threads))),
    ]


def run_cli(staged: list[Path], out_dir: Path, *, jar: Path, config: AdapterConfig, java_tmp: Path) -> subprocess.CompletedProcess:
    """Run one JVM over all staged files. Raises OpenDataLoaderError on timeout/launch failure."""
    cmd = build_command(staged, out_dir, jar=jar, config=config, java_tmp=java_tmp)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=config.timeout_seconds, check=False, shell=False)
    except subprocess.TimeoutExpired:
        raise OpenDataLoaderError(OpenDataLoaderError.TIMEOUT, f"解析超时（{config.timeout_seconds:g}s），JVM 已终止。") from None
    except FileNotFoundError:
        raise OpenDataLoaderError(OpenDataLoaderError.JAVA_NOT_FOUND, f"找不到 Java（{config.java_bin}）。") from None


def parse_pdfs(pdf_paths: list[str], output_dir: str | None = None, *, config: AdapterConfig | None = None) -> list[dict]:
    """Parse several PDFs in a single JVM. Returns one envelope per input, in order.

    Never raises for expected failures: each envelope carries ``error``.
    """
    config = config or AdapterConfig()
    version = package_version()
    results: list[dict | None] = [None] * len(pdf_paths)

    try:
        dest = resolve_output_dir(output_dir, config.allowed_output_roots) if output_dir is not None else None
    except OpenDataLoaderError as exc:
        return [_empty_envelope(str(exc), version) for _ in pdf_paths]

    valid: list[tuple[int, Path]] = []
    for i, raw in enumerate(pdf_paths):
        try:
            valid.append((i, _check_input(raw)))
        except OpenDataLoaderError as exc:
            results[i] = _empty_envelope(str(exc), version)
    if not valid:
        return [r for r in results if r is not None]

    try:
        jar = locate_jar(config)
        java_version = check_java(config.java_bin)
    except OpenDataLoaderError as exc:
        for i, _ in valid:
            results[i] = _empty_envelope(str(exc), version)
        return [r for r in results if r is not None]

    work = Path(tempfile.mkdtemp(prefix="odl-", dir=config.temp_root))
    try:
        in_dir, out_dir, java_tmp = work / "in", work / "out", work / "jtmp"
        for d in (in_dir, out_dir, java_tmp):
            d.mkdir()
        staged: list[Path] = []
        # Safe, unique names: avoid basename collisions and option-like file names.
        for n, (_, src) in enumerate(valid, start=1):
            link = in_dir / f"f{n:04d}.pdf"
            try:
                link.symlink_to(src)
            except OSError:
                shutil.copyfile(src, link)
            staged.append(link)

        started = time.monotonic()
        with _semaphore(config.max_concurrent):
            try:
                proc = run_cli(staged, out_dir, jar=jar, config=config, java_tmp=java_tmp)
            except OpenDataLoaderError as exc:
                for i, _ in valid:
                    results[i] = _empty_envelope(str(exc), version, {"java": java_version})
                return [r for r in results if r is not None]
        elapsed_ms = int((time.monotonic() - started) * 1000)
        errors_by_name = {m.group("name"): m.group("reason").strip() for m in _ERROR_LINE.finditer((proc.stdout or "") + "\n" + (proc.stderr or ""))}
        warnings = _cli_warnings(proc.stderr or "")
        logger.info("opendataloader batch files=%d exit=%d elapsed_ms=%d", len(staged), proc.returncode, elapsed_ms)

        for (i, src), link in zip(valid, staged):
            json_path = out_dir / f"{link.stem}.json"
            md_path = out_dir / f"{link.stem}.md"
            if not json_path.is_file():
                reason = errors_by_name.get(link.name)
                detail = f"'{src.name}' {reason}" if reason else f"解析器退出码 {proc.returncode}，未生成结果。"
                results[i] = _empty_envelope(f"{OpenDataLoaderError.CLI_FAILED}: {detail}", version, {"java": java_version})
                continue
            try:
                envelope = build_envelope(
                    json.loads(json_path.read_text(encoding="utf-8")),
                    md_path.read_text(encoding="utf-8") if md_path.is_file() else "",
                    version=version, cli_warnings=warnings.get(link.name, []), elapsed_ms=elapsed_ms,
                )
            except (ValueError, OpenDataLoaderError) as exc:
                results[i] = _empty_envelope(f"{OpenDataLoaderError.OUTPUT_INVALID}: {exc}", version, {"java": java_version})
                continue
            envelope["metadata"].update({"java": java_version, "source_file": src.name, "batch_size": len(staged)})
            if not md_path.is_file():
                envelope["warnings"].append("未生成 Markdown 输出。")
            if dest is not None:
                dest.mkdir(parents=True, exist_ok=True)
                stem = f"{src.stem}.{i}" if sum(1 for _, s in valid if s.stem == src.stem) > 1 else src.stem
                shutil.copyfile(json_path, dest / f"{stem}.json")
                if md_path.is_file():
                    shutil.copyfile(md_path, dest / f"{stem}.md")
                envelope["metadata"]["output_files"] = [str(dest / f"{stem}.json")] + ([str(dest / f"{stem}.md")] if md_path.is_file() else [])
            results[i] = envelope
        return [r for r in results if r is not None]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def parse_pdf(pdf_path: str, output_dir: str | None = None, *, config: AdapterConfig | None = None) -> dict:
    """Parse one PDF. Blocking: use :func:`parse_pdf_async` from async code."""
    return parse_pdfs([pdf_path], output_dir, config=config)[0]


async def parse_pdf_async(pdf_path: str, output_dir: str | None = None, *, config: AdapterConfig | None = None) -> dict:
    return await asyncio.to_thread(parse_pdf, pdf_path, output_dir, config=config)


async def parse_pdfs_async(pdf_paths: list[str], output_dir: str | None = None, *, config: AdapterConfig | None = None) -> list[dict]:
    return await asyncio.to_thread(parse_pdfs, pdf_paths, output_dir, config=config)


# ---------------------------------------------------------------- explicit opt-in

def selected_engine() -> str:
    """config.yaml ``pdf_parser.engine``; anything other than "opendataloader" means legacy."""
    try:
        from app.config import get_config

        engine = str(((get_config() or {}).get("pdf_parser") or {}).get("engine") or "legacy")
    except Exception:
        engine = "legacy"
    return "opendataloader" if engine.strip().lower() == "opendataloader" else "legacy"


def extract_pdf_with_engine(
    pdf_path: str,
    task_id: str | None = None,
    *,
    engine: str | None = None,
    legacy_extract: Callable | None = None,
    config: AdapterConfig | None = None,
) -> tuple[str, dict[str, Any], list[int]]:
    """Same return shape as file_parse_service._extract_pdf.

    Default (engine unset and no config) is the legacy chain, called unchanged.
    With engine="opendataloader" the adapter is tried first; on any failure the
    legacy chain runs exactly as it would have without the adapter.
    """
    if legacy_extract is None:
        from app.services.file_parse_service import _extract_pdf as legacy_extract  # noqa: N813

    chosen = (engine or selected_engine()).strip().lower()
    if chosen != "opendataloader":
        return legacy_extract(pdf_path, task_id=task_id)

    try:
        envelope = parse_pdf(pdf_path, config=config)
    except Exception as exc:  # adapter bug: never break the legacy chain
        logger.warning("opendataloader adapter crashed, using legacy chain: %s", type(exc).__name__)
        envelope = {"success": False, "error": f"ADAPTER_CRASH: {type(exc).__name__}"}
    if not envelope.get("success"):
        logger.warning("opendataloader failed (%s), using legacy chain", envelope.get("error"))
        return legacy_extract(pdf_path, task_id=task_id)
    metadata = {
        "source": "opendataloader_pdf",
        "page_count": envelope["page_count"],
        "parser": envelope["metadata"],
        "warnings": envelope["warnings"],
        "pages": envelope["pages"],
    }
    return envelope["markdown"], metadata, []
