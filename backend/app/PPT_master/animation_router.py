"""P4 Animation REST API router.

Endpoints:
  GET  /ppt-master/projects/{project_id}/editor/animations
  PUT  /ppt-master/projects/{project_id}/editor/animations
  PATCH /ppt-master/projects/{project_id}/editor/animations
  POST /ppt-master/projects/{project_id}/editor/animations/validate
  GET  /ppt-master/projects/{project_id}/editor/animations/export-preview
"""

from __future__ import annotations

import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.PPT_master.animation_schemas import (
    AnimationManifest,
    AnimationSaveRequest,
    AnimationSaveResponse,
    AnimationGetResponse,
    AnimationValidateRequest,
    AnimationValidateResponse,
    AnimationExportPreviewRequest,
    AnimationExportPreviewResponse,
)
from app.PPT_master.animation_service import (
    AnimationNotFound,
    AnimationRevisionConflict,
    AnimationService,
    AnimationValidationError,
)
from app.PPT_master.editor_documents import EditorDocumentNotFound, EditorDocumentStore

router = APIRouter(tags=["ppt-master"])
_service = AnimationService()
_docs = EditorDocumentStore()


def _require_p0_feature(current_user) -> None:
    allowed = {value.strip() for value in os.environ.get("PPT_P0_ALLOWED_USERS", "123").split(",") if value.strip()}
    if str(getattr(current_user, "username", "")) not in allowed:
        raise HTTPException(status_code=404, detail={"code": "ppt_feature_unavailable"})


def _parse_animation_request(payload: dict, request_type):
    try:
        return request_type.model_validate(payload)
    except ValidationError as exc:
        fields = {str(item) for error in exc.errors() for item in error.get("loc", ())}
        if "direction" in fields:
            raise HTTPException(status_code=422, detail={"code": "unsupported_animation_direction"}) from exc
        if "repeat" in fields:
            raise HTTPException(status_code=422, detail={"code": "unsupported_animation_repeat"}) from exc
        if {"effect", "category"} & fields or "unsupported_animation_effect" in str(exc):
            raise HTTPException(status_code=422, detail={"code": "unsupported_animation_effect"}) from exc
        raise HTTPException(status_code=422, detail={"code": "animation_validation_error", "errors": exc.errors()}) from exc


def _extract_element_slide_ids(doc: dict) -> tuple[set[str], set[str], dict[str, set[str]]]:
    """Extract slide ids, global element ids, and per-slide target ownership."""
    slides = doc.get("slides", []) or []
    slide_ids: set[str] = set()
    element_ids: set[str] = set()
    elements_by_slide: dict[str, set[str]] = {}
    for slide in slides:
        sid = slide.get("id") or slide.get("slide_id", "")
        if not sid:
            continue
        slide_ids.add(sid)
        owned = elements_by_slide.setdefault(sid, set())
        for el in slide.get("elements", []) or []:
            eid = el.get("id", "")
            if eid:
                element_ids.add(eid)
                owned.add(eid)
    return slide_ids, element_ids, elements_by_slide


@router.get("/ppt-master/projects/{project_id}/editor/animations")
def get_animations(project_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_p0_feature(current_user)
    try:
        return {"data": _service.get_or_initialize(db, project_id=project_id, user_id=current_user.id)}
    except AnimationNotFound:
        return {
            "data": {
                "project_id": project_id,
                "document_revision": 0,
                "animation_revision": 1,
                "manifest": AnimationManifest(
                    version=1, project_id=project_id, animation_revision=1, slides=[]
                ).model_dump(mode="json"),
            }
        }


@router.put("/ppt-master/projects/{project_id}/editor/animations")
def save_animations(project_id: str, payload: dict,
                    current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_p0_feature(current_user)
    req = _parse_animation_request(payload, AnimationSaveRequest)

    # Read editor document for element validation
    try:
        doc_data = _docs.get_or_initialize(db, project_id=project_id, user_id=current_user.id)
    except EditorDocumentNotFound:
        raise HTTPException(status_code=404, detail={"code": "editor_project_not_found"})

    slide_ids, element_ids, elements_by_slide = _extract_element_slide_ids(doc_data.get("document", {}))

    # Verify document revision match
    doc_revision = doc_data.get("revision", 0)
    if req.expected_document_revision != doc_revision:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "editor_revision_conflict",
                "expected": req.expected_document_revision,
                "actual": doc_revision,
            },
        )

    try:
        result = _service.save(
            db,
            project_id=project_id,
            user_id=current_user.id,
            expected_document_revision=req.expected_document_revision,
            expected_animation_revision=req.expected_animation_revision,
            manifest=req.manifest,
            slide_ids=slide_ids,
            element_ids=element_ids,
            elements_by_slide=elements_by_slide,
        )
        return {"data": result}
    except AnimationRevisionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "animation_revision_conflict", "expected": exc.expected, "actual": exc.actual},
        ) from exc
    except AnimationValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "animation_validation_error", "errors": str(exc)}) from exc


