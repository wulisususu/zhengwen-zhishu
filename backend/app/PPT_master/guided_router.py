"""Guided Strategist (P3-B) HTTP router.

Prefix is applied by the host app (per P3B_SPEC.md §6: /api/v1/ppt-master).
This file is the controller layer: it parses requests, validates via Pydantic
schemas, delegates to ``guided_service`` and translates domain errors into
structured ``ErrorResponse`` bodies. It contains NO business logic.

Dependency assumptions (merged worktree): the host app exposes
  * ``get_db``        -> ``app.database.get_db``  (yields a SQLAlchemy Session)
  * ``get_current_user`` -> ``app.PPT_master.security.get_current_user``
                          (returns an object with ``.id``)
If those modules are unavailable (isolated test run), the router falls back to
locally-defined stubs so it stays importable; tests override them via
``app.dependency_overrides``.
"""
from __future__ import annotations

from typing import Any, Optional

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from . import guided_service as svc
from .guided_schemas import (
    ConfirmRequest,
    ErrorResponse,
    GenerateOut,
    GenerateRequest,
    GuidedProjectCreate,
    GuidedProjectListOut,
    GuidedProjectOut,
    MutationOut,
    RetryRequest,
    StageOut,
    StagePatch,
)

# --------------------------------------------------------------------------- #
# Dependency resolution (resilient to offline test environments)
# --------------------------------------------------------------------------- #
try:  # pragma: no cover - present in merged worktree
    from ..database import get_db as _repo_get_db  # type: ignore
except Exception:  # pragma: no cover
    def _repo_get_db():  # type: ignore
        raise RuntimeError("get_db dependency not configured")

try:  # pragma: no cover - present in merged worktree
    # NOTE: this repo exposes get_current_user via app.deps (not app.PPT_master.security).
    from app.deps import get_current_user as _repo_get_current_user  # type: ignore
except Exception:  # pragma: no cover
    def _repo_get_current_user():  # type: ignore
        raise RuntimeError("get_current_user dependency not configured")


def _err(code: int, error_code: str, message: str, detail: Any = None) -> HTTPException:
    return HTTPException(
        status_code=code,
        detail=ErrorResponse(error_code=error_code, message=message, detail=detail).model_dump(),
    )


# --------------------------------------------------------------------------- #
# Background generation (mirrors incremental_router's producer pattern)
# --------------------------------------------------------------------------- #
_guided_jobs: set[asyncio.Task] = set()


async def _run_guided_background(
    guided_project_id: str, project_id: str, task_id: str, user_id: int
) -> None:
    """Run the confirmed guided result through the EXISTING incremental chain.

    Mirrors ``incremental_router``'s producer pattern: pre-create the durable
    ``PPTIncrementalTask`` row (the chain's ``append_event`` requires it) and run
    the chain as a detached asyncio task. On success the GuidedProject is marked
    ``completed``; any failure (raised exception or ``task.failed`` detected by
    ``run_guided_generation``) marks it ``failed`` with structured error json.
    """
    from app.database import SessionLocal
    from app.PPT_master.incremental_store import IncrementalTaskStore
    from . import guided_service as svc
    from .guided_generation_adapter import run_guided_generation

    db = SessionLocal()
    gp = None
    try:
        gp = (
            db.query(svc.GuidedProject)
            .filter(
                svc.GuidedProject.guided_project_id == guided_project_id,
                svc.GuidedProject.owner_user_id == user_id,
            )
            .first()
        )
        if gp is None:
            return
        # Pre-create the durable task row so the chain can persist milestones.
        _store = IncrementalTaskStore()
        _store.create_task(
            db,
            task_id=task_id,
            project_id=project_id,
            user_id=user_id,
            request_id="guided_" + str(gp.guided_project_id),
            page_count=int((gp.result_json or {}).get("page_count", 6) or 6),
            source_refs={"guided_project_id": str(gp.guided_project_id), "mode": "guided"},
        )
        await run_guided_generation(gp, project_id, task_id)
        gp.status = "completed"
        gp.completed_at = datetime.utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001 - persist as structured failure
        # Defensive: gp may be unbound if the very first query blew up (e.g. the
        # guided_projects table is missing or the row vanished before we read it).
        # Only mark the row failed when we actually have a reference to it; an
        # unbound gp here used to raise UnboundLocalError and mask the real cause.
        if gp is not None:
            gp.status = "failed"
            gp.error_json = {"message": str(exc), "type": type(exc).__name__}
            gp.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


