"""Authenticated editor draft endpoints for incremental PPT projects."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.PPT_master.media_assets import MediaAssetError, PptMediaAdapter, PptMediaResolver
from app.PPT_master.native_data import build_chart_from_rows, build_table_from_rows, has_native_elements, load_tabular_file
from app.models import File
from app.PPT_master.editor_documents import (
    EditorDocumentConflict, EditorDocumentNotFound, EditorDocumentStore, EditorExportConflict,
    EditorExportFailed, EditorExportStore, EditorProjectStore,
)


router = APIRouter(tags=["ppt-master"])
_store = EditorDocumentStore()
_projects = EditorProjectStore()
_exports = EditorExportStore()
_media = PptMediaResolver()
_media_adapter = PptMediaAdapter()


def _require_feature(current_user, environment_name: str) -> None:
    allowed = {value.strip() for value in os.environ.get(environment_name, "123").split(",") if value.strip()}
    if str(getattr(current_user, "username", "")) not in allowed:
        raise HTTPException(status_code=404, detail={"code": "ppt_feature_unavailable"})


def _require_p0_feature(current_user) -> None:
    _require_feature(current_user, "PPT_P0_ALLOWED_USERS")


def _require_media_feature(current_user) -> None:
    _require_feature(current_user, "PPT_MEDIA_PROVIDED_ALLOWED_USERS")


def _require_native_data_feature(current_user) -> None:
    _require_feature(current_user, "PPT_NATIVE_CHARTS_TABLES_ALLOWED_USERS")


class EditorSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    document: dict


class EditorExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class EditorMediaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: int = Field(gt=0)
    source_type: str
    source_file_id: int | None = Field(default=None, gt=0)


class EditorDocumentMediaExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_file_id: int = Field(gt=0)


class EditorNativeDataImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: int = Field(gt=0)
    kind: str
    chart_type: str = "column"
    title: str = ""


@router.get("/ppt-master/projects/{project_id}/media")
def list_project_media(project_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_media_feature(current_user)
    return {"data": _media.manifest(db, project_id=project_id, owner_user_id=current_user.id)}


@router.post("/ppt-master/projects/{project_id}/media")
def register_project_media(project_id: str, req: EditorMediaRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_media_feature(current_user)
    try:
        return {"data": _media.register_file(db, file_id=req.file_id, owner_user_id=current_user.id, source_type=req.source_type, project_id=project_id, source_file_id=req.source_file_id)}
    except MediaAssetError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc


@router.post("/ppt-master/projects/{project_id}/media/extract")
def extract_project_document_media(project_id: str, req: EditorDocumentMediaExtractRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_media_feature(current_user)
    try:
        return {"data": _media_adapter.extract_document_images(
            db, project_id=project_id, owner_user_id=current_user.id, source_file_id=req.source_file_id,
        )}
    except MediaAssetError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc


@router.post("/ppt-master/projects/{project_id}/native-data/import")
def import_native_data(project_id: str, req: EditorNativeDataImportRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_p0_feature(current_user)
    _require_native_data_feature(current_user)
    source = db.query(File).filter(File.id == req.file_id, File.owner_user_id == current_user.id).first()
    if source is None or not (source.real_path or source.filepath):
        raise HTTPException(status_code=404, detail={"code": "native_tabular_file_not_found"})
    try:
        rows = load_tabular_file(source.real_path or source.filepath, source.mime_type or "")
        source_ref = {"file_id": source.id, "sheet": "Sheet1", "range": f"A1:{len(rows[0])}x{len(rows)}"}
        if req.kind == "table":
            data = build_table_from_rows(rows, source_ref=source_ref)
        elif req.kind == "chart":
            data = build_chart_from_rows(rows, chart_type=req.chart_type, source_ref=source_ref, title=req.title)
        else:
            raise ValueError("native_import_kind_invalid")
        return {"data": data}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc


@router.post("/ppt-master/projects/{project_id}/editor/export")
def export_editor_document(project_id: str, req: EditorExportRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_p0_feature(current_user)
    try:
        return {"data": _exports.export(db, project_id=project_id, user_id=current_user.id, expected_revision=req.expected_revision)}
    except EditorDocumentNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "editor_project_not_found"}) from exc
    except EditorExportConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "editor_revision_conflict", "revision": exc.revision}) from exc
    except EditorExportFailed as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc


@router.get("/ppt-master/projects/{project_id}/editor/exports")
def list_editor_exports(project_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_p0_feature(current_user)
    return {"data": _exports.list(db, project_id=project_id, user_id=current_user.id)}


@router.get("/ppt-master/projects/recent")
@router.get("/ppt-master/projects")
def list_editor_projects(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_p0_feature(current_user)
    return {"data": _projects.recent(db, user_id=current_user.id)}


@router.get("/ppt-master/projects/{project_id}/history")
def get_history_project(project_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_p0_feature(current_user)
    try:
        return {"data": _projects.history(db, project_id=project_id, user_id=current_user.id)}
    except EditorDocumentNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "editor_project_not_found"}) from exc


@router.get("/ppt-master/projects/{project_id}/editor")
def get_editor_document(project_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_p0_feature(current_user)
    try:
        return {"data": _store.get_or_initialize(db, project_id=project_id, user_id=current_user.id)}
    except EditorDocumentNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "editor_project_not_found"}) from exc


@router.patch("/ppt-master/projects/{project_id}/editor")
def save_editor_document(project_id: str, req: EditorSaveRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_p0_feature(current_user)
    if has_native_elements(req.document):
        _require_native_data_feature(current_user)
    try:
        return {"data": _store.save(
            db,
            project_id=project_id,
            user_id=current_user.id,
            expected_revision=req.expected_revision,
            document=req.document,
        )}
    except EditorDocumentNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "editor_project_not_found"}) from exc
    except EditorDocumentConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "editor_revision_conflict", "revision": exc.revision}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
