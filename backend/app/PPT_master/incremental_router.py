"""Versioned incremental PPT generation and durable task query routes."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.errors import ok
from app.PPT_master.admission import (
    GenerationBusyError,
    GenerationLimiter,
    InvalidRequestIdError,
    ProjectQuotaError,
    enforce_directory_quota,
    generation_limiter,
    select_request_id,
)
from app.PPT_master.incremental_runner import run_incremental_workflow
from app.PPT_master.media_assets import MediaAssetError, PptMediaAdapter, PptMediaResolver
from app.models import File, PPTIncrementalTask
from app.PPT_master.incremental_store import IncrementalTaskNotFound, IncrementalTaskStore
from app.PPT_master.sse_bridge import make_sse_event
from app.PPT_master.source_context import SourceResolutionError, resolve_ppt_sources


router = APIRouter(tags=["ppt-master-incremental"])
_store = IncrementalTaskStore()
_jobs: set[asyncio.Task] = set()
_PROJECTS_ROOT = Path(__file__).resolve().parent / "projects"
_PROJECTS_TOTAL_MAX_BYTES = 2 * 1024 * 1024 * 1024
_REQUEST_MAX_BYTES = 64 * 1024
_TASK_TIMEOUT_SECONDS = 900
_media_resolver = PptMediaResolver()
_media_adapter = PptMediaAdapter()


def _media_feature_enabled(current_user) -> bool:
    allowed = {value.strip() for value in os.environ.get("PPT_MEDIA_PROVIDED_ALLOWED_USERS", "123").split(",") if value.strip()}
    return str(getattr(current_user, "username", "")) in allowed


_SUPPORTED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
_SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _is_supported_image(record: File) -> bool:
    return (
        str(record.mime_type or "").lower() in _SUPPORTED_IMAGE_MIME_TYPES
        or Path(str(record.filename or record.filepath or "")).suffix.lower() in _SUPPORTED_IMAGE_EXTENSIONS
    )


def _collect_source_media(db: Session, *, project_id: str, owner_user_id: int, file_ids: list[int]) -> list[dict]:
    assets: list[dict] = []
    for file_id in file_ids:
        record = db.query(File).filter(File.id == file_id, or_(File.owner_user_id == owner_user_id, File.user_id == owner_user_id)).first()
        if record is None:
            continue
        try:
            if _is_supported_image(record):
                assets.append(_media_resolver.register_file(db, file_id=record.id, owner_user_id=owner_user_id, source_type="uploaded", project_id=project_id, source_file_id=record.id))
            else:
                assets.extend(_media_adapter.extract_document_images(db, project_id=project_id, owner_user_id=owner_user_id, source_file_id=record.id))
        except MediaAssetError:
            continue
    return assets
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


class IncrementalPPTRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_input: str = Field(..., min_length=2, max_length=20_000)
    page_count: int = Field(default=8, ge=1, le=12)
    page_format: Literal["ppt169", "ppt43"] = "ppt169"
    sources: list[str] = Field(default_factory=list, max_length=1)
    attachment_file_ids: list[int] = Field(default_factory=list, max_length=12)
    knowledge_doc_ids: list[int] = Field(default_factory=list, max_length=20)
    source_policy: Literal["parsed_only", "ready_only"] = "parsed_only"
    pptx_structure_mode: Literal["flat", "structured"] = "flat"
    structured_workspace_id: str | None = None
    request_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$",
    )

    @field_validator("sources")
    @classmethod
    def reject_sources(cls, value: list[str]) -> list[str]:
        if value:
            raise ValueError("sources are disabled; future uploads must use registered asset_id")
        return value

    @model_validator(mode="after")
    def check_structured_workspace_id(self):
        if self.pptx_structure_mode == "structured" and not self.structured_workspace_id:
            raise ValueError("structured_workspace_id is required when pptx_structure_mode=structured")
        return self


def _check_content_length(request: Request) -> None:
    value = request.headers.get("content-length")
    if value is None:
        return
    try:
        content_length = int(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_content_length"}) from exc
    if content_length > _REQUEST_MAX_BYTES:
        raise HTTPException(status_code=413, detail={"code": "request_body_too_large"})


async def _persist_timeout(task_id: str, completed_slide_count: int = 0) -> dict:
    db = SessionLocal()
    try:
        event = _store.append_event(
            db,
            task_id,
            "task.failed",
            {"code": "task_timeout", "completed_slide_count": completed_slide_count},
        )
        return event
    finally:
        db.close()


@router.post("/ppt-master/generate-incremental")
async def ppt_generate_incremental(
    req: IncrementalPPTRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a durable per-slide workflow and stream its milestone events."""

    _check_content_length(request)

    # Validate structured workspace if specified
    if req.pptx_structure_mode == "structured":
        from app.PPT_master.workspace_service import WorkspaceService
        _ws_service = WorkspaceService()
        workspace = _ws_service.get_workspace(db, req.structured_workspace_id)
        if not workspace:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_workspace", "message": f"Workspace {req.structured_workspace_id} not found"}
            )
        # Check user has access (owner or builtin)
        if workspace["source_type"] != "builtin" and workspace["owner_user_id"] != current_user.id:
            raise HTTPException(
                status_code=403,
                detail={"code": "workspace_access_denied", "message": "User does not have access to this workspace"}
            )
    try:
        request_id = select_request_id(req.request_id, idempotency_key)
        enforce_directory_quota(_PROJECTS_ROOT, _PROJECTS_TOTAL_MAX_BYTES)
    except InvalidRequestIdError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
    except ProjectQuotaError as exc:
        raise HTTPException(status_code=507, detail={"code": str(exc)}) from exc

    existing = _store.find_by_request(db, current_user.id, request_id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_incremental_request", "task_id": existing.task_id},
        )

    try:
        lease = await generation_limiter.acquire_nowait(current_user.id)
    except GenerationBusyError as exc:
        raise HTTPException(
            status_code=429,
            detail={"code": exc.code},
            headers={"Retry-After": "5"},
        ) from exc

    task_id = "pptinc_" + uuid.uuid4().hex
    project_id = "pptproj_" + uuid.uuid4().hex
    attachment_records = db.query(File).filter(File.id.in_(req.attachment_file_ids), or_(File.owner_user_id == current_user.id, File.user_id == current_user.id)).all() if req.attachment_file_ids else []
    direct_image_ids = {record.id for record in attachment_records if _is_supported_image(record)}
    contextual_file_ids = [file_id for file_id in req.attachment_file_ids if file_id not in direct_image_ids]
    try:
        source_result = resolve_ppt_sources(
            user_id=current_user.id,
            attachment_file_ids=contextual_file_ids,
            knowledge_doc_ids=req.knowledge_doc_ids,
            source_policy=req.source_policy,
            query=req.user_input,
        )
    except SourceResolutionError as exc:
        await lease.release()
        raise HTTPException(
            status_code=409 if exc.code in {"sources_pending", "sources_failed", "no_ready_sources"} else 422,
            detail={"code": exc.code, "pending_file_ids": exc.pending_file_ids, "failed_file_ids": exc.failed_file_ids},
        ) from exc
    source_manifest = list(source_result.source_manifest)
    try:
        _store.create_task(
            db,
            task_id=task_id,
            project_id=project_id,
            user_id=current_user.id,
            request_id=request_id,
            page_count=req.page_count,
            source_refs={
                "attachment_file_ids": req.attachment_file_ids,
                "knowledge_doc_ids": source_result.knowledge_doc_ids,
                "source_policy": req.source_policy,
                "source_manifest": source_manifest,
                "skipped_sources": source_result.skipped_sources,
            },
        )
        if _media_feature_enabled(current_user):
            for asset in _collect_source_media(db, project_id=project_id, owner_user_id=current_user.id, file_ids=req.attachment_file_ids):
                source_manifest.append({"kind": "media_asset", **asset})
            task = db.query(PPTIncrementalTask).filter(PPTIncrementalTask.task_id == task_id).first()
            if task is not None:
                refs = json.loads(task.source_refs_json or "{}")
                refs["source_manifest"] = source_manifest
                task.source_refs_json = json.dumps(refs, ensure_ascii=False, separators=(",", ":"))
                db.commit()
    except IntegrityError as exc:
        await lease.release()
        existing = _store.find_by_request(db, current_user.id, request_id)
        detail = {"code": "duplicate_incremental_request"}
        if existing is not None:
            detail["task_id"] = existing.task_id
        raise HTTPException(status_code=409, detail=detail) from exc

    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def event_sink(event: dict) -> None:
        await queue.put(event)

    async def producer() -> None:
        try:
            await asyncio.wait_for(
                run_incremental_workflow(
                    task_id=task_id,
                    project_id=project_id,
                    user_id=current_user.id,
                    user_input=req.user_input,
                    page_count=req.page_count,
                    page_format=req.page_format,
                    source_context=source_result.source_context,
                    source_manifest=source_manifest,
                    event_sink=event_sink,
                    pptx_structure_mode=req.pptx_structure_mode,
                    structured_workspace_id=req.structured_workspace_id,
                ),
                timeout=_TASK_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            event = await _persist_timeout(task_id)
            await queue.put(event)
        finally:
            await lease.release()
            await queue.put(None)

    job = asyncio.create_task(producer(), name=f"ppt-incremental:{task_id}")
    _jobs.add(job)
    job.add_done_callback(_jobs.discard)

    async def event_stream():
        while True:
            event = await queue.get()
            if event is None:
                break
            yield make_sse_event(event["event_type"], event)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.get("/ppt-master/tasks/{task_id}")
def get_incremental_task(
    task_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        snapshot = _store.snapshot(db, task_id, current_user.id)
    except IncrementalTaskNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found"}) from exc
    return ok(data=snapshot)
