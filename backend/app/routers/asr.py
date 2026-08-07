"""ASR endpoint."""
import logging
import os
import shutil
import tempfile
import uuid
from fastapi import APIRouter, UploadFile, File, Depends, Form
from app.deps import require_asr_access
from app.errors import ok, fail, ERR_ASR
from app.services.asr_contract import recognize_saved_path
from app.services.voice_input_pipeline import VoiceInputPipeline
from app.services.voice_refiner import build_default_voice_refiner

router = APIRouter(prefix="/asr", tags=["asr"])
logger = logging.getLogger(__name__)
_VOICE_PIPELINES: dict[str, VoiceInputPipeline] = {}


def build_asr_voice_event(
    task_id: str,
    transcript: str,
    mode: str,
    backend: str,
    *,
    raw_transcript: str | None = None,
    stages: list[str] | None = None,
    latency_ms: dict | None = None,
    revision_id: int | None = None,
) -> dict:
    normalized_transcript = str(transcript or "").strip()
    normalized_stages = list(stages or ["raw_asr"])
    normalized_latency = {
        "partial_fix_p95": int((latency_ms or {}).get("partial_fix_p95") or 0),
        "sentence_fix_p95": int((latency_ms or {}).get("sentence_fix_p95") or 0),
        "final_polish_p95": int((latency_ms or {}).get("final_polish_p95") or 0),
    }
    normalized_revision_id = int(revision_id or 1)
    return {
        "type": "audio_done",
        "capability": "asr",
        "task_id": str(task_id or "").strip(),
        "status": "completed",
        "transcript": normalized_transcript,
        "raw_transcript": str(raw_transcript or normalized_transcript).strip(),
        "mode": str(mode or "").strip(),
        "backend": str(backend or "").strip(),
        "stages": normalized_stages,
        "latency_ms": normalized_latency,
        "revision_id": max(1, normalized_revision_id),
    }


def _save_upload(upload: UploadFile, suffix: str = ".wav") -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        shutil.copyfileobj(upload.file, tmp)
        return tmp.name
    finally:
        tmp.close()


def _configured_asr_backend() -> str:
    value = str(os.environ.get("ASR_BACKEND") or os.environ.get("ASR_MODE") or "cpu").strip().lower()
    if value in {"rknn", "npu"}:
        return "rknn"
    return "cpu"


def _cpu_transcribe(wav_path: str) -> str:
    from app.services.asr_service import transcribe as default_transcribe

    return default_transcribe(wav_path)


def _rknn_transcribe(wav_path: str) -> str:
    from app.services.asr_service_rknn import transcribe as rknn_transcribe

    return rknn_transcribe(wav_path)


def _preferred_transcribe(wav_path: str) -> tuple[str, str]:
    backend = _configured_asr_backend()
    if backend == "rknn":
        try:
            return _rknn_transcribe(wav_path), "rknn"
        except Exception as exc:
            logger.warning("RKNN ASR failed, fallback to CPU ASR: %s", exc, exc_info=True)
    return _cpu_transcribe(wav_path), "cpu"


def _build_pipeline_with_defaults(*, task_id: str, mode: str, initial_revision_id: int = 0) -> VoiceInputPipeline:
    refiner = build_default_voice_refiner()
    backend_name = str(getattr(refiner, "backend_name", "") or "asr + deterministic_text_refiner").strip()
    return VoiceInputPipeline(
        task_id=task_id,
        mode=mode,
        backend=backend_name,
        partial_fix_runner=refiner.refine_partial,
        sentence_fix_runner=refiner.refine_sentence,
        final_polish_runner=refiner.refine_final,
        initial_revision_id=initial_revision_id,
    )


def build_voice_input_pipeline(response_kind: str, *, session_id: str | None = None) -> VoiceInputPipeline | None:
    normalized_kind = str(response_kind or "").strip().lower()
    if normalized_kind not in {"chunk", "final", "internal_asr"}:
        return None
    pipeline_mode = "internal_asr" if normalized_kind == "internal_asr" else "streaming_voice_input"
    normalized_session_id = str(session_id or "").strip()
    if normalized_kind == "chunk" and normalized_session_id:
        pipeline = _VOICE_PIPELINES.get(normalized_session_id)
        if pipeline is None:
            pipeline = _build_pipeline_with_defaults(
                task_id=f"voice_{uuid.uuid4().hex[:12]}",
                mode=pipeline_mode,
            )
            _VOICE_PIPELINES[normalized_session_id] = pipeline
        return pipeline
    if normalized_kind == "final" and normalized_session_id:
        previous = _VOICE_PIPELINES.pop(normalized_session_id, None)
        if previous is not None:
            previous.mode = pipeline_mode
            return previous
    return _build_pipeline_with_defaults(task_id=f"voice_{uuid.uuid4().hex[:12]}", mode=pipeline_mode)


