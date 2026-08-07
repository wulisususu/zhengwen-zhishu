"""SSE bridge — graph events → SSE protocol."""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def make_sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format a single SSE event string."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


def extract_done_event(state: dict, download_url: str = "") -> dict:
    """从 state 提取 done SSE 数据."""
    has_fallback = any(
        ch.get("fallback", False)
        for ch in state.get("generated_chapters", [])
    )
    return {
        "download_url": download_url,
        "filename": state.get("polished_title", "document") + ".docx",
        "size": state.get("docx_size", 0),
        "has_fallback": has_fallback,
    }
