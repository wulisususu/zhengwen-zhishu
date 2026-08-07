"""Authenticated native template-fill endpoints; separate from incremental SVG generation."""
from __future__ import annotations

import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user
from app.PPT_master.template_fill import TemplateFillError, TemplateFillPlanConflict, TemplateFillPlanImmutable, TemplateFillPlanNotConfirmed, TemplateFillStore

router = APIRouter(tags=["ppt-master-template-fill"])
_store = TemplateFillStore()


def _require_feature(current_user) -> None:
    allowed = {item.strip() for item in os.environ.get("PPT_TEMPLATE_FILL_ALLOWED_USERS", "123").split(",") if item.strip()}
    if str(getattr(current_user, "username", "")) not in allowed:
        raise HTTPException(status_code=404, detail={"code": "ppt_feature_unavailable"})


class TemplateFillPlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_slides: list[int] = Field(min_length=1, max_length=100)
    source_file_ids: list[int] = Field(default_factory=list, max_length=20)


class TemplateFillPlanUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    plan: dict


class TemplateRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_file_id: int = Field(gt=0)
    title: str = Field(default="", max_length=256)


class TemplateFillApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


@router.post("/ppt-master/templates")
def register_template(req: TemplateRegisterRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_feature(current_user)
    try:
        return {"data": _store.register_template(db, source_file_id=req.source_file_id, user_id=current_user.id, title=req.title)}
    except TemplateFillError as exc:
        raise HTTPException(status_code=422 if str(exc) != "template_file_not_found" else 404, detail={"code": str(exc)}) from exc


@router.get("/ppt-master/templates")
def list_templates(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_feature(current_user)
    return {"data": _store.list_templates(db, user_id=current_user.id)}


@router.get("/ppt-master/templates/{template_id}")
def get_template(template_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_feature(current_user)
    result = _store.get_template(db, template_id=template_id, user_id=current_user.id)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "template_not_found"})
    return {"data": result}


@router.post("/ppt-master/templates/{template_id}/analyze")
def analyze_template(template_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_feature(current_user)
    try:
        return {"data": _store.analyze_template(db, template_id=template_id, user_id=current_user.id)}
    except TemplateFillError as exc:
        raise HTTPException(status_code=404 if str(exc) == "template_not_found" else 422, detail={"code": str(exc)}) from exc


@router.post("/ppt-master/templates/{template_id}/fill-plans")
def create_fill_plan(template_id: str, req: TemplateFillPlanCreateRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_feature(current_user)
    try:
        return {"data": _store.create_fill_plan(db, template_id=template_id, user_id=current_user.id, selected_slides=req.selected_slides, source_file_ids=req.source_file_ids)}
    except TemplateFillError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc


@router.patch("/ppt-master/fill-plans/{plan_id}")
def update_fill_plan(plan_id: str, req: TemplateFillPlanUpdateRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_feature(current_user)
    try:
        result = _store.update_fill_plan(db, plan_id=plan_id, user_id=current_user.id, expected_revision=req.expected_revision, plan=req.plan)
    except (TemplateFillPlanConflict, TemplateFillPlanImmutable) as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    except TemplateFillError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "template_fill_plan_not_found"})
    return {"data": result}


@router.post("/ppt-master/fill-plans/{plan_id}/apply")
def apply_fill_plan(plan_id: str, req: TemplateFillApplyRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_feature(current_user)
    try:
        result = _store.apply_fill_plan(db, plan_id=plan_id, user_id=current_user.id, expected_revision=req.expected_revision)
    except (TemplateFillPlanConflict, TemplateFillPlanNotConfirmed, TemplateFillPlanImmutable) as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    except TemplateFillError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "template_fill_plan_not_found"})
    return {"data": result}


@router.get("/ppt-master/template-fill-tasks/{task_id}")
def get_template_fill_task(task_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_feature(current_user)
    result = _store.get_fill_task(db, task_id=task_id, user_id=current_user.id)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "template_fill_task_not_found"})
    return {"data": result}


@router.post("/ppt-master/fill-plans/{plan_id}/confirm")
def confirm_fill_plan(plan_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_feature(current_user)
    result = _store.confirm_fill_plan(db, plan_id=plan_id, user_id=current_user.id)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "template_fill_plan_not_found"})
    return {"data": result}


@router.get("/ppt-master/templates/{template_id}/slides")
def template_slides(template_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_feature(current_user)
    result = _store.get_template(db, template_id=template_id, user_id=current_user.id)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "template_not_found"})
    return {"data": _store.get_template_slides(db, template_id=template_id, user_id=current_user.id) or []}
