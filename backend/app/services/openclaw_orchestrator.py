from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.services.local_small_model import generate as local_small_generate

from app.services.openclaw_contracts import (
    validate_asr_completion,
    validate_chat_completion,
    validate_document_completion,
    validate_knowledge_completion,
    validate_tts_completion,
)
from app.services.openclaw_gateway import (
    build_chat_input,
    build_knowledge_input,
    collect_openclaw_done_flag,
    collect_openclaw_text_fragments,
    extract_kb_grounding_payload,
    get_openclaw_chat_runtime,
    get_openclaw_knowledge_runtime,
    iter_openclaw_agent_events,
    load_kb_trace_call_ids,
    normalize_grounding_payload,
    wait_for_kb_grounding_from_trace,
)


def _override_previous_step_hint(result: dict[str, Any], previous_step_hint: str) -> dict[str, Any]:
    if result.get("status") == "repair_required" and str(previous_step_hint or "").strip():
        updated = dict(result)
        updated["previous_step_hint"] = str(previous_step_hint).strip()
        return updated
    return result


def build_chat_orchestration_result(
    *,
    text: str,
    done_seen: bool,
    previous_step_hint: str,
) -> dict[str, Any]:
    result = validate_chat_completion(text=text, done_seen=done_seen)
    result = _override_previous_step_hint(result, previous_step_hint)
    return {
        "workflow": "chat",
        **result,
    }


def build_knowledge_orchestration_result(
    *,
    text: str,
    grounding: dict[str, Any] | None,
    done_seen: bool,
    expected_grounding: bool,
    previous_step_hint: str,
) -> dict[str, Any]:
    result = validate_knowledge_completion(
        text=text,
        grounding=grounding,
        done_seen=done_seen,
        expected_grounding=expected_grounding,
    )
    result = _override_previous_step_hint(result, previous_step_hint)
    return {
        "workflow": "knowledge",
        **result,
    }


def build_document_orchestration_result(
    *,
    text: str,
    task: dict[str, Any] | None,
    done_seen: bool,
    requires_task: bool,
    previous_step_hint: str,
) -> dict[str, Any]:
    result = validate_document_completion(
        text=text,
        task=task,
        done_seen=done_seen,
        requires_task=requires_task,
    )
    result = _override_previous_step_hint(result, previous_step_hint)
    return {
        "workflow": "document",
        **result,
    }


def build_tts_orchestration_result(
    *,
    task_id: str,
    audio_url: str,
    mime_type: str,
    done_seen: bool,
    chunk_seen: bool,
    previous_step_hint: str,
) -> dict[str, Any]:
    result = validate_tts_completion(
        task_id=task_id,
        audio_url=audio_url,
        mime_type=mime_type,
        done_seen=done_seen,
        chunk_seen=chunk_seen,
    )
    result = _override_previous_step_hint(result, previous_step_hint)
    return {
        "workflow": "tts",
        **result,
    }


def build_asr_orchestration_result(
    *,
    task_id: str,
    transcript: str,
    mode: str,
    backend: str,
    done_seen: bool,
    chunk_seen: bool,
    previous_step_hint: str,
) -> dict[str, Any]:
    result = validate_asr_completion(
        task_id=task_id,
        transcript=transcript,
        mode=mode,
        backend=backend,
        done_seen=done_seen,
        chunk_seen=chunk_seen,
    )
    result = _override_previous_step_hint(result, previous_step_hint)
    return {
        "workflow": "asr",
        **result,
    }


