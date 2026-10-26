from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.errors import ok
from . import service
from .schemas import Content, Update, Decision, Revision, ExportRequest, Generation
from .materials import router as material_router

router = APIRouter(prefix="/gov", tags=["government"])
router.include_router(material_router)


@router.get("/actor")
def actor(user: User = Depends(get_current_user)):
    return ok(service.actor(user))


@router.get("/runtime")
def runtime(user: User = Depends(get_current_user)):
    from app.config import get_config
    try:
        mode = get_config().get("model_policy", {}).get("mode", "unknown")
    except (OSError, KeyError):
        mode = "unknown"
    if mode not in {"cloud_allowed", "intranet", "offline"}:
        mode = "unknown"
    return ok({"origin": "backend", "modelMode": mode, "label": "后端已连接 · 模型可用性未验证", "detail": "人工审核已接入；政策检索与自动审校未接入。"})


@router.get("/documents")
def documents(keyword: str = "", docType: str = "all", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    docs = [service.serialize(db, d) for d in service.visible_query(db, user).order_by(service.GovDocument.updated_at.desc()).all()]
    return ok([d for d in docs if (not keyword or keyword in d["title"]) and (docType == "all" or d["docType"] == docType)])


@router.post("/documents")
def create(body: Content, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(service.create(db, user, body))


@router.get("/documents/{document_id}")
def get(document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(service.serialize(db, service.get_document(db, user, document_id)))


@router.put("/documents/{document_id}")
def save(document_id: str, body: Update, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(service.save(db, user, document_id, body))


@router.post("/documents/{document_id}/submit")
def submit(document_id: str, body: Decision, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(service.transition(db, user, document_id, body, "submit"))


@router.post("/documents/{document_id}/approve")
def approve(document_id: str, body: Decision, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(service.transition(db, user, document_id, body, "approve"))


@router.post("/documents/{document_id}/return")
def return_document(document_id: str, body: Decision, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(service.transition(db, user, document_id, body, "return"))


@router.post("/documents/{document_id}/check")
def check(document_id: str, body: Revision, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service.get_document(db, user, document_id)
    raise HTTPException(503, "自动审校未接入，本期仅支持人工审核")


@router.post("/documents/{document_id}/generate")
def generate(document_id: str, body: Generation, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .generation import generate as run_generation
    return ok(run_generation(db, user, document_id, body))


@router.post("/documents/{document_id}/export")
def export(document_id: str, body: ExportRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    import json
    from fastapi.responses import Response
    from .export import internal_docx
    doc = service.get_document(db, user, document_id)
    if body.kind == "formal":
        raise HTTPException(403, "正式发文权限尚未配置，仅支持内部草稿")
    content = internal_docx(json.loads(doc.payload_json))
    service.record(db, doc, user, "导出内部草稿", "带内部草稿标识，不能作为正式文件使用")
    db.commit()
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="draft-{doc.id}.docx"', "Cache-Control": "private, no-store"})