router = APIRouter(prefix="/guided-projects", tags=["guided"])


def _to_list_out(d: dict) -> GuidedProjectListOut:
    return GuidedProjectListOut(**d)


def _to_detail_out(gp: Any) -> GuidedProjectOut:
    return GuidedProjectOut(
        guided_project_id=str(gp.guided_project_id),
        owner_user_id=int(gp.owner_user_id),
        project_id=str(gp.project_id) if gp.project_id else None,
        title=gp.title,
        mode=gp.mode,
        current_stage=gp.current_stage,
        status=gp.status,
        revision=int(gp.revision),
        stage1_json=gp.stage1_json,
        stage2_json=gp.stage2_json,
        stage3_json=gp.stage3_json,
        recommendations_json=gp.recommendations_json,
        result_json=gp.result_json,
        confirmed_values_json=gp.confirmed_values_json,
        source_refs_json=gp.source_refs_json,
        generation_task_id=gp.generation_task_id,
        error_json=gp.error_json,
        created_at=gp.created_at,
        updated_at=gp.updated_at,
        confirmed_at=gp.confirmed_at,
        completed_at=gp.completed_at,
    )


def _to_mutation_out(gp: Any) -> MutationOut:
    return MutationOut(
        guided_project_id=str(gp.guided_project_id),
        current_stage=gp.current_stage,
        status=gp.status,
        revision=int(gp.revision),
    )


def _stage_out(gp: Any) -> StageOut:
    field = {
        "stage1_draft": gp.stage1_json,
        "stage2_draft": gp.stage2_json,
        "stage3_draft": gp.stage3_json,
    }.get(gp.current_stage)
    chosen = None
    if gp.current_stage in ("stage2_draft", "stage3_draft", "confirmed"):
        chosen = gp.stage2_json
    actions = []
    if gp.current_stage == "stage1_draft":
        actions = ["confirm_stage1", "revise"]
    elif gp.current_stage == "stage2_draft":
        actions = ["confirm_stage2", "revise_stage1"]
    elif gp.current_stage == "stage3_draft":
        actions = ["confirm_stage3", "revise_stage1", "revise_stage2"]
    elif gp.current_stage == "confirmed":
        actions = ["generate"]
    elif gp.current_stage == "failed":
        actions = ["retry"]
    return StageOut(
        guided_project_id=str(gp.guided_project_id),
        current_stage=gp.current_stage,
        status=gp.status,
        revision=int(gp.revision),
        stage_data=field,
        allowed_next_actions=actions,
        chosen_direction=chosen,
    )


# --------------------------------------------------------------------------- #
# Endpoints (per P3B_SPEC.md §6)
# --------------------------------------------------------------------------- #
@router.post("/", response_model=MutationOut, status_code=status.HTTP_201_CREATED)
def create_project(
    body: GuidedProjectCreate,
    db: Session = Depends(_repo_get_db),
    user: Any = Depends(_repo_get_current_user),
):
    try:
        gp = svc.create_guided_project(
            db, user, title=body.title, prompt=body.prompt, source_refs=body.source_refs
        )
    except svc.FeatureDenied as e:
        raise _err(status.HTTP_403_FORBIDDEN, e.error_code, e.message)
    return _to_mutation_out(gp)


@router.get("/", response_model=GuidedProjectListOut)
def list_projects(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(_repo_get_db),
    user: Any = Depends(_repo_get_current_user),
):
    return _to_list_out(svc.list_guided_projects(db, user, page=page, page_size=page_size))


@router.get("/{project_id}", response_model=GuidedProjectOut)
def get_project(
    project_id: str,
    db: Session = Depends(_repo_get_db),
    user: Any = Depends(_repo_get_current_user),
):
    try:
        gp = svc.get_guided_project(db, user, project_id)
    except svc.NotFound as e:
        raise _err(status.HTTP_404_NOT_FOUND, e.error_code, e.message)
    return _to_detail_out(gp)


@router.get("/{project_id}/stage", response_model=StageOut)
def get_stage(
    project_id: str,
    db: Session = Depends(_repo_get_db),
    user: Any = Depends(_repo_get_current_user),
):
    try:
        gp = svc.get_guided_project(db, user, project_id)
    except svc.NotFound as e:
        raise _err(status.HTTP_404_NOT_FOUND, e.error_code, e.message)
    return _stage_out(gp)