def orchestrate_chat_reply(
    *,
    content: str,
    history_payload: list[dict[str, str]] | None,
    attachment_context: str,
    conversation_id: int | None = None,
    user_id: int | None = None,
    attachment_ids: list[int] | None = None,
    audio_attachment_ids: list[int] | None = None,
) -> dict[str, Any]:
    runtime = get_openclaw_chat_runtime()
    previous_step_hint = ""
    events: list[dict[str, Any]] = []
    try:
        openclaw_input = build_chat_input(
            content=content,
            history_messages=history_payload or [],
            attachment_context=attachment_context,
            conversation_id=conversation_id,
            user_id=user_id,
            attachment_ids=attachment_ids or [],
            audio_attachment_ids=audio_attachment_ids or [],
        )
        for parsed in iter_openclaw_agent_events(
            model=runtime.get("chat_model", "openclaw"),
            agent_id=runtime.get("chat_agent_id", "main"),
            input_text=openclaw_input,
            timeout_seconds=runtime.get("timeout_seconds", 180),
        ):
            if parsed.get("type") == "[DONE]":
                break
            events.append(parsed)
    except Exception as exc:
        previous_step_hint = f"Return to the previous orchestration step and repair the OpenClaw chat call before retrying: {exc!r}"

    return build_chat_orchestration_result(
        text=collect_openclaw_text_fragments(events),
        done_seen=collect_openclaw_done_flag(events),
        previous_step_hint=previous_step_hint,
    )


def orchestrate_knowledge_reply(
    *,
    content: str,
    history_payload: list[dict[str, str]] | None,
    expected_grounding: bool,
) -> dict[str, Any]:
    runtime = get_openclaw_knowledge_runtime()
    previous_step_hint = ""
    events: list[dict[str, Any]] = []
    grounding: dict[str, Any] | None = None
    known_call_ids = load_kb_trace_call_ids()
    try:
        openclaw_input = build_knowledge_input(
            content=content,
            history_messages=history_payload or [],
        )
        for parsed in iter_openclaw_agent_events(
            model=runtime.get("knowledge_model", "openclaw"),
            agent_id=runtime.get("knowledge_agent_id", "main"),
            input_text=openclaw_input,
            timeout_seconds=runtime.get("timeout_seconds", 180),
        ):
            if parsed.get("type") == "[DONE]":
                break
            events.append(parsed)
            payload_obj = parsed.get("payload") or {}
            grounding_payload = extract_kb_grounding_payload(payload_obj)
            if grounding_payload:
                grounding = normalize_grounding_payload(grounding_payload)
        trace_grounding = wait_for_kb_grounding_from_trace(known_call_ids=known_call_ids)
        if trace_grounding:
            grounding = normalize_grounding_payload(trace_grounding)
    except Exception as exc:
        previous_step_hint = f"Return to the previous orchestration step, rerun kb_search, and repair the OpenClaw knowledge call before retrying: {exc!r}"

    return build_knowledge_orchestration_result(
        text=collect_openclaw_text_fragments(events),
        grounding=grounding,
        done_seen=collect_openclaw_done_flag(events),
        expected_grounding=expected_grounding,
        previous_step_hint=previous_step_hint,
    )


