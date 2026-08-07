from __future__ import annotations

from typing import Any


WORKFLOW_STATES = {
    "received",
    "prepared",
    "submitted_to_openclaw",
    "tool_running",
    "validated",
    "completed",
    "repair_required",
}


CHAT_WORKFLOW_SCHEMA = {
    "conversation_id": {"type": "integer", "required": True, "minimum": 1},
    "message": {"type": "string", "required": True, "min_length": 1},
    "attachments": {"type": "array", "required": False, "items": "integer"},
    "history": {"type": "array", "required": False, "items": "message"},
    "attachment_context": {"type": "string", "required": False},
}

KNOWLEDGE_WORKFLOW_SCHEMA = {
    "conversation_id": {"type": "integer", "required": True, "minimum": 1},
    "message": {"type": "string", "required": True, "min_length": 1},
    "history": {"type": "array", "required": False, "items": "message"},
    "expected_grounding": {"type": "boolean", "required": True},
}

DOCUMENT_WORKFLOW_SCHEMA = {
    "conversation_id": {"type": "integer", "required": True, "minimum": 1},
    "user_id": {"type": "integer", "required": True, "minimum": 1},
    "message": {"type": "string", "required": True, "min_length": 1},
    "attachments": {"type": "array", "required": False, "items": "integer"},
    "attachment_context": {"type": "string", "required": False},
}

TTS_WORKFLOW_SCHEMA = {
    "conversation_id": {"type": "integer", "required": True, "minimum": 1},
    "message_id": {"type": "integer", "required": True, "minimum": 1},
    "text": {"type": "string", "required": True, "min_length": 1},
}

ASR_WORKFLOW_SCHEMA = {
    "conversation_id": {"type": "integer", "required": True, "minimum": 1},
    "message_id": {"type": "integer", "required": True, "minimum": 1},
    "file_id": {"type": "integer", "required": True, "minimum": 1},
    "response_kind": {"type": "string", "required": True, "min_length": 1},
}


def normalize_workflow_status(status: str) -> str:
    normalized = str(status or "").strip()
    if normalized not in WORKFLOW_STATES:
        raise ValueError(f"unknown workflow status: {status}")
    return normalized


def _base_result(
    *,
    status: str,
    previous_step_hint: str,
    validated_payload: dict[str, Any],
    frontend_events: list[str],
    metric_key: str,
) -> dict[str, Any]:
    normalized_status = normalize_workflow_status(status)
    metric_value = 1.0 if normalized_status == "completed" else 0.0
    return {
        "status": normalized_status,
        "previous_step_hint": previous_step_hint,
        "validated_payload": validated_payload,
        "frontend_events": frontend_events,
        "evaluation_snapshot": {
            metric_key: metric_value,
            "result_shape_valid_rate": metric_value,
            "output_format_valid_rate": metric_value,
            "mcp_success_rate": metric_value,
        },
    }


def validate_chat_completion(*, text: str, done_seen: bool) -> dict[str, Any]:
    answer_text = str(text or "").strip()
    if not answer_text:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair the OpenClaw answer text before completing chat.",
            validated_payload={"text": "", "done_seen": bool(done_seen)},
            frontend_events=["token"],
            metric_key="tool_call_compliance_rate",
        )
    if not done_seen:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair the SSE completion so the chat route emits done.",
            validated_payload={"text": answer_text, "done_seen": False},
            frontend_events=["token"],
            metric_key="tool_call_compliance_rate",
        )
    return _base_result(
        status="completed",
        previous_step_hint="",
        validated_payload={"text": answer_text, "done_seen": True},
        frontend_events=["token", "done"],
        metric_key="tool_call_compliance_rate",
    )


def validate_knowledge_completion(
    *,
    text: str,
    grounding: dict[str, Any] | None,
    done_seen: bool,
    expected_grounding: bool,
) -> dict[str, Any]:
    answer_text = str(text or "").strip()
    grounding = grounding or {}
    grounded = bool(grounding.get("grounded"))
    source_count = int(grounding.get("source_count") or 0)
    sources = grounding.get("sources") or []
    if not answer_text:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair the OpenClaw knowledge answer text before completing the route.",
            validated_payload={"text": "", "grounding": grounding, "done_seen": bool(done_seen)},
            frontend_events=["grounding"],
            metric_key="tool_call_compliance_rate",
        )
    if not done_seen:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair the SSE completion so the knowledge route emits done.",
            validated_payload={"text": answer_text, "grounding": grounding, "done_seen": False},
            frontend_events=["token", "grounding"],
            metric_key="tool_call_compliance_rate",
        )
    if expected_grounding and (not grounded or source_count != len(sources) or source_count <= 0):
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step, rerun kb_search, and repair the grounding payload before completing the knowledge route.",
            validated_payload={"text": answer_text, "grounding": grounding, "done_seen": True},
            frontend_events=["token", "grounding"],
            metric_key="tool_call_compliance_rate",
        )
    return _base_result(
        status="completed",
        previous_step_hint="",
        validated_payload={
            "text": answer_text,
            "grounding": {
                "grounded": grounded,
                "source_count": source_count,
                "sources": sources,
            },
            "done_seen": True,
        },
        frontend_events=["token", "grounding", "done"],
        metric_key="tool_call_compliance_rate",
    )