def _recognize_saved_path(file_path: str, response_kind: str, *, session_id: str | None = None) -> dict:
    pipeline = build_voice_input_pipeline(response_kind, session_id=session_id)
    pipeline_response_kind = "final" if str(response_kind or "").strip().lower() == "internal_asr" else response_kind
    payload = recognize_saved_path(file_path, pipeline_response_kind, _preferred_transcribe, pipeline=pipeline)
    payload["mode"] = response_kind
    return payload


def _recognize_upload(file: UploadFile, response_kind: str, *, session_id: str | None = None) -> dict:
    tmp_path = _save_upload(file)
    try:
        return _recognize_saved_path(tmp_path, response_kind, session_id=session_id)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _reset_voice_pipeline_sessions() -> None:
    _VOICE_PIPELINES.clear()


def _build_voice_payload_from_events(pipeline: VoiceInputPipeline, events: list[dict], mode: str, backend: str) -> dict:
    payload = {
        "text": "",
        "mode": mode,
        "backend": backend,
        "voice_events": list(events or []),
        "voice_state": pipeline.snapshot(),
        "task_id": str(getattr(pipeline, "task_id", "") or "").strip(),
    }
    completion_event = next((event for event in reversed(events) if event.get("type") == "audio_done"), None)
    if completion_event:
        payload["voice_event"] = completion_event
        payload["text"] = str(completion_event.get("transcript") or "").strip()
    else:
        snapshot = payload["voice_state"] or {}
        payload["text"] = str(
            snapshot.get("final_text")
            or snapshot.get("committed_sentence_text")
            or snapshot.get("provisional_text")
            or ""
        ).strip()
    return payload


def _advance_voice_session(session_id: str, *, pause_ms: int = 0, explicit_finalize: bool = False) -> dict:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise ValueError("session_id is required")
    pipeline = _VOICE_PIPELINES.get(normalized_session_id)
    if pipeline is None:
        raise ValueError("voice session not found")
    events = pipeline.process_pause(pause_ms=pause_ms, explicit_finalize=explicit_finalize)
    if explicit_finalize or int(pause_ms or 0) >= int(pipeline.final_pause_ms or 0):
        _VOICE_PIPELINES.pop(normalized_session_id, None)
    return _build_voice_payload_from_events(pipeline, events, "chunk", pipeline.backend)


@router.post("/recognize")
async def recognize(file: UploadFile = File(...), _: bool = Depends(require_asr_access)):
    try:
        return ok(data=_recognize_upload(file, "legacy"))
    except Exception as e:
        return fail(ERR_ASR, str(e))


@router.post("/recognize_chunk")
async def recognize_chunk(
    file: UploadFile = File(...),
    session_id: str | None = Form(None),
    _: bool = Depends(require_asr_access),
):
    try:
        return ok(data=_recognize_upload(file, "chunk", session_id=session_id))
    except Exception as e:
        return fail(ERR_ASR, str(e))


@router.post("/recognize_pause")
async def recognize_pause(body: dict, _: bool = Depends(require_asr_access)):
    try:
        session_id = body.get("session_id")
        pause_ms = int(body.get("pause_ms") or 0)
        explicit_finalize = bool(body.get("explicit_finalize"))
        return ok(data=_advance_voice_session(session_id, pause_ms=pause_ms, explicit_finalize=explicit_finalize))
    except Exception as e:
        return fail(ERR_ASR, str(e))


@router.post("/recognize_final")
async def recognize_final(
    file: UploadFile = File(...),
    session_id: str | None = Form(None),
    _: bool = Depends(require_asr_access),
):
    try:
        return ok(data=_recognize_upload(file, "final", session_id=session_id))
    except Exception as e:
        return fail(ERR_ASR, str(e))
