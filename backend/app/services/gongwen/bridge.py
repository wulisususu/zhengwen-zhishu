"""Call the fixed Node bridge (node/render_notice.js) to render a component spec."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.services.gongwen import catalog
from app.services.gongwen.runner import GongwenToolError, require_kit, run_node
from app.services.gongwen.settings import BRIDGE_SCRIPT, GongwenSettings

logger = logging.getLogger("app.gongwen")


def render_docx(spec: dict, out_path: Path, settings: GongwenSettings) -> dict:
    """Render `spec` to `out_path`. Returns {bytes, toolVersion, seconds}; raises GongwenToolError."""
    kit = require_kit(settings)
    out_path = Path(out_path).resolve()   # node runs with cwd=out_path.parent
    payload = json.dumps(spec, ensure_ascii=False).encode("utf-8")
    run = run_node(settings, [str(BRIDGE_SCRIPT), "--kit", str(kit), "--out", str(out_path)],
                   timeout=settings.render_timeout_seconds, cwd=out_path.parent, stdin=payload)
    lines = [ln for ln in run.stdout.splitlines() if ln.strip()]
    try:
        reply = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError:
        reply = None
    if not isinstance(reply, dict) or "ok" not in reply:
        raise GongwenToolError(catalog.TOOL_BAD_OUTPUT, "公文生成桥输出不是约定的 JSON", run.stderr[-300:])
    if reply["ok"] is True and run.returncode == 0 and out_path.is_file():
        logger.info("gongwen render components=%s bytes=%s seconds=%.3f",
                    reply.get("components"), reply.get("bytes"), run.seconds)
        return {"bytes": reply.get("bytes"), "toolVersion": reply.get("toolVersion"), "seconds": round(run.seconds, 3)}
    if run.returncode == 3:
        raise GongwenToolError(catalog.TOOL_RENDER_REJECTED, str(reply.get("message") or "生成参数被拒绝"))
    raise GongwenToolError(catalog.TOOL_RENDER_FAILED, str(reply.get("message") or "公文生成失败"), run.stderr[-300:])
