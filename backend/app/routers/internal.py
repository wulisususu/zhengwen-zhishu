"""Internal bridge endpoints for OpenClaw option A integration."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import fail, ok, ERR_INTERNAL, ERR_NOT_FOUND, ERR_PARAM
from app.internal_auth import require_internal_service
from app.kb.kb_manager import KnowledgeBase
from app.models import Conversation, File
from app.routers.asr import _recognize_saved_path
from app.routers.tts import build_tts_audio_url
from app.services.document_tasks import create_document_task, get_task
from app.services.file_parse_service import create_file_parse_task, get_parse_task, get_parsed_file
from app.services.tts_service import synthesize as synthesize_tts
from app.services.voice_artifacts import store_tts_artifact
from app.services.local_small_model import generate as local_small_generate, VALID_MODES
from app.services.document_service import classify_document
from app.services.openclaw_gateway import compact_document_filename

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_service)])
_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".webm"}


def _normalize_file_refs(raw_files) -> list[int]:
    if raw_files is None:
        return []
    if isinstance(raw_files, (int, str)):
        raw_files = [raw_files]
    result: list[int] = []
    if isinstance(raw_files, list):
        for item in raw_files:
            if isinstance(item, dict):
                item = item.get("id") or item.get("file_id")
            try:
                file_id = int(item)
            except Exception:
                continue
            if file_id > 0 and file_id not in result:
                result.append(file_id)
    return result


def _resolve_attachment_context(db: Session, file_ids: list[int], conversation_user_id: int) -> tuple[list[File], str]:
    if not file_ids:
        return [], ""
    files = db.query(File).filter(File.user_id == conversation_user_id, File.id.in_(file_ids)).all()
    files_by_id = {file.id: file for file in files}
    ordered = [files_by_id[file_id] for file_id in file_ids if file_id in files_by_id]
    if not ordered:
        return [], ""

    parts: list[str] = []
    for file in ordered:
        task = create_file_parse_task(file.id, conversation_user_id, force=False)
        if task and task.get("status") == "done":
            parsed = get_parsed_file(file.id, conversation_user_id, include_markdown=True) or {}
            title = parsed.get("title") or file.filename
            markdown = parsed.get("markdown") or ""
            parts.append(f"## 附件: {title}\n{markdown}".strip())
    return ordered, "\n\n".join(part for part in parts if part).strip()


@router.post("/doc-tasks")
def create_internal_doc_task(body: dict, db: Session = Depends(get_db)):
    conversation_id = body.get("conversation_id")
    requester_user_id = body.get("user_id")
    instruction = (body.get("instruction") or body.get("prompt") or "").strip()
    file_ids = _normalize_file_refs(body.get("attachments") or body.get("file_ids"))

    if not conversation_id:
        return fail(ERR_PARAM, "conversation_id is required")
    if requester_user_id is None:
        return fail(ERR_PARAM, "user_id is required")
    if not instruction:
        return fail(ERR_PARAM, "instruction is required")

    try:
        requester_user_id = int(requester_user_id)
    except Exception:
        return fail(ERR_PARAM, "user_id must be an integer")

    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        return fail(ERR_NOT_FOUND, "conversation not found")
    if conv.user_id != requester_user_id:
        return fail(ERR_NOT_FOUND, "conversation not found")

    _, attachment_context = _resolve_attachment_context(db, file_ids, conv.user_id)
    user_input = instruction if not attachment_context else f"{instruction}\n\n以下是用户上传附件的解析内容：\n{attachment_context}"
    content_schema = None
    content = str(body.get("content") or "").strip()
    if content:
        content_schema = {
            "filename": str(body.get("filename") or "").strip(),
            "format": str(body.get("format") or "docx").strip() or "docx",
            "content_type": str(body.get("content_type") or "markdown").strip() or "markdown",
            "content": content,
        }

    try:
        task = create_document_task(
            user_input,
            conv.user_id,
            content_schema=content_schema,
            conversation_id=conv.id,
            workflow_type="document",
        )
        return ok(data=task)
    except Exception as exc:
        return fail(ERR_INTERNAL, str(exc))


@router.post("/document-render-docx")
def internal_document_render_docx(body: dict, db: Session = Depends(get_db)):
    conversation_id = body.get("conversation_id")
    requester_user_id = body.get("user_id")
    instruction = (body.get("instruction") or body.get("prompt") or body.get("title") or "生成文档").strip()
    content = str(body.get("content") or "").strip()
    content_type = str(body.get("content_type") or "markdown").strip().lower() or "markdown"
    filename = str(body.get("filename") or "").strip()
    file_ids = _normalize_file_refs(body.get("attachments") or body.get("file_ids"))

    if not conversation_id:
        return fail(ERR_PARAM, "conversation_id is required")
    if requester_user_id is None:
        return fail(ERR_PARAM, "user_id is required")
    if not content:
        return fail(ERR_PARAM, "content is required")
    if content_type not in {"markdown", "html", "plaintext"}:
        return fail(ERR_PARAM, "content_type must be markdown, html, or plaintext")

    try:
        requester_user_id = int(requester_user_id)
    except Exception:
        return fail(ERR_PARAM, "user_id must be an integer")

    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv or conv.user_id != requester_user_id:
        return fail(ERR_NOT_FOUND, "conversation not found")

    _, attachment_context = _resolve_attachment_context(db, file_ids, conv.user_id)
    user_input = instruction if not attachment_context else f"{instruction}\n\n以下是用户上传附件的解析内容：\n{attachment_context}"
    content_schema = {
        "filename": filename or (compact_document_filename(instruction, content) + ".docx"),
        "format": "docx",
        "content_type": content_type,
        "content": content,
    }

    try:
        task = create_document_task(
            user_input,
            conv.user_id,
            content_schema=content_schema,
            conversation_id=conv.id,
            workflow_type="document",
        )
        return ok(data=task)
    except Exception as exc:
        return fail(ERR_INTERNAL, str(exc))


@router.get("/doc-tasks/{task_id}")
def internal_doc_task_status(task_id: str):
    task = get_task(task_id)
    if not task:
        return fail(ERR_NOT_FOUND, "task not found")
    return ok(data=task)


@router.post("/kb/search")
def internal_kb_search(body: dict):
    query = (body.get("query") or "").strip()
    top_k = int(body.get("top_k") or 5)
    if not query:
        return fail(ERR_PARAM, "query is required")

    try:
        kb = KnowledgeBase()
        results = kb.search(query, top_k=top_k)
        sources = [
            {
                "chunk_id": item.get("chunk_id"),
                "filename": item.get("filename"),
                "score": item.get("score"),
                "chunk_text": item.get("chunk_text"),
            }
            for item in results
        ]
        return ok(data={"passages": results, "sources": sources})
    except Exception as exc:
        return fail(ERR_INTERNAL, str(exc))


@router.post("/file-parse")
def internal_file_parse(body: dict, db: Session = Depends(get_db)):
    conversation_id = body.get("conversation_id")
    requester_user_id = body.get("user_id")
    file_id = body.get("file_id")
    force = bool(body.get("force"))
    if not conversation_id:
        return fail(ERR_PARAM, "conversation_id is required")
    if requester_user_id is None:
        return fail(ERR_PARAM, "user_id is required")
    if not file_id:
        return fail(ERR_PARAM, "file_id is required")

    try:
        requester_user_id = int(requester_user_id)
    except Exception:
        return fail(ERR_PARAM, "user_id must be an integer")

    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        return fail(ERR_NOT_FOUND, "conversation not found")
    if conv.user_id != requester_user_id:
        return fail(ERR_NOT_FOUND, "conversation not found")

    try:
        task = create_file_parse_task(int(file_id), conv.user_id, force=force)
    except Exception as exc:
        return fail(ERR_INTERNAL, str(exc))
    if not task:
        return fail(ERR_NOT_FOUND, "file not found")
    return ok(data=task)


@router.post("/attachment-parse")
def internal_attachment_parse(body: dict, db: Session = Depends(get_db)):
    conversation_id = body.get("conversation_id")
    requester_user_id = body.get("user_id")
    file_ids = _normalize_file_refs(body.get("file_id") or body.get("file_ids") or body.get("attachments"))
    if not conversation_id:
        return fail(ERR_PARAM, "conversation_id is required")
    if requester_user_id is None:
        return fail(ERR_PARAM, "user_id is required")
    if not file_ids:
        return fail(ERR_PARAM, "file_id is required")

    try:
        requester_user_id = int(requester_user_id)
    except Exception:
        return fail(ERR_PARAM, "user_id must be an integer")

    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv or conv.user_id != requester_user_id:
        return fail(ERR_NOT_FOUND, "conversation not found")

    try:
        files, context = _resolve_attachment_context(db, file_ids, conv.user_id)
        return ok(data={
            "file_ids": [item.id for item in files],
            "context": context,
            "parsed": bool(context),
        })
    except Exception as exc:
        return fail(ERR_INTERNAL, str(exc))


@router.get("/file-parse/{task_id}")
def internal_file_parse_status(task_id: str):
    task = get_parse_task(task_id)
    if not task:
        return fail(ERR_NOT_FOUND, "parse task not found")
    return ok(data=task)


@router.post("/tts")
def internal_tts(body: dict):
    text = (body.get("text") or "").strip()
    if not text:
        return fail(ERR_PARAM, "text is required")
    try:
        task_id = uuid.uuid4().hex[:16]
        audio = synthesize_tts(text)
        store_tts_artifact(task_id, audio, "audio/wav")
        return ok(data={
            "task_id": task_id,
            "audio_bytes": len(audio),
            "audio_url": build_tts_audio_url(task_id),
            "mime_type": "audio/wav",
        })
    except Exception as exc:
        return fail(ERR_INTERNAL, str(exc))


@router.post("/asr")
def internal_asr(body: dict, db: Session = Depends(get_db)):
    conversation_id = body.get("conversation_id")
    requester_user_id = body.get("user_id")
    file_id = body.get("file_id")
    if not conversation_id:
        return fail(ERR_PARAM, "conversation_id is required")
    if requester_user_id is None:
        return fail(ERR_PARAM, "user_id is required")
    if not file_id:
        return fail(ERR_PARAM, "file_id is required")

    try:
        requester_user_id = int(requester_user_id)
    except Exception:
        return fail(ERR_PARAM, "user_id must be an integer")

    try:
        file_id = int(file_id)
    except Exception:
        return fail(ERR_PARAM, "file_id must be an integer")

    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        return fail(ERR_NOT_FOUND, "conversation not found")
    if conv.user_id != requester_user_id:
        return fail(ERR_NOT_FOUND, "conversation not found")

    file = db.query(File).filter(File.id == file_id, File.user_id == conv.user_id).first()
    if not file:
        return fail(ERR_NOT_FOUND, "file not found")

    ext = Path(file.filename or file.filepath or "").suffix.lower()
    if ext not in _AUDIO_EXTS:
        return fail(ERR_PARAM, "file is not an audio attachment")
    if not file.filepath or not os.path.exists(file.filepath):
        return fail(ERR_NOT_FOUND, "file not found")

    try:
        payload = _recognize_saved_path(file.filepath, "internal_asr")
        payload["file_id"] = file.id
        payload["filename"] = file.filename
        return ok(data=payload)
    except Exception as exc:
        return fail(ERR_INTERNAL, str(exc))


@router.post("/local-small/generate")
def internal_local_small_generate(body: dict):
    prompt = (body.get("prompt") or "").strip()
    mode = body.get("mode") or "general"
    max_tokens = body.get("max_tokens")

    if not prompt:
        return fail(ERR_PARAM, "prompt is required")
    if mode not in VALID_MODES:
        return fail(ERR_PARAM, f"mode must be one of {sorted(VALID_MODES)}")

    result = local_small_generate(prompt, mode=mode, max_tokens=max_tokens)
    return ok(data=result)


@router.post("/classify-document")
def internal_classify_document(body: dict):
    content = (body.get("content") or "").strip()
    has_attachments = bool(body.get("has_attachments"))
    if not content:
        return fail(ERR_PARAM, "content is required")
    try:
        route = classify_document(content)
        return ok(data={
            "route": route,
            "doc_type": route.get("doc_type", ""),
            "operation": route.get("operation", ""),
        })
    except Exception as exc:
        return fail(ERR_INTERNAL, str(exc))


@router.post("/document-route")
def internal_document_route(body: dict):
    return internal_classify_document(body)


@router.post("/doc-task-status")
def internal_doc_task_status(body: dict):
    task_id = (body.get("task_id") or "").strip()
    if not task_id:
        return fail(ERR_PARAM, "task_id is required")
    from app.services.document_tasks import get_task
    task = get_task(task_id)
    if not task:
        return fail(ERR_NOT_FOUND, "task not found")
    return ok(data=task)


@router.post("/download-url")
def internal_download_url(body: dict):
    task_id = (body.get("task_id") or "").strip()
    if not task_id:
        return fail(ERR_PARAM, "task_id is required")
    task = get_task(task_id)
    if not task:
        return fail(ERR_NOT_FOUND, "task not found")
    download = task.get("download_url")
    if not download:
        return ok(data={
            "task_id": task.get("task_id"),
            "status": task.get("status"),
            "title": task.get("title"),
            "download_url": "",
            "ready": False,
        })
    return ok(data={
        "task_id": task.get("task_id"),
        "status": task.get("status"),
        "title": task.get("title"),
        "download_url": download,
        "ready": True,
    })
