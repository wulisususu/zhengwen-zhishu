"""File management."""
import logging
import os, uuid
from fastapi import APIRouter, UploadFile, File as F, Depends, Query, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import File, User
from app.deps import get_current_user
from app.errors import ok, fail, ERR_INTERNAL, ERR_NOT_FOUND
from app.services.file_parse_service import create_file_parse_task, get_parse_task, get_parsed_file, should_auto_parse_on_upload
from app.services.pandawiki_sync_service import create_pandawiki_sync_task
from app.services.artifact_service import (
    ArtifactExpiredError,
    ArtifactNotFoundError,
    ArtifactSecurityError,
    ArtifactService,
)

UPLOAD_DIR = "/home/youyeetoo/InNet_box/backend/data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])
artifact_service = ArtifactService()


@router.post("/upload")
async def upload_file(file: UploadFile = F(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ext = os.path.splitext(file.filename)[1]
    saved_name = uuid.uuid4().hex + ext
    path = os.path.join(UPLOAD_DIR, saved_name)
    with open(path, "wb") as f:
        f.write(await file.read())
    size = os.path.getsize(path)
    rec = File(user_id=user.id, filename=file.filename, filepath=path, filesize=size, filetype=ext)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    parse_task = None
    if should_auto_parse_on_upload(rec.filename):
        parse_task = create_file_parse_task(rec.id, user.id)
    try:
        create_pandawiki_sync_task(rec.id, user.id)
    except Exception:
        # PandaWiki sync is best-effort and must not block the primary upload flow.
        logger.exception("Failed to enqueue PandaWiki sync for file %s", rec.id)
    return ok(data={
        "id": rec.id,
        "filename": rec.filename,
        "size": rec.filesize,
        "type": rec.filetype,
        "download_url": f"/api/v1/files/{rec.id}/download",
        "parse_task": parse_task,
    })


@router.get("")
def list_files(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    files = db.query(File).filter(File.user_id == user.id).order_by(File.id.desc()).all()
    return ok(data=[{"id": f.id, "filename": f.filename, "type": f.filetype, "size": f.filesize, "created_at": f.created_at.isoformat()} for f in files])


@router.get("/{file_id}")
def get_file(file_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.query(File).filter(File.id == file_id, File.user_id == user.id).first()
    if not f:
        return fail(ERR_NOT_FOUND, "file not found")
    return ok(data={"id": f.id, "filename": f.filename, "type": f.filetype, "size": f.filesize, "created_at": f.created_at.isoformat()})


@router.post("/{file_id}/parse")
def parse_file(file_id: int, body: dict | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.query(File).filter(File.id == file_id, File.user_id == user.id).first()
    if not f:
        return fail(ERR_NOT_FOUND, "file not found")
    try:
        task = create_file_parse_task(file_id, user.id, force=bool((body or {}).get("force")))
        if not task:
            return fail(ERR_NOT_FOUND, "file not found")
        return ok(data={"task": task})
    except Exception as exc:
        return fail(ERR_INTERNAL, str(exc))


@router.get("/{file_id}/parse-tasks/{task_id}")
def file_parse_task_status(file_id: int, task_id: str, user: User = Depends(get_current_user)):
    task = get_parse_task(task_id, user_id=user.id, file_id=file_id)
    if not task:
        return fail(ERR_NOT_FOUND, "parse task not found")
    return ok(data=task)


@router.get("/{file_id}/parsed")
def parsed_file(file_id: int, include_markdown: bool = Query(False), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.query(File).filter(File.id == file_id, File.user_id == user.id).first()
    if not f:
        return fail(ERR_NOT_FOUND, "file not found")
    parsed = get_parsed_file(file_id, user.id, include_markdown=include_markdown)
    if not parsed:
        return fail(ERR_NOT_FOUND, "parsed file not found")
    return ok(data=parsed)


@router.get("/{file_id}/download")
def download_file(file_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        record = artifact_service.get_downloadable(db, file_id, owner_user_id=user.id)
        path = artifact_service.download_path(record)
    except ArtifactExpiredError as exc:
        raise HTTPException(status_code=410, detail="file expired") from exc
    except (ArtifactNotFoundError, ArtifactSecurityError) as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    media_type = artifact_service.media_type_for(record)
    return FileResponse(
        str(path),
        filename=record.filename,
        media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.put("/{file_id}")
def update_file(file_id: int, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.query(File).filter(File.id == file_id, File.user_id == user.id).first()
    if not f:
        return fail(ERR_NOT_FOUND, "file not found")
    if "filename" in body:
        f.filename = body["filename"]
    db.commit()
    return ok(data={"id": f.id, "filename": f.filename})


@router.delete("/{file_id}")
def delete_file(file_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.query(File).filter(File.id == file_id, File.user_id == user.id).first()
    if not f:
        return fail(ERR_NOT_FOUND, "file not found")
    from app.gov.models import GovDocumentMaterial
    if db.query(GovDocumentMaterial).filter_by(file_id=file_id).first():
        raise HTTPException(409, "材料已关联政务文稿，请先在可编辑文稿中解除关联")
    if os.path.exists(f.filepath):
        os.remove(f.filepath)
    db.delete(f)
    db.commit()
    return ok(message="deleted")
