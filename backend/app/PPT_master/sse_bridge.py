"""SSE bridge: graph events to SSE protocol."""
import json
import logging

logger = logging.getLogger(__name__)


def make_sse_event(event_type: str, data: dict) -> str:
    """Format a single SSE event string."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"
