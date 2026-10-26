from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.errors import ok
from . import service
from .schemas import Content, Update, Decision, Revision, ExportRequest, Generation, CitationSelection
from .materials import router as material_router
from .entry import router as entry_router

router = APIRouter(prefix="/gov", tags=["government"])
router.include_router(material_router)
router.include_router(entry_router)


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
    return ok({"origin": "backend", "modelMode": mode, "label": "后端已连接 · 模型可用性需单独确认", "detail": "通知支持双层审校和内部草稿；政策库已接入。正式发文未开放。"})


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


@router.post("/documents/{document_id}/citations")
def select_citations(document_id: str, body: CitationSelection, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .policy_refs import select
    return ok(select(db, user, document_id, body))


@router.post("/documents/{document_id}/approve")
def approve(document_id: str, body: Decision, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(service.transition(db, user, document_id, body, "approve"))


@router.post("/documents/{document_id}/return")
def return_document(document_id: str, body: Decision, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(service.transition(db, user, document_id, body, "return"))


@router.post("/documents/{document_id}/check")
def check(document_id: str, body: Revision, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .proofread import check as run_check
    return ok(run_check(db, user, document_id, body.version))


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
    payload = json.loads(doc.payload_json)
    from .policy_refs import references
    payload["policyRefs"] = references(payload.get("citationIds", []), snapshot=payload.get("_citationSnapshot", []))
    if payload.get("docType", "notice") == "notice":
        from .proofread import notice, review
        from .export import notice_docx
        payload["_review"] = review(doc.id, payload)
        content = notice_docx(notice(doc.id, payload), payload)
    else:
        content = internal_docx(payload)
    service.record(db, doc, user, "导出内部草稿", "带内部草稿标识，不能作为正式文件使用")
    db.commit()
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="draft-{doc.id}.docx"', "Cache-Control": "private, no-store"})