def orchestrate_document_reply(
    *,
    content: str,
    conversation_id: int,
    user_id: int,
    attachment_ids: list[int] | None,
    attachment_context: str,
    task_wait_seconds: float | None = None,
) -> dict[str, Any]:
    """OpenClaw main path: 0.6B summary + OpenClaw document generation.

    OpenClaw docgen agent handles the full pipeline:
    - Content generation via its provider (Qwen 35B)
    - Task creation via backend-bridge generate_document tool
    We add DeepSeek 0.6B summary as a concurrent quick-feedback layer.
    """
    logger = logging.getLogger("app.openclaw_orchestrator")
    runtime = _get_openclaw_document_runtime()
    wait_seconds = float(task_wait_seconds or runtime.get("task_wait_seconds", 45) or 45)
    previous_step_hint = ""
    openclaw_result = None
    timed_out = False
    summary_text = ""

    # Phase 1: concurrent — 0.6B summary + OpenClaw document generation
    with ThreadPoolExecutor(max_workers=2) as pool:
        summary_future = pool.submit(
            local_small_generate, content, mode="intent_normalize"
        )
        body_future = pool.submit(
            _submit_and_wait_openclaw,
            content=content,
            conversation_id=conversation_id,
            user_id=user_id,
            attachment_ids=attachment_ids or [],
            attachment_context=attachment_context,
            wait_seconds=wait_seconds,
        )

        # Collect 0.6B summary (fast, ~1-12s)
        try:
            summary_result = summary_future.result(timeout=15)
            summary_text = str(summary_result.get("text") or "").strip()
            if summary_result.get("fallback"):
                logger.info("0.6B summary fell back: %s", summary_result.get("error"))
        except Exception as exc:
            logger.warning("0.6B summary failed: %s", exc)
            summary_text = ""

        # Collect OpenClaw result (slower, up to wait_seconds)
        try:
            openclaw_result = body_future.result(timeout=wait_seconds + 5)
            previous_step_hint = str((openclaw_result or {}).get("previous_step_hint") or "").strip()
        except TimeoutError:
            timed_out = True
            previous_step_hint = "OpenClaw did not produce a validated task within the wait window."
        except Exception as exc:
            previous_step_hint = f"OpenClaw document call failed: {exc!r}"

    # Extract task from OpenClaw result
    raw_task = (openclaw_result or {}).get("task")
    if not raw_task and openclaw_result:
        raw_task = _extract_task_from_response(openclaw_result, conversation_id)

    # Clean response text
    clean_response_text = str((openclaw_result or {}).get("assistant_text") or "")
    if raw_task and (openclaw_result or {}).get("task") is None:
        _ERR_MARKER = "\n\n中科信创自研模型这一步没有产出有效的文档任务"
        if _ERR_MARKER in clean_response_text:
            clean_response_text = clean_response_text.split(_ERR_MARKER)[0].strip()

    final = _finalize_document_outcome(
        task=raw_task,
        response_text=clean_response_text,
        timed_out=timed_out,
    )

    result = build_document_orchestration_result(
        text=str(final.get("reply_text") or ""),
        task=final.get("task"),
        done_seen=True,
        requires_task=True,
        previous_step_hint=previous_step_hint,
    )
    result["summary_text"] = summary_text
    return result


def _get_openclaw_document_runtime() -> dict[str, Any]:
    from app.services.openclaw_gateway import get_openclaw_document_runtime
    return get_openclaw_document_runtime()


def _finalize_document_outcome(task, response_text, timed_out=False):
    from app.services.openclaw_gateway import finalize_document_outcome
    return finalize_document_outcome(task=task, response_text=response_text, timed_out=timed_out)


def _submit_and_wait_openclaw(
    *,
    content: str,
    conversation_id: int,
    user_id: int,
    attachment_ids: list[int],
    attachment_context: str,
    wait_seconds: float,
) -> dict[str, Any]:
    from app.services.openclaw_gateway import submit_openclaw_document
    future = submit_openclaw_document(
        content=content,
        conversation_id=conversation_id,
        user_id=user_id,
        attachment_ids=attachment_ids,
        attachment_context=attachment_context,
    )
    return future.result(timeout=wait_seconds)


def _extract_task_from_response(openclaw_result: dict, conversation_id: int) -> dict | None:
    """Extract task from OpenClaw response when trace-polling missed it."""
    import re
    response_json = openclaw_result.get("response_json") or {}
    response_text = str(response_json.get("output_text") or "")
    if not response_text:
        for item in (response_json.get("output") or []):
            for c in (item.get("content") or []):
                if c.get("type") == "output_text":
                    response_text += str(c.get("text") or "")
    if not response_text:
        response_text = str(openclaw_result.get("assistant_text") or "")

    # Try regex extraction
    task_id_match = re.search(r"[a-f0-9]{32}", response_text)
    if task_id_match:
        try:
            from app.services.document_tasks import get_task
            found = get_task(task_id_match.group(0))
            if found:
                return found
        except Exception:
            pass

    # Fallback: find most recent task for this conversation
    try:
        from app.services.document_tasks import get_latest_task_for_conversation
        found = get_latest_task_for_conversation(conversation_id)
        if found:
            return found
    except Exception:
        pass
    return None

