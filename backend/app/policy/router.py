"""政策库与政策问答接口。

POST   /policy/documents            上传政策原文（PDF/DOCX/TXT），解析入库
GET    /policy/documents            政策列表（按状态/关键词筛选）
GET    /policy/documents/{id}       政策详情（含全部条款与元数据体检）
PATCH  /policy/documents/{id}       补录/修正元数据（文号、生效日期、状态、替代关系…）
DELETE /policy/documents/{id}       删除政策及其条款
POST   /policy/search               条款级检索（返回候选与分数，不生成结论）
POST   /policy/qa                   政策问答（有依据才作答，结论带 [n] 引用）
POST   /policy/qa/stream            同上，SSE 流式（先给证据，再逐块吐字）
GET    /policy/qa/logs              最近的问答留痕（审计）
GET    /policy/stats                政策库概览
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.errors import fail, ok
from app.models import User

from . import lifecycle, parser, qa, retrieval
from .models import ALL_STATUSES, PolicyClause, PolicyDocument, PolicyQaLog

router = APIRouter(prefix="/policy", tags=["policy"])

FILE_DIR = Path(__file__).resolve().parents[2] / "data" / "policy_files"
MAX_BYTES = 20 * 1024 * 1024

EDITABLE_FIELDS = (
    "title", "doc_no", "issuer", "source_url", "region", "target_audience", "theme",
    "publish_date", "effective_date", "expire_date", "status",
    "supersedes", "superseded_by", "revision_of", "version", "review_note",
)


def _get_or_404(db: Session, policy_id: int) -> PolicyDocument:
    doc = db.get(PolicyDocument, policy_id)
    if not doc:
        raise LookupError(f"政策不存在：{policy_id}")
    return doc


def _fail_parse(result: parser.ParseResult, hint: str) -> dict:
    """未切出条款时，把「抓到了多少字」一并回传，便于定位是文件问题还是规则问题。"""
    preview = (result.full_text or "").strip().replace("\n", " ")[:120]
    detail = (
        f"{hint}（已识别 {result.char_count} 字 / {result.page_count} 页，"
        f"未匹配到「第X条」或「一、」等条款编号）"
    )
    if result.ocr_used:
        detail += "。该文件无文字层，已尝试 OCR，识别质量可能不足，建议改用「粘贴正文」入库"
    return fail(400, detail, data={
        "char_count": result.char_count,
        "page_count": result.page_count,
        "ocr_used": result.ocr_used,
        "preview": preview,
        "parse_warnings": result.warnings,
    })


def _persist(db: Session, *, user: User, result: parser.ParseResult, payload: dict,
             file_name: str, file_path: str) -> dict:
    """把解析结果写入三张表；重复文件返回 409。"""
    dup = db.query(PolicyDocument).filter(PolicyDocument.checksum == result.checksum).first()
    if dup:
        return fail(409, f"该原文已入库：《{dup.title}》（ID {dup.id}）", data=dup.to_dict())

    raw_title = (payload.get("title") or "").strip()
    # 文件名是哈希（机器命名下载件常见）时不能当标题用
    if re.fullmatch(r"[0-9a-fA-F]{16,}", raw_title):
        raw_title = ""
    title = raw_title or result.suggested_title or file_name or "未命名政策"
    source_url, url_note = lifecycle.normalize_source_url(payload.get("source_url"))
    doc = PolicyDocument(
        title=title[:200],
        doc_no=(payload.get("doc_no") or "").strip(),
        issuer=(payload.get("issuer") or "").strip(),
        source_url=source_url,
        region=(payload.get("region") or "").strip(),
        target_audience=(payload.get("target_audience") or "").strip(),
        theme=(payload.get("theme") or "").strip(),
        publish_date=lifecycle.normalize_date(payload.get("publish_date")),
        effective_date=lifecycle.normalize_date(payload.get("effective_date")),
        expire_date=lifecycle.normalize_date(payload.get("expire_date")),
        status=lifecycle.derive_status(
            payload.get("effective_date"), payload.get("expire_date"),
            payload.get("status") or "", payload.get("superseded_by") or "",
        ),
        supersedes=(payload.get("supersedes") or "").strip(),
        superseded_by=(payload.get("superseded_by") or "").strip(),
        revision_of=(payload.get("revision_of") or "").strip(),
        version=(payload.get("version") or "").strip(),
        file_name=file_name,
        file_path=file_path,
        page_count=result.page_count,
        clause_count=len(result.clauses),
        char_count=result.char_count,
        checksum=result.checksum,
        created_by=getattr(user, "id", None),
    )
    db.add(doc)
    db.flush()

    for span in result.clauses:
        db.add(PolicyClause(
            policy_id=doc.id,
            seq=span.seq,
            clause_no=span.clause_no,
            chapter=span.chapter,
            heading=span.heading,
            content=span.content,
            page=span.page,
            char_start=span.char_start,
            char_end=span.char_end,
            checksum=span.checksum,
            search_text=parser.normalize_search_text(span.content),
        ))
    db.commit()
    db.refresh(doc)

    return ok(data={
        "document": doc.to_dict(),
        "clauses_preview": [c.to_dict() for c in doc.clauses[:5]],
        "parse_warnings": result.warnings + ([url_note] if url_note else []),
        "ocr_used": result.ocr_used,
        "lifecycle_issues": lifecycle.lifecycle_issues(doc),
    }, message="政策入库成功")


def _payload_from_form(**kwargs) -> dict:
    return {k: (v or "") for k, v in kwargs.items()}


@router.post("/documents")
def upload_policy(
    file: UploadFile = File(...),
    title: str = Form(""),
    doc_no: str = Form(""),
    issuer: str = Form(""),
    source_url: str = Form(""),
    region: str = Form(""),
    target_audience: str = Form(""),
    theme: str = Form(""),
    publish_date: str = Form(""),
    effective_date: str = Form(""),
    expire_date: str = Form(""),
    status: str = Form(""),
    supersedes: str = Form(""),
    superseded_by: str = Form(""),
    revision_of: str = Form(""),
    version: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in parser.SUPPORTED_SUFFIXES:
        return fail(400, f"不支持的文件类型 {suffix or '(无扩展名)'}，请上传 PDF / DOCX / TXT")

    raw = file.file.read()
    if not raw:
        return fail(400, "文件为空")
    if len(raw) > MAX_BYTES:
        return fail(400, "文件超过 20MB，请压缩后重试")

    FILE_DIR.mkdir(parents=True, exist_ok=True)
    stored = FILE_DIR / f"{uuid.uuid4().hex}{suffix}"
    stored.write_bytes(raw)

    try:
        result = parser.parse_policy(stored)
    except Exception as exc:
        stored.unlink(missing_ok=True)
        return fail(400, f"原文解析失败：{exc}")

    if not result.clauses:
        stored.unlink(missing_ok=True)
        return _fail_parse(result, "未识别到任何条款")

    payload = _payload_from_form(
        title=title, doc_no=doc_no, issuer=issuer, source_url=source_url, region=region,
        target_audience=target_audience, theme=theme, publish_date=publish_date,
        effective_date=effective_date, expire_date=expire_date, status=status,
        supersedes=supersedes, superseded_by=superseded_by, revision_of=revision_of,
        version=version,
    )
    resp = _persist(db, user=user, result=result, payload=payload,
                    file_name=file.filename or "", file_path=str(stored))
    if resp.get("code") != 0:
        stored.unlink(missing_ok=True)
    return resp


@router.post("/documents/text")
def upload_policy_text(payload: dict = Body(...), db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """粘贴正文入库：扫描件 OCR 不可靠时的兜底通道，也是网页政策的常用入口。"""
    text = str(payload.get("text") or payload.get("content") or "").strip()
    if len(text) < 50:
        return fail(400, "正文太短（少于 50 字），请粘贴完整政策原文")
    try:
        result = parser.parse_text(text)
    except Exception as exc:
        return fail(400, f"正文解析失败：{exc}")

    if not result.clauses:
        return _fail_parse(result, "正文未识别到条款")

    FILE_DIR.mkdir(parents=True, exist_ok=True)
    stored = FILE_DIR / f"{uuid.uuid4().hex}.txt"
    stored.write_text(text, encoding="utf-8")

    resp = _persist(db, user=user, result=result, payload=payload,
                    file_name="粘贴正文.txt", file_path=str(stored))
    if resp.get("code") != 0:
        stored.unlink(missing_ok=True)
    return resp


@router.get("/documents")
def list_policies(
    status: str = Query("", description="按状态筛选，留空为全部"),
    keyword: str = Query("", description="标题/文号/机关关键词"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(PolicyDocument)
    if status:
        query = query.filter(PolicyDocument.status == status)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (PolicyDocument.title.like(like))
            | (PolicyDocument.doc_no.like(like))
            | (PolicyDocument.issuer.like(like))
        )
    rows = query.order_by(PolicyDocument.id.desc()).limit(limit).all()
    return ok(data={"items": [d.to_dict() for d in rows], "total": len(rows)})


@router.get("/documents/{policy_id}")
def get_policy(policy_id: int, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    try:
        doc = _get_or_404(db, policy_id)
    except LookupError as exc:
        return fail(404, str(exc))
    return ok(data={
        "document": doc.to_dict(with_clauses=True),
        "lifecycle_issues": lifecycle.lifecycle_issues(doc),
        "relation": lifecycle.describe_relation(doc),
    })


@router.patch("/documents/{policy_id}")
def update_policy(policy_id: int, payload: dict = Body(...),
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    try:
        doc = _get_or_404(db, policy_id)
    except LookupError as exc:
        return fail(404, str(exc))

    url_note = ""
    for key in EDITABLE_FIELDS:
        if key not in payload:
            continue
        value = payload.get(key)
        if key in ("publish_date", "effective_date", "expire_date"):
            value = lifecycle.normalize_date(value)
        elif key == "source_url":
            value, note = lifecycle.normalize_source_url(value)
            if note:
                url_note = note
        else:
            value = ("" if value is None else str(value)).strip()
        setattr(doc, key, value)

    if "status" not in payload:
        doc.status = lifecycle.derive_status(
            doc.effective_date, doc.expire_date, doc.status, doc.superseded_by
        )
    db.commit()
    db.refresh(doc)
    return ok(data={
        "document": doc.to_dict(with_clauses=True),
        "lifecycle_issues": lifecycle.lifecycle_issues(doc),
        "meta_warnings": [url_note] if url_note else [],
    }, message="已更新" + ("（来源链接无效，未保存）" if url_note else ""))


@router.delete("/documents/{policy_id}")
def delete_policy(policy_id: int, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    try:
        doc = _get_or_404(db, policy_id)
    except LookupError as exc:
        return fail(404, str(exc))
    Path(doc.file_path).unlink(missing_ok=True) if doc.file_path else None
    db.delete(doc)
    db.commit()
    return ok(message="已删除")


@router.post("/search")
def search_clauses(payload: dict = Body(...), db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    question = str(payload.get("query") or payload.get("question") or "").strip()
    if not question:
        return fail(400, "检索内容不能为空")
    scope = str(payload.get("scope") or "current")
    policy_ids = payload.get("policy_ids") or None
    threshold = float(payload.get("threshold") or retrieval.DEFAULT_THRESHOLD)
    top_k = int(payload.get("top_k") or 12)

    candidates = retrieval.search(db, question, scope=scope, policy_ids=policy_ids, top_k=top_k)
    return ok(data={
        "items": [
            {**c.to_dict(index=i + 1),
             "below_threshold": c.score < threshold,
             "excerpt": retrieval.build_excerpt(c.clause.content, c.matched_terms)}
            for i, c in enumerate(candidates)
        ],
        "threshold": threshold,
        "scope": scope,
    })


@router.post("/qa")
def policy_qa(payload: dict = Body(...), db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    question = str(payload.get("question") or payload.get("query") or "").strip()
    if not question:
        return fail(400, "问题不能为空")
    result = qa.answer(
        db,
        question,
        scope=str(payload.get("scope") or "current"),
        policy_ids=payload.get("policy_ids") or None,
        include_deprecated=bool(payload.get("include_deprecated")),
        threshold=float(payload.get("threshold") or retrieval.DEFAULT_THRESHOLD),
        top_k=int(payload.get("top_k") or 12),
        user_id=getattr(user, "id", None),
    )
    return ok(data=result)


def _sse(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


@router.post("/qa/stream")
def policy_qa_stream(payload: dict = Body(...), user: User = Depends(get_current_user)):
    """流式问答。用独立会话，避免请求级 session 在流式响应期间被回收。"""
    question = str(payload.get("question") or payload.get("query") or "").strip()
    if not question:
        return fail(400, "问题不能为空")

    kwargs = {
        "scope": str(payload.get("scope") or "current"),
        "policy_ids": payload.get("policy_ids") or None,
        "include_deprecated": bool(payload.get("include_deprecated")),
        "threshold": float(payload.get("threshold") or retrieval.DEFAULT_THRESHOLD),
        "top_k": int(payload.get("top_k") or 12),
        "user_id": getattr(user, "id", None),
    }

    def event_stream():
        db = SessionLocal()
        try:
            for event in qa.answer_stream(db, question, **kwargs):
                yield _sse(event)
        except GeneratorExit:  # 客户端断开
            raise
        except Exception as exc:
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            db.close()
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/qa/logs")
def qa_logs(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    rows = db.query(PolicyQaLog).order_by(PolicyQaLog.id.desc()).limit(limit).all()
    items = []
    for row in rows:
        item = row.to_dict()
        try:
            item["citations"] = json.loads(row.citations_json or "[]")
        except Exception:
            item["citations"] = []
        items.append(item)
    return ok(data={"items": items})


@router.get("/stats")
def policy_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    total = db.query(PolicyDocument).count()
    by_status = {
        status: db.query(PolicyDocument).filter(PolicyDocument.status == status).count()
        for status in ALL_STATUSES
    }
    clauses = db.query(PolicyClause).count()
    qa_total = db.query(PolicyQaLog).count()
    qa_no_basis = db.query(PolicyQaLog).filter(PolicyQaLog.status == "no_basis").count()
    return ok(data={
        "documents": total,
        "clauses": clauses,
        "by_status": by_status,
        "qa_total": qa_total,
        "qa_no_basis": qa_no_basis,
    })