def validate_document_completion(
    *,
    text: str,
    task: dict[str, Any] | None,
    done_seen: bool,
    requires_task: bool,
) -> dict[str, Any]:
    answer_text = str(text or "").strip()
    task = task or None
    if not done_seen:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair the SSE completion so the document route emits done.",
            validated_payload={"text": answer_text, "task": task, "done_seen": False},
            frontend_events=["token", "doc_task"],
            metric_key="tool_call_compliance_rate",
        )
    if requires_task:
        task_id = str((task or {}).get("task_id") or "").strip()
        task_status = str((task or {}).get("status") or "").strip()
        if not task_id or not task_status:
            return _base_result(
                status="repair_required",
                previous_step_hint="Return to the previous orchestration step and repair document task creation so a valid task_id and status are present.",
                validated_payload={"text": answer_text, "task": task, "done_seen": True},
                frontend_events=["token"],
                metric_key="tool_call_compliance_rate",
            )
    return _base_result(
        status="completed",
        previous_step_hint="",
        validated_payload={"text": answer_text, "task": task, "done_seen": True},
        frontend_events=["token", "doc_task", "done"] if task else ["token", "done"],
        metric_key="tool_call_compliance_rate",
    )


def validate_tts_completion(
    *,
    task_id: str,
    audio_url: str,
    mime_type: str,
    done_seen: bool,
    chunk_seen: bool,
) -> dict[str, Any]:
    normalized_task_id = str(task_id or "").strip()
    normalized_audio_url = str(audio_url or "").strip()
    normalized_mime_type = str(mime_type or "").strip()
    payload = {
        "capability": "tts",
        "task_id": normalized_task_id,
        "audio_url": normalized_audio_url,
        "mime_type": normalized_mime_type,
        "done_seen": bool(done_seen),
        "chunk_seen": bool(chunk_seen),
    }
    if not normalized_task_id:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair TTS task creation before retrying the voice stream.",
            validated_payload=payload,
            frontend_events=["audio_start"],
            metric_key="tool_call_compliance_rate",
        )
    if not normalized_audio_url or not normalized_mime_type.startswith("audio/"):
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair the synthesized audio payload before emitting audio_done.",
            validated_payload=payload,
            frontend_events=["audio_start"],
            metric_key="tool_call_compliance_rate",
        )
    if not done_seen:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair the voice SSE completion so the route emits audio_done.",
            validated_payload=payload,
            frontend_events=["audio_start"],
            metric_key="tool_call_compliance_rate",
        )
    return _base_result(
        status="completed",
        previous_step_hint="",
        validated_payload=payload,
        frontend_events=["audio_start", "audio_done", "done"],
        metric_key="tool_call_compliance_rate",
    )


def validate_asr_completion(
    *,
    task_id: str,
    transcript: str,
    mode: str,
    backend: str,
    done_seen: bool,
    chunk_seen: bool,
) -> dict[str, Any]:
    normalized_task_id = str(task_id or "").strip()
    normalized_transcript = str(transcript or "").strip()
    normalized_mode = str(mode or "").strip()
    normalized_backend = str(backend or "").strip()
    payload = {
        "capability": "asr",
        "task_id": normalized_task_id,
        "transcript": normalized_transcript,
        "mode": normalized_mode,
        "backend": normalized_backend,
        "done_seen": bool(done_seen),
        "chunk_seen": bool(chunk_seen),
    }
    if not normalized_task_id:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair ASR task creation before retrying the voice stream.",
            validated_payload=payload,
            frontend_events=["audio_start"],
            metric_key="tool_call_compliance_rate",
        )
    if not normalized_transcript:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair the ASR transcript before emitting audio_done.",
            validated_payload=payload,
            frontend_events=["audio_start"],
            metric_key="tool_call_compliance_rate",
        )
    if not normalized_mode or not normalized_backend:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair the ASR mode/backend metadata before emitting audio_done.",
            validated_payload=payload,
            frontend_events=["audio_start"],
            metric_key="tool_call_compliance_rate",
        )
    if not done_seen:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair the voice SSE completion so the route emits audio_done.",
            validated_payload=payload,
            frontend_events=["audio_start"],
            metric_key="tool_call_compliance_rate",
        )
    return _base_result(
        status="completed",
        previous_step_hint="",
        validated_payload=payload,
        frontend_events=["audio_start", "audio_done", "done"],
        metric_key="tool_call_compliance_rate",
    )


