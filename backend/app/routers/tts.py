"""TTS: text-to-speech."""
import uuid
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from app.deps import get_current_user
from app.errors import ERR_INTERNAL, ERR_NOT_FOUND, fail, ok
from app.models import User
from app.services.voice_artifacts import get_tts_artifact, store_tts_artifact

router = APIRouter(prefix="/tts", tags=["tts"])


def build_tts_audio_url(task_id: str) -> str:
    return f"/api/v1/tts/result/{str(task_id or '').strip()}"


def build_tts_voice_event(task_id: str, audio_url: str, mime_type: str) -> dict:
    return {
        "type": "audio_done",
        "capability": "tts",
        "task_id": str(task_id or "").strip(),
        "status": "completed",
        "audio_url": str(audio_url or "").strip(),
        "mime_type": str(mime_type or "").strip(),
    }


@router.post("/synthesize")
def synthesize(body: dict, user: User = Depends(get_current_user)):
    text = body.get("text", "")
    if not text:
        return fail(ERR_INTERNAL, "text is required")
    try:
        from app.services.tts_service import synthesize as tts

        task_id = uuid.uuid4().hex[:16]
        audio_bytes = tts(text)
        store_tts_artifact(task_id, audio_bytes, "audio/wav")
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "inline",
                "X-Task-Id": task_id,
            }
        )
    except Exception as e:
        return fail(ERR_INTERNAL, str(e))


@router.get("/result/{task_id}")
def get_tts_result(task_id: str, user: User = Depends(get_current_user)):
    payload = get_tts_artifact(task_id)
    if not payload:
        return fail(ERR_NOT_FOUND, "tts result not found")
    return Response(
        content=payload["audio_bytes"],
        media_type=payload["mime_type"],
        headers={"Content-Disposition": "inline"},
    )


@router.get("/status/{task_id}")
def tts_status(task_id: str, user: User = Depends(get_current_user)):
    return ok(data={"task_id": task_id, "status": "completed"})