@router.patch("/ppt-master/projects/{project_id}/editor/animations")
def patch_animations(project_id: str, payload: dict,
                     current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Alias for PUT — partial save of animation manifest."""
    return save_animations(project_id, payload, current_user, db)


@router.post("/ppt-master/projects/{project_id}/editor/animations/validate")
def validate_animations(project_id: str, req: AnimationValidateRequest,
                        current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_p0_feature(current_user)

    slide_ids: set[str] = set()
    element_ids: set[str] = set()
    elements_by_slide: dict[str, set[str]] = {}
    if req.document:
        slide_ids, element_ids, elements_by_slide = _extract_element_slide_ids(req.document)
    else:
        try:
            doc_data = _docs.get_or_initialize(db, project_id=project_id, user_id=current_user.id)
            slide_ids, element_ids, elements_by_slide = _extract_element_slide_ids(doc_data.get("document", {}))
        except EditorDocumentNotFound:
            pass

    result = _service.validate_only(req.manifest, slide_ids, element_ids, elements_by_slide)
    return {"data": result}


@router.get("/ppt-master/projects/{project_id}/editor/animations/export-preview")
def export_preview_animations_qp(
    project_id: str,
    document_revision: int = 1,
    animation_revision: int = 1,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export preview with query parameters."""
    _require_p0_feature(current_user)
    try:
        anim_data = _service.get(db, project_id=project_id, user_id=current_user.id)
        doc_data = _docs.get_or_initialize(db, project_id=project_id, user_id=current_user.id)

        if document_revision != doc_data.get("revision", 0):
            raise HTTPException(
                status_code=409,
                detail={"code": "document_revision_mismatch",
                        "expected": document_revision,
                        "actual": doc_data.get("revision")},
            )
        if animation_revision != anim_data["animation_revision"]:
            raise HTTPException(
                status_code=409,
                detail={"code": "animation_revision_mismatch",
                        "expected": animation_revision,
                        "actual": anim_data["animation_revision"]},
            )

        manifest = AnimationManifest.model_validate(anim_data["manifest"])
        slide_ids, element_ids, elements_by_slide = _extract_element_slide_ids(doc_data.get("document", {}))

        targets = []
        errors = []
        for slide_anim in manifest.slides:
            for anim in slide_anim.animations:
                if anim.element_id not in elements_by_slide.get(slide_anim.slide_id, set()):
                    errors.append(f"element not found on slide {slide_anim.slide_id}: {anim.element_id}")
                    targets.append({
                        "slide_id": slide_anim.slide_id,
                        "element_id": anim.element_id,
                        "shape_id": None, "shape_name": "",
                        "supported": False, "reason": "element not found on slide",
                    })
                else:
                    targets.append({
                        "slide_id": slide_anim.slide_id,
                        "element_id": anim.element_id,
                        "shape_id": None, "shape_name": "",
                        "supported": True, "reason": "shape_id assigned at export",
                    })

        return {"data": {
            "project_id": project_id,
            "document_revision": anim_data["document_revision"],
            "animation_revision": anim_data["animation_revision"],
            "targets": targets, "errors": errors,
        }}
    except AnimationNotFound:
        raise HTTPException(status_code=404, detail={"code": "animation_not_found"})