def _validate_voice_revision(*, revision_id: int, previous_revision_id: int | None) -> str:
    try:
        normalized_revision_id = int(revision_id)
    except Exception:
        return "revision_id must be an integer"
    if normalized_revision_id <= 0:
        return "revision_id must be positive"
    if previous_revision_id is not None and normalized_revision_id <= int(previous_revision_id):
        return "revision_id must be newer than the previous revision_id"
    return ""


def validate_asr_stream_chunk(
    *,
    task_id: str,
    revision_id: int,
    text: str,
    is_final: bool,
    previous_revision_id: int | None = None,
) -> dict[str, Any]:
    payload = {
        "capability": "asr",
        "stage": "raw_asr",
        "task_id": str(task_id or "").strip(),
        "revision_id": revision_id,
        "text": str(text or "").strip(),
        "is_final": bool(is_final),
    }
    if not payload["task_id"]:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair task_id before emitting raw_asr audio_chunk.",
            validated_payload=payload,
            frontend_events=["audio_chunk"],
            metric_key="tool_call_compliance_rate",
        )
    revision_error = _validate_voice_revision(revision_id=revision_id, previous_revision_id=previous_revision_id)
    if revision_error:
        return _base_result(
            status="repair_required",
            previous_step_hint=f"Return to the previous orchestration step and repair revision_id before emitting raw_asr audio_chunk: {revision_error}.",
            validated_payload=payload,
            frontend_events=["audio_chunk"],
            metric_key="tool_call_compliance_rate",
        )
    if not payload["text"]:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair raw_asr text before emitting audio_chunk.",
            validated_payload=payload,
            frontend_events=["audio_chunk"],
            metric_key="tool_call_compliance_rate",
        )
    return _base_result(
        status="completed",
        previous_step_hint="",
        validated_payload=payload,
        frontend_events=["audio_chunk"],
        metric_key="tool_call_compliance_rate",
    )


def validate_partial_fix(
    *,
    task_id: str,
    revision_id: int,
    text: str,
    source_revision_id: int,
    previous_revision_id: int | None = None,
) -> dict[str, Any]:
    payload = {
        "capability": "asr",
        "stage": "partial_fix",
        "task_id": str(task_id or "").strip(),
        "revision_id": revision_id,
        "source_revision_id": source_revision_id,
        "text": str(text or "").strip(),
        "is_final": False,
    }
    revision_error = _validate_voice_revision(revision_id=revision_id, previous_revision_id=previous_revision_id)
    if not payload["task_id"] or revision_error:
        hint = "task_id is required" if not payload["task_id"] else revision_error
        return _base_result(
            status="repair_required",
            previous_step_hint=f"Return to the previous orchestration step and repair partial_fix metadata before emitting audio_chunk: {hint}.",
            validated_payload=payload,
            frontend_events=["audio_chunk"],
            metric_key="tool_call_compliance_rate",
        )
    try:
        normalized_source_revision = int(source_revision_id)
    except Exception:
        normalized_source_revision = 0
    if normalized_source_revision <= 0:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair source_revision_id before emitting partial_fix audio_chunk.",
            validated_payload=payload,
            frontend_events=["audio_chunk"],
            metric_key="tool_call_compliance_rate",
        )
    if not payload["text"]:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair partial_fix text before emitting audio_chunk.",
            validated_payload=payload,
            frontend_events=["audio_chunk"],
            metric_key="tool_call_compliance_rate",
        )
    return _base_result(
        status="completed",
        previous_step_hint="",
        validated_payload=payload,
        frontend_events=["audio_chunk"],
        metric_key="tool_call_compliance_rate",
    )


def validate_sentence_fix(
    *,
    task_id: str,
    revision_id: int,
    text: str,
    sentence_id: str,
    previous_revision_id: int | None = None,
) -> dict[str, Any]:
    payload = {
        "capability": "asr",
        "stage": "sentence_fix",
        "task_id": str(task_id or "").strip(),
        "revision_id": revision_id,
        "sentence_id": str(sentence_id or "").strip(),
        "text": str(text or "").strip(),
        "is_final": True,
    }
    revision_error = _validate_voice_revision(revision_id=revision_id, previous_revision_id=previous_revision_id)
    if not payload["task_id"] or revision_error:
        hint = "task_id is required" if not payload["task_id"] else revision_error
        return _base_result(
            status="repair_required",
            previous_step_hint=f"Return to the previous orchestration step and repair sentence_fix metadata before emitting audio_chunk: {hint}.",
            validated_payload=payload,
            frontend_events=["audio_chunk"],
            metric_key="tool_call_compliance_rate",
        )
    if not payload["sentence_id"]:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair sentence_id before emitting sentence_fix audio_chunk.",
            validated_payload=payload,
            frontend_events=["audio_chunk"],
            metric_key="tool_call_compliance_rate",
        )
    if not payload["text"]:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair sentence_fix text before emitting audio_chunk.",
            validated_payload=payload,
            frontend_events=["audio_chunk"],
            metric_key="tool_call_compliance_rate",
        )
    return _base_result(
        status="completed",
        previous_step_hint="",
        validated_payload=payload,
        frontend_events=["audio_chunk"],
        metric_key="tool_call_compliance_rate",
    )


