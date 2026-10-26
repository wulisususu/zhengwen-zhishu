import json
import uuid
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import or_, update
from sqlalchemy.orm import Session
from app.models import User, File
from .models import GovDocument, GovDocumentMaterial, GovReviewRecord


def actor(user):
    return {"origin": "backend", "account": user.username, "name": user.nickname or user.username,
            "department": "", "roles": ["drafter", "reviewer"] if user.is_admin else ["drafter"], "canFormalIssue": False}


def visible_query(db, user):
    q = db.query(GovDocument)
    if user.is_admin:
        return q.filter(or_(GovDocument.owner_user_id == user.id, GovDocument.status != "draft"))
    return q.filter(GovDocument.owner_user_id == user.id)


def get_document(db, user, document_id):
    doc = visible_query(db, user).filter(GovDocument.id == document_id).first()
    if not doc:
        raise HTTPException(404, "文稿不存在或无权访问")
    return doc


def editable(doc, user):
    if doc.owner_user_id != user.id:
        raise HTTPException(403, "只能修改自己起草的文稿")
    if doc.status not in {"draft", "returned"}:
        raise HTTPException(409, "文稿已锁定，不能修改")


def record(db, doc, user, action, note="", tone="neutral"):
    db.add(GovReviewRecord(id=uuid.uuid4().hex, document_id=doc.id, actor_user_id=user.id,
                          action=action, note=note, tone=tone))


def write_revision(db, doc, version, *, payload=None, status=None):
    """Compare-and-swap in SQLite, not an unprotected read followed by commit."""
    values = {"version": version + 1, "updated_at": datetime.utcnow()}
    if payload is not None:
        values["payload_json"] = json.dumps(payload, ensure_ascii=False)
    if status is not None:
        values["status"] = status
    result = db.execute(update(GovDocument).where(GovDocument.id == doc.id, GovDocument.version == version).values(**values), execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "文稿已更新，请刷新后重试")
    db.flush()
    db.refresh(doc)


def material(file):
    return {"id": str(file.id), "name": file.filename, "meta": f"{file.filetype} · {file.filesize} 字节 · 已上传，解析状态需单独确认", "downloadUrl": f"/api/v1/gov/materials/{file.id}/download"}


def serialize(db, doc):
    payload = json.loads(doc.payload_json)
    owner = db.get(User, doc.owner_user_id)
    records = db.query(GovReviewRecord).filter_by(document_id=doc.id).order_by(GovReviewRecord.at, GovReviewRecord.id).all()
    files = db.query(File).join(GovDocumentMaterial, GovDocumentMaterial.file_id == File.id).filter(GovDocumentMaterial.document_id == doc.id).order_by(File.id).all()
    blocks = [{"id": f"{doc.id}-p{i}", "kind": "paragraph", "section": "正文",
               "segments": [{"kind": "text", "id": f"{doc.id}-s{i}", "text": text}]}
              for i, text in enumerate(payload.get("body", "").splitlines()) if text.strip()]
    return {**payload, "id": doc.id, "origin": "backend", "status": doc.status, "version": doc.version,
            "docNumber": {"id": doc.id + "-number", "text": ""}, "blocks": blocks,
            "author": owner.nickname or owner.username, "authorAccount": owner.username, "department": "",
            "createdAt": doc.created_at.isoformat(), "materials": [material(f) for f in files],
            "policyRefs": [], "issues": [], "resolutions": {}, "lastReviewedAt": "", "checkStatus": "not_run",
            "history": [{"id": r.id, "action": r.action, "actor": (db.get(User, r.actor_user_id).nickname or db.get(User, r.actor_user_id).username), "at": r.at.isoformat(), "tone": r.tone, "note": r.note} for r in records]}


def create(db, user, body):
    doc = GovDocument(id=uuid.uuid4().hex, owner_user_id=user.id, status="draft", version=1,
                      payload_json=json.dumps(body.model_dump(), ensure_ascii=False))
    db.add(doc)
    db.flush()
    record(db, doc, user, "创建文稿")
    db.commit()
    return serialize(db, doc)


def save(db, user, document_id, body):
    doc = get_document(db, user, document_id)
    editable(doc, user)
    payload = json.loads(doc.payload_json)
    patch = body.model_dump(exclude_unset=True, exclude={"version"})
    if any(v is None for v in patch.values()):
        raise HTTPException(422, "文稿字段不能为 null")
    payload.update(patch)
    from .schemas import Content
    payload = Content.model_validate(payload).model_dump()
    write_revision(db, doc, body.version, payload=payload)
    record(db, doc, user, "保存草稿")
    db.commit()
    return serialize(db, doc)


def transition(db, user, document_id, body, action):
    doc = get_document(db, user, document_id)
    if action == "submit":
        editable(doc, user)
        if not json.loads(doc.payload_json).get("body", "").strip():
            raise HTTPException(422, "请填写正文后再送审")
        target, label, note = "pending", "提交审核", "自动审校未接入；提交人工审核"
    else:
        if not user.is_admin or doc.owner_user_id == user.id:
            raise HTTPException(403, "需要非起草人的审核人操作")
        if doc.status != "pending":
            raise HTTPException(409, "仅待审核文稿可以审核")
        if action == "return" and not body.opinion.strip():
            raise HTTPException(422, "退回修改须填写意见")
        target, label = ("approved", "审核通过") if action == "approve" else ("returned", "退回修改")
        note = "人工审核；自动审校未接入。" + body.opinion.strip()
    write_revision(db, doc, body.version, status=target)
    record(db, doc, user, label, note, "success" if target == "approved" else "info")
    db.commit()
    return serialize(db, doc)
