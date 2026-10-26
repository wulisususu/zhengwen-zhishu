import os
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File as Upload, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user
from app.models import User, File
from app.errors import ok
from .models import GovDocument, GovDocumentMaterial
from .schemas import Materials
from . import service

router = APIRouter()
MAX_UPLOAD = 20 * 1024 * 1024
ALLOWED = {".txt", ".md", ".pdf", ".docx", ".xlsx", ".csv", ".pptx", ".png", ".jpg", ".jpeg"}


@router.get("/materials")
def list_materials(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok([service.material(f) for f in db.query(File).filter_by(user_id=user.id).order_by(File.id.desc()).all()])


@router.post("/materials")
async def upload_material(file: UploadFile = Upload(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = Path((file.filename or "").replace("\\", "/")).name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(422, "不支持的材料类型")
    root = Path(os.environ.get("GOV_DATA_DIR") or Path(__file__).resolve().parents[2] / "data/gov-materials")
    root.mkdir(parents=True, exist_ok=True)
    path = root / (uuid.uuid4().hex + ext)
    size = 0
    try:
        with path.open("xb") as out:
            while chunk := await file.read(65536):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "材料不能超过20MiB")
                out.write(chunk)
        if not size:
            raise HTTPException(422, "材料不能为空")
        rec = File(user_id=user.id, owner_user_id=user.id, filename=name, filepath=str(path.resolve()), real_path=str(path.resolve()),
                   filesize=size, size=size, filetype=ext, mime_type=file.content_type)
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return ok(service.material(rec))
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.get("/materials/{file_id}/download")
def download(file_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rec = db.get(File, file_id)
    allowed = rec is not None and rec.user_id == user.id
    if rec is not None and user.is_admin and not allowed:
        allowed = db.query(GovDocumentMaterial).join(GovDocument).filter(GovDocumentMaterial.file_id == file_id, GovDocument.status != "draft").first() is not None
    if not allowed or not rec or not Path(rec.filepath).is_file():
        raise HTTPException(404, "材料不存在或无权下载")
    return FileResponse(rec.filepath, filename=rec.filename, media_type="application/octet-stream", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.post("/documents/{document_id}/materials")
def associate(document_id: str, body: Materials, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = service.get_document(db, user, document_id)
    service.editable(doc, user)
    ids = set(body.fileIds)
    files = db.query(File).filter(File.id.in_(ids), File.user_id == user.id).all()
    if len(files) != len(ids):
        raise HTTPException(404, "材料不存在或不属于当前用户")
    service.write_revision(db, doc, body.version)
    for fid in ids:
        if not db.get(GovDocumentMaterial, (doc.id, fid)):
            db.add(GovDocumentMaterial(document_id=doc.id, file_id=fid))
    service.record(db, doc, user, "添加材料", f"{len(ids)}份")
    db.commit()
    return ok(service.serialize(db, doc))


@router.delete("/documents/{document_id}/materials/{file_id}")
def unlink(document_id: str, file_id: int, version: int = Query(ge=1), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = service.get_document(db, user, document_id)
    service.editable(doc, user)
    link = db.get(GovDocumentMaterial, (doc.id, file_id))
    if not link:
        raise HTTPException(404, "材料关联不存在")
    service.write_revision(db, doc, version)
    db.delete(link)
    service.record(db, doc, user, "移除材料", "仅解除关联，原文件保留")
    db.commit()
    return ok(service.serialize(db, doc))