def validate_final_polish(
    *,
    task_id: str,
    revision_id: int,
    text: str,
    previous_revision_id: int | None = None,
) -> dict[str, Any]:
    payload = {
        "capability": "asr",
        "stage": "final_polish_preview",
        "task_id": str(task_id or "").strip(),
        "revision_id": revision_id,
        "text": str(text or "").strip(),
        "is_final": False,
    }
    revision_error = _validate_voice_revision(revision_id=revision_id, previous_revision_id=previous_revision_id)
    if not payload["task_id"] or revision_error:
        hint = "task_id is required" if not payload["task_id"] else revision_error
        return _base_result(
            status="repair_required",
            previous_step_hint=f"Return to the previous orchestration step and repair final_polish preview metadata before emitting audio_chunk: {hint}.",
            validated_payload=payload,
            frontend_events=["audio_chunk"],
            metric_key="tool_call_compliance_rate",
        )
    if not payload["text"]:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair final_polish preview text before emitting audio_chunk.",
            validated_payload=payload,
            frontend_events=["audio_chunk"],
            metric_key="tool_call_compliance_rate",
        )
    return _base_result(
        status="completed",
        previous_step_hint="",
        validated_payload=payload,
        frontend_events=["audio_chunk"],
        metric_key="tool_call_compliance_rate",
    )


def validate_voice_input_completion(
    *,
    task_id: str,
    transcript: str,
    raw_transcript: str,
    mode: str,
    backend: str,
    stages: list[str],
    latency_ms: dict[str, Any],
    revision_id: int,
    done_seen: bool,
) -> dict[str, Any]:
    payload = {
        "capability": "asr",
        "task_id": str(task_id or "").strip(),
        "transcript": str(transcript or "").strip(),
        "raw_transcript": str(raw_transcript or "").strip(),
        "mode": str(mode or "").strip(),
        "backend": str(backend or "").strip(),
        "stages": list(stages or []),
        "latency_ms": latency_ms if isinstance(latency_ms, dict) else {},
        "revision_id": revision_id,
        "done_seen": bool(done_seen),
    }
    revision_error = _validate_voice_revision(revision_id=revision_id, previous_revision_id=None)
    if not payload["task_id"] or revision_error:
        hint = "task_id is required" if not payload["task_id"] else revision_error
        return _base_result(
            status="repair_required",
            previous_step_hint=f"Return to the previous orchestration step and repair voice input completion metadata before emitting audio_done: {hint}.",
            validated_payload=payload,
            frontend_events=["audio_done"],
            metric_key="tool_call_compliance_rate",
        )
    if not payload["transcript"]:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair transcript before emitting audio_done.",
            validated_payload=payload,
            frontend_events=["audio_done"],
            metric_key="tool_call_compliance_rate",
        )
    if not payload["raw_transcript"]:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair raw_transcript before emitting audio_done.",
            validated_payload=payload,
            frontend_events=["audio_done"],
            metric_key="tool_call_compliance_rate",
        )
    if not payload["mode"] or not payload["backend"]:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair mode/backend before emitting audio_done.",
            validated_payload=payload,
            frontend_events=["audio_done"],
            metric_key="tool_call_compliance_rate",
        )
    if not payload["stages"] or not payload["latency_ms"]:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair stages/latency_ms before emitting audio_done.",
            validated_payload=payload,
            frontend_events=["audio_done"],
            metric_key="tool_call_compliance_rate",
        )
    if not payload["done_seen"]:
        return _base_result(
            status="repair_required",
            previous_step_hint="Return to the previous orchestration step and repair the SSE completion so the route emits audio_done and done.",
            validated_payload=payload,
            frontend_events=["audio_done"],
            metric_key="tool_call_compliance_rate",
        )
    return _base_result(
        status="completed",
        previous_step_hint="",
        validated_payload=payload,
        frontend_events=["audio_done", "done"],
        metric_key="tool_call_compliance_rate",
    )
