"""FastAPI router: PPT-master SSE endpoint."""
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session
from typing import Literal

from app.database import get_db
from app.deps import get_current_user
from app.PPT_master.runner import run_pipeline_stream
from app.PPT_master.sse_bridge import make_sse_event
from app.PPT_master.admission import (
    GenerationBusyError,
    IdempotencyService,
    InvalidRequestIdError,
    ProjectQuotaError,
    enforce_directory_quota,
    generation_limiter,
    select_request_id,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ppt-master"])
_generation_limiter = generation_limiter
_idempotency_service = IdempotencyService()
_PROJECTS_ROOT = Path(__file__).resolve().parent / "projects"
_PROJECTS_TOTAL_MAX_BYTES = 2 * 1024 * 1024 * 1024
_REQUEST_MAX_BYTES = 64 * 1024
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


class PPTGenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_input: str = Field(..., min_length=2, max_length=20_000, description="PPT topic or material description")
    page_count: int = Field(default=8, ge=1, le=12, description="Number of pages")
    page_format: Literal["ppt169", "ppt43"] = Field(default="ppt169", description="Page format")
    sources: list[str] = Field(default_factory=list, max_length=1, description="Disabled during Stage A")
    request_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$",
        description="Client idempotency key",
    )

    @field_validator("sources")
    @classmethod
    def reject_sources(cls, value: list[str]) -> list[str]:
        if value:
            raise ValueError("sources are disabled during Stage A; use registered asset_id in a future API")
        return value


@router.post("/ppt-master/generate")
async def ppt_generate(
    req: PPTGenRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Launch PPT generation task, returns SSE stream."""

    raw_content_length = request.headers.get("content-length")
    if raw_content_length:
        try:
            content_length = int(raw_content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "invalid_content_length"}) from exc
        if content_length > _REQUEST_MAX_BYTES:
            raise HTTPException(status_code=413, detail={"code": "request_body_too_large"})

    try:
        request_id = select_request_id(req.request_id, idempotency_key)
    except InvalidRequestIdError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc

    try:
        enforce_directory_quota(_PROJECTS_ROOT, _PROJECTS_TOTAL_MAX_BYTES)
    except ProjectQuotaError as exc:
        raise HTTPException(status_code=507, detail={"code": str(exc)}) from exc

    task_id = "ppt_" + uuid.uuid4().hex
    decision = _idempotency_service.begin(db, current_user.id, request_id, task_id)
    if decision.kind == "replay":
        async def replay_generator():
            yield make_sse_event(decision.event_type or "fallback", decision.payload or {"valid": False})

        return StreamingResponse(replay_generator(), media_type="text/event-stream", headers=_SSE_HEADERS)
    if decision.kind == "active":
        raise HTTPException(status_code=409, detail={"code": "duplicate_request_in_progress"})

    try:
        lease = await _generation_limiter.acquire_nowait(current_user.id)
    except GenerationBusyError as exc:
        db.delete(decision.record)
        db.commit()
        raise HTTPException(
            status_code=429,
            detail={"code": exc.code},
            headers={"Retry-After": "5"},
        ) from exc

    async def event_generator():
        try:
            async for sse in run_pipeline_stream(
                user_input=req.user_input,
                page_count=req.page_count,
                page_format=req.page_format,
                sources=[],
                task_id=task_id,
                user_id=current_user.id,
                idempotency_record_id=decision.record.id,
            ):
                yield sse
        finally:
            await lease.release()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


from app.PPT_master.incremental_router import router as incremental_router  # noqa: E402
from app.PPT_master.editor_router import router as editor_router  # noqa: E402
from app.PPT_master.template_router import router as template_router  # noqa: E402
from app.PPT_master.native_enhance_router import router as native_enhance_router  # noqa: E402
from app.PPT_master.workspace_router import router as workspace_router  # noqa: E402
from app.PPT_master.guided_router import router as guided_router  # noqa: E402  (P3-B Guided Strategist)
from app.PPT_master.animation_router import router as animation_router  # noqa: E402  (P4 Object Animations)

router.include_router(incremental_router)
router.include_router(editor_router)
router.include_router(template_router)
router.include_router(native_enhance_router)
router.include_router(workspace_router)
# P3-B Guided Strategist: mounted at /api/v1/ppt-master/guided-projects/...
# (ppt_master_router is itself included at /api/v1, so use /ppt-master here.)
router.include_router(guided_router, prefix="/ppt-master")
# P4 Object Animations: mounted at /api/v1/ppt-master/projects/{project_id}/editor/animations/...
router.include_router(animation_router)

