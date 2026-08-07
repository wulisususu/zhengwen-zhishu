from __future__ import annotations

import time
from threading import Lock
from typing import Any


_TTL_SECONDS = 1800.0
_TTS_ARTIFACTS: dict[str, dict[str, Any]] = {}
_LOCK = Lock()


def _cleanup_locked(now_ts: float) -> None:
    expired = [
        task_id
        for task_id, payload in _TTS_ARTIFACTS.items()
        if now_ts - float(payload.get("created_at") or 0.0) > _TTL_SECONDS
    ]
    for task_id in expired:
        _TTS_ARTIFACTS.pop(task_id, None)


def store_tts_artifact(task_id: str, audio_bytes: bytes, mime_type: str = "audio/wav") -> dict[str, Any]:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        raise ValueError("task_id is required")
    payload = {
        "task_id": normalized_task_id,
        "audio_bytes": bytes(audio_bytes or b""),
        "mime_type": str(mime_type or "").strip() or "audio/wav",
        "created_at": time.time(),
    }
    with _LOCK:
        _cleanup_locked(payload["created_at"])
        _TTS_ARTIFACTS[normalized_task_id] = payload
    return {
        "task_id": normalized_task_id,
        "audio_bytes": len(payload["audio_bytes"]),
        "mime_type": payload["mime_type"],
    }


def get_tts_artifact(task_id: str) -> dict[str, Any] | None:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return None
    with _LOCK:
        now_ts = time.time()
        _cleanup_locked(now_ts)
        payload = _TTS_ARTIFACTS.get(normalized_task_id)
        if not payload:
            return None
        return {
            "task_id": normalized_task_id,
            "audio_bytes": payload["audio_bytes"],
            "mime_type": payload["mime_type"],
            "created_at": payload["created_at"],
        }