@router.patch("/{project_id}/stage", response_model=MutationOut)
def patch_project_stage(
    project_id: str,
    body: StagePatch,
    db: Session = Depends(_repo_get_db),
    user: Any = Depends(_repo_get_current_user),
):
    try:
        gp = svc.patch_stage(
            db, user, project_id, expected_revision=body.expected_revision, stage_data=body.stage_data
        )
    except svc.NotFound as e:
        raise _err(status.HTTP_404_NOT_FOUND, e.error_code, e.message)
    except svc.RevisionConflict as e:
        raise _err(
            status.HTTP_409_CONFLICT, e.error_code, str(e),
            detail={"expected": e.expected, "actual": e.actual},
        )
    except svc.StageGateInvalid as e:
        raise _err(status.HTTP_400_BAD_REQUEST, e.error_code, str(e))
    return _to_mutation_out(gp)


@router.post("/{project_id}/confirm", response_model=MutationOut)
def confirm_project_stage(
    project_id: str,
    body: ConfirmRequest,
    db: Session = Depends(_repo_get_db),
    user: Any = Depends(_repo_get_current_user),
):
    try:
        gp = svc.confirm_stage(
            db,
            user,
            project_id,
            expected_revision=body.expected_revision,
            stage=body.stage,
            action=body.action,
            direction_id=body.direction_id,
        )
    except svc.NotFound as e:
        raise _err(status.HTTP_404_NOT_FOUND, e.error_code, e.message)
    except svc.RevisionConflict as e:
        raise _err(
            status.HTTP_409_CONFLICT, e.error_code, str(e),
            detail={"expected": e.expected, "actual": e.actual},
        )
    except svc.StageGateInvalid as e:
        raise _err(status.HTTP_400_BAD_REQUEST, e.error_code, str(e))
    return _to_mutation_out(gp)


@router.post("/{project_id}/generate", response_model=GenerateOut)
async def generate_project(
    project_id: str,
    body: Optional[GenerateRequest] = None,
    db: Session = Depends(_repo_get_db),
    user: Any = Depends(_repo_get_current_user),
):
    expected = body.expected_revision if body else None
    try:
        gp = svc.generate(db, user, project_id, expected_revision=expected)
    except svc.NotFound as e:
        raise _err(status.HTTP_404_NOT_FOUND, e.error_code, e.message)
    except svc.RevisionConflict as e:
        raise _err(
            status.HTTP_409_CONFLICT, e.error_code, str(e),
            detail={"expected": e.expected, "actual": e.actual},
        )
    except svc.StageGateInvalid as e:
        raise _err(status.HTTP_400_BAD_REQUEST, e.error_code, str(e))
    except svc.GenerationFailed as e:
        raise _err(status.HTTP_500_INTERNAL_SERVER_ERROR, e.error_code, e.message)
    # Launch the real incremental chain as a detached background task so the
    # endpoint returns immediately with the generation_task_id (status polling
    # is done client-side via GET /{id}).
    job = asyncio.create_task(
        _run_guided_background(
            str(gp.guided_project_id),
            str(gp.project_id),
            str(gp.generation_task_id),
            int(user.id),
        ),
        name=f"guided:{gp.guided_project_id}",
    )
    _guided_jobs.add(job)
    job.add_done_callback(_guided_jobs.discard)
    return GenerateOut(
        guided_project_id=str(gp.guided_project_id),
        status=gp.status,
        generation_task_id=str(gp.generation_task_id),
    )


@router.post("/{project_id}/retry", response_model=GenerateOut)
async def retry_project(
    project_id: str,
    _body: Optional[RetryRequest] = None,
    db: Session = Depends(_repo_get_db),
    user: Any = Depends(_repo_get_current_user),
):
    try:
        gp = svc.retry(db, user, project_id)
    except svc.NotFound as e:
        raise _err(status.HTTP_404_NOT_FOUND, e.error_code, e.message)
    except svc.StageGateInvalid as e:
        raise _err(status.HTTP_400_BAD_REQUEST, e.error_code, str(e))
    except svc.GenerationFailed as e:
        raise _err(status.HTTP_500_INTERNAL_SERVER_ERROR, e.error_code, e.message)
    job = asyncio.create_task(
        _run_guided_background(
            str(gp.guided_project_id),
            str(gp.project_id),
            str(gp.generation_task_id),
            int(user.id),
        ),
        name=f"guided:{gp.guided_project_id}",
    )
    _guided_jobs.add(job)
    job.add_done_callback(_guided_jobs.discard)
    return GenerateOut(
        guided_project_id=str(gp.guided_project_id),
        status=gp.status,
        generation_task_id=str(gp.generation_task_id),
    )
