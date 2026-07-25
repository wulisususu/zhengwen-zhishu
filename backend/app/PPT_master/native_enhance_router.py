"""Authenticated endpoints for non-destructive native PPTX enhancement."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import File
from app.PPT_master.native_enhance import analyze_native_pptx
from app.PPT_master.native_enhance_store import NativeEnhanceError, NativeEnhanceStore

router = APIRouter(tags=["ppt-master-native-enhance"])


def _require_feature(current_user) -> None:
    allowed = {item.strip() for item in os.environ.get("PPT_NATIVE_ENHANCE_ALLOWED_USERS", "123").split(",") if item.strip()}
    if str(getattr(current_user, "username", "")) not in allowed:
        raise HTTPException(status_code=404, detail={"code": "ppt_feature_unavailable"})


class NativeEnhanceAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_file_id: int = Field(gt=0)


class NativeEnhanceFieldOptions(BaseModel):
    """A bounded, schema-checked footer field configuration."""
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    text: str | None = Field(default=None, max_length=500)
    font_size_pt: int = Field(default=9, ge=6, le=48)
    color: str = Field(default="64748B", min_length=6, max_length=6)
    position: Literal["bottom_left", "bottom_center", "bottom_right"] = "bottom_right"
    application_scope: Literal["all", "selected"] = "all"
    slide_ids: list[int] = Field(default_factory=list, max_length=500)

    @field_validator("color")
    @classmethod
    def color_is_hex(cls, value: str) -> str:
        if any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError("native_enhance_color_invalid")
        return value.upper()

    @field_validator("slide_ids")
    @classmethod
    def valid_field_slide_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("native_enhance_slide_id_invalid")
        return sorted(set(values))


class NativeEnhanceOptions(BaseModel):
    """Only supported OOXML mutations reach the enhancer."""
    model_config = ConfigDict(extra="forbid")
    transition_type: Literal["keep", "none", "fade", "push", "wipe", "split", "cover"] = "keep"
    duration_ms: int = Field(default=500, ge=0, le=5000)
    advance_on_click: bool = True
    auto_advance_ms: int | None = Field(default=None, ge=1, le=3_600_000)
    application_scope: Literal["all", "missing_only", "selected"] = "all"
    slide_ids: list[int] = Field(default_factory=list, max_length=500)
    page_number: NativeEnhanceFieldOptions | None = None
    footer: NativeEnhanceFieldOptions | None = None
    date: NativeEnhanceFieldOptions | None = None
    document_properties: dict[str, str] | None = None
    remove_external_relationships: bool = False

    @field_validator("slide_ids")
    @classmethod
    def valid_slide_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("native_enhance_slide_id_invalid")
        return sorted(set(values))


class NativeEnhanceTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_file_id: int = Field(gt=0)
    expected_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    options: NativeEnhanceOptions = Field(default_factory=NativeEnhanceOptions)


@router.post("/ppt-master/enhance/analyze")
def analyze_existing_ppt(req: NativeEnhanceAnalyzeRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_feature(current_user)
    source = db.query(File).filter(File.id == req.source_file_id, File.owner_user_id == current_user.id).first()
    path = Path(source.real_path or source.filepath) if source is not None else None
    if source is None or path is None or not path.is_file() or path.suffix.lower() != ".pptx":
        raise HTTPException(status_code=404, detail={"code": "native_enhance_source_not_found"})
    try:
        return {"data": analyze_native_pptx(path)}
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "native_enhance_analysis_failed"}) from exc


@router.post("/ppt-master/enhance/tasks")
def create_native_enhance_task(req: NativeEnhanceTaskRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_feature(current_user)
    try:
        return {"data": NativeEnhanceStore().create_task(db, user_id=current_user.id, source_file_id=req.source_file_id, expected_sha256=req.expected_sha256, options=req.options.model_dump(exclude_none=True))}
    except NativeEnhanceError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc


@router.get("/ppt-master/enhance/tasks/{task_id}")
def get_native_enhance_task(task_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_feature(current_user)
    task = NativeEnhanceStore().get_task(db, task_id=task_id, user_id=current_user.id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "native_enhance_task_not_found"})
    return {"data": task}


@router.get("/ppt-master/enhance/tasks/{task_id}/result")
def get_native_enhance_result(task_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return get_native_enhance_task(task_id, current_user, db)
