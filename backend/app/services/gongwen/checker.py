"""gongwen-kit `check --json` adapter.

Every hit is parsed and returned; the exit code alone is never trusted. The
report is accepted only when exit code, status, the blocking count, the hits and
the document sha256 all agree (S1: exit 0 still happens with hint-level hits,
status is "hit" only for blocking hits). Anything else is a tool error, and a
tool error is never reported as a pass.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.services.gongwen import catalog
from app.services.gongwen.runner import GongwenToolError, require_kit, run_node
from app.services.gongwen.settings import GongwenSettings, load_settings

logger = logging.getLogger("app.gongwen")

_EXIT_BY_STATUS = {"pass": 0, "hit": 1}


@dataclass
class KitHit:
    check: str
    rule: str
    detail: str
    blocking: bool
    anchors: list = field(default_factory=list)   # str or {"text": str, "table": int}


def validate_docx_path(path: Path) -> Path:
    path = Path(path).resolve()   # node runs with cwd=path.parent
    if path.suffix.lower() != ".docx" or not path.is_file():
        raise GongwenToolError(catalog.TOOL_INVALID_INPUT, "只接受存在的 .docx 文件")
    with path.open("rb") as fh:
        if fh.read(4) != b"PK\x03\x04":
            raise GongwenToolError(catalog.TOOL_INVALID_INPUT, "文件不是 DOCX（ZIP）格式")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_report(stdout: str, exit_code: int, expected_sha256: str | None = None) -> tuple[dict, list[KitHit]]:
    """Validate the documented JSON and return (report, hits). Raises GongwenToolError."""
    try:
        report = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        raise GongwenToolError(catalog.TOOL_BAD_OUTPUT, "格式工具输出不是 JSON", stdout[-300:])
    if not isinstance(report, dict) or report.get("status") not in ("pass", "hit", "fault"):
        raise GongwenToolError(catalog.TOOL_BAD_OUTPUT, "格式工具输出缺少 status")
    if report["status"] == "fault" or exit_code == 2:
        raise GongwenToolError(catalog.TOOL_FAULT, "格式工具运行失败：" + str(report.get("message") or "未给出原因")[:300])
    if _EXIT_BY_STATUS[report["status"]] != exit_code:
        raise GongwenToolError(catalog.TOOL_INCONSISTENT,
                               f"格式工具退出码 {exit_code} 与 status={report['status']} 不一致")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        raise GongwenToolError(catalog.TOOL_BAD_OUTPUT, "格式工具输出缺少 checks")
    hits: list[KitHit] = []
    for chk in checks:
        if not isinstance(chk, dict) or not isinstance(chk.get("hits"), list):
            raise GongwenToolError(catalog.TOOL_BAD_OUTPUT, "格式工具 checks 结构不对")
        for hit in chk["hits"]:
            if not (isinstance(hit, dict) and isinstance(hit.get("rule"), str)
                    and isinstance(hit.get("detail"), str) and isinstance(hit.get("blocking"), bool)):
                raise GongwenToolError(catalog.TOOL_BAD_OUTPUT, "格式工具命中项结构不对")
            anchors = hit.get("anchors") or []
            if not isinstance(anchors, list):
                anchors = []
            hits.append(KitHit(str(chk.get("check") or ""), hit["rule"], hit["detail"], hit["blocking"], anchors))
    blocking = sum(1 for h in hits if h.blocking)
    if report.get("blocking") != blocking or (report["status"] == "hit") != (blocking > 0):
        raise GongwenToolError(catalog.TOOL_INCONSISTENT, "格式工具汇总数与逐条命中不一致")
    if expected_sha256 and report.get("sha256") != expected_sha256:
        raise GongwenToolError(catalog.TOOL_INCONSISTENT, "格式工具检查的文件与提交的文件不一致")
    return report, hits


def check_docx(path: str | Path, settings: GongwenSettings | None = None, timeout: float | None = None) -> dict:
    """Run `gongwen check --json`. Never raises; never reports success on a tool failure.

    Returns {success, exit_code, status, hits[], tool_version, sha256, seconds, raw, error}.
    """
    settings = settings or load_settings()
    result = {"success": False, "exit_code": None, "status": None, "hits": [], "tool_version": None,
              "sha256": None, "seconds": None, "raw": None, "error": None}
    try:
        path = validate_docx_path(Path(path))
        kit = require_kit(settings)
        sha = _sha256(path)
        run = run_node(settings, [str(kit / "bin" / "gongwen.js"), "check", str(path), "--json"],
                       timeout=timeout or settings.check_timeout_seconds, cwd=path.parent)
        result.update(exit_code=run.returncode, seconds=round(run.seconds, 3))
        report, hits = parse_report(run.stdout, run.returncode, sha)
        if _sha256(path) != sha:   # the checker must never modify its input
            raise GongwenToolError(catalog.TOOL_INCONSISTENT, "格式检查后文件内容发生变化")
        result.update(success=True, status=report["status"], hits=[asdict(h) for h in hits],
                      tool_version=report.get("toolVersion"), sha256=sha, raw=report)
        logger.info("gongwen check file=%s bytes=%d seconds=%.3f status=%s hits=%d blocking=%d",
                    path.name, path.stat().st_size, run.seconds, report["status"], len(hits),
                    report.get("blocking", 0))
    except GongwenToolError as exc:
        result["error"] = exc.to_dict()
        logger.warning("gongwen check failed code=%s", exc.code)
    return result
