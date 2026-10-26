"""Optional layout fix for external Word files: copy in, copy out, original untouched.

`gongwen fix` writes a separate output file and refuses to overwrite its input.
We additionally run it on a private copy and verify the copy's hash is unchanged
afterwards. A passing check after fix is NOT a compliance claim
(catalog.COMPLIANCE_NOTE_FIX; S1 retest: title, levels, lists, tables, 落款,
版头 and 版记 are not fixed).
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.services.gongwen import catalog
from app.services.gongwen.checker import validate_docx_path
from app.services.gongwen.runner import GongwenToolError, require_kit, run_node
from app.services.gongwen.settings import GongwenSettings

logger = logging.getLogger("app.gongwen")


def fix_copy(src: Path, out: Path, settings: GongwenSettings) -> dict:
    """Fix `src` into `out` (must differ). Returns {report, seconds, srcSha256}; raises GongwenToolError."""
    src, out = validate_docx_path(Path(src)), Path(out).resolve()
    if src.resolve() == out.resolve() or out.suffix.lower() != ".docx":
        raise GongwenToolError(catalog.TOOL_INVALID_INPUT, "修复输出必须是另一个 .docx 文件")
    kit = require_kit(settings)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    run = run_node(settings, [str(kit / "bin" / "gongwen.js"), "fix", str(src), "--out", str(out)],
                   timeout=settings.fix_timeout_seconds, cwd=src.parent)
    if hashlib.sha256(src.read_bytes()).hexdigest() != before:
        raise GongwenToolError(catalog.TOOL_INCONSISTENT, "修复过程改动了输入文件")
    if run.returncode != 0 or not out.is_file():
        raise GongwenToolError(catalog.TOOL_FIX_FAILED, "版式修复失败", run.stderr[-300:])
    logger.info("gongwen fix bytes_in=%d bytes_out=%d seconds=%.3f", src.stat().st_size, out.stat().st_size, run.seconds)
    return {"report": run.stdout.strip(), "seconds": round(run.seconds, 3), "srcSha256": before}
