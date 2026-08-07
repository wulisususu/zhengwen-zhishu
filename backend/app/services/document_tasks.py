"""Persistent document task system for async DOCX generation."""
from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

from app.database import SessionLocal
from app.models import DocumentTask, File
from app.services.document_service import generate_document_file
from app.docs_pipeline import run_pipeline

_executor = ThreadPoolExecutor(max_workers=2)
_futures: dict[str, Any] = {}
_futures_lock = Lock()


def _task_error_message(exc: Exception) -> str:
    user_message = getattr(exc, "user_message", "")
    if user_message:
        return str(user_message)
    text = str(exc).strip()
    return text or "正式文档正文生成失败，请稍后重试。"


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_load(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _is_prebuilt_render_content(content_schema: Any) -> bool:
    return isinstance(content_schema, dict) and bool(str(content_schema.get("content") or "").strip())


def _public(task: DocumentTask, db=None) -> dict[str, Any]:
    file_info = None
    if task.file_id and db is not None:
        file = db.query(File).filter(File.id == task.file_id, File.user_id == task.user_id).first()
        if file:
            file_info = {
                "id": file.id,
                "filename": file.filename,
                "size": file.filesize,
                "type": file.filetype,
                "download_url": f"/api/v1/files/{file.id}/download",
            }
    route = _json_load(task.route_json, {})
    meta = route.get("_task_meta") if isinstance(route, dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    return {
        "task_id": task.task_id,
        "workflow_type": task.workflow_type or "document",
        "conversation_id": task.conversation_id,
        "message_id": task.message_id,
        "title": task.title or "document.docx",
        "status": task.status,
        "progress": task.progress,
        "stage": meta.get("stage") or task.status,
        "status_text": meta.get("status_text") or _default_status_text(task.status),
        "doc_type": task.doc_type,
        "engine": task.engine,
        "template_id": task.template_id,
        "routing_json": route,
        "outline_preview": route.get("outline_preview") if isinstance(route, dict) else None,
        "task_graph": route.get("task_graph") if isinstance(route, dict) else None,
        "sections_stream": meta.get("sections_stream", []),
        "quality_check": meta.get("quality_check") if isinstance(meta, dict) else None,
        "output_spec": (route.get("output_spec") if isinstance(route, dict) else None),
        "file": file_info,
        "download_url": file_info.get("download_url") if file_info else None,
        "error": task.error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def _default_status_text(status: str) -> str:
    return {
        "queued": "任务已创建，等待开始",
        "validated": "任务校验完成",
        "generating_outline": "正在生成文档大纲",
        "outline_ready": "大纲已生成，正在撰写正文",
        "generating_content": "正在生成正文内容",
        "rendering": "正在渲染文档文件",
        "download_card": "正在准备下载卡片",
        "done": "文档已生成，可下载",
        "error": "文档生成失败",
        "cancelling": "正在取消任务",
        "cancelled": "任务已取消",
    }.get(status, "任务处理中")


def _update_task_progress(task_id: str, status: str, progress: int, status_text: str = "", sections = None) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        task = db.query(DocumentTask).filter(DocumentTask.task_id == task_id).first()
        if not task:
            return None
        route = _json_load(task.route_json, {})
        if not isinstance(route, dict):
            route = {}
        meta = route.get("_task_meta")
        if not isinstance(meta, dict):
            meta = {}
        meta["stage"] = status
        meta["status_text"] = status_text or _default_status_text(status)
        if sections is not None:
            meta["sections_stream"] = sections
        route["_task_meta"] = meta
        task.route_json = _json_dump(route)
        task.status = status
        task.progress = max(0, min(100, int(progress)))
        if status != "error":
            task.error = ""
        db.add(task)
        db.commit()
        db.refresh(task)
        return _public(task, db)
    finally:
        db.close()


def get_task(task_id: str, user_id: int | None = None) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        query = db.query(DocumentTask).filter(DocumentTask.task_id == task_id)
        if user_id is not None:
            query = query.filter(DocumentTask.user_id == user_id)
        task = query.first()
        return _public(task, db) if task else None
    finally:
        db.close()


def get_latest_task_for_conversation(conversation_id: int, max_age_seconds: int = 120) -> dict[str, Any] | None:
    """Find the most recent document task for a conversation (within max_age_seconds)."""
    from datetime import datetime, timedelta
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(seconds=max_age_seconds)
        task = (
            db.query(DocumentTask)
            .filter(
                DocumentTask.conversation_id == conversation_id,
                DocumentTask.created_at >= cutoff,
                DocumentTask.status.notin_(["error", "cancelled"]),
            )
            .order_by(DocumentTask.created_at.desc())
            .first()
        )
        return _public(task, db) if task else None
    finally:
        db.close()


def list_tasks(user_id: int, conversation_id: int | None = None, workflow_type: str | None = None) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        query = db.query(DocumentTask).filter(DocumentTask.user_id == user_id)
        if conversation_id is not None:
            query = query.filter(DocumentTask.conversation_id == conversation_id)
        if workflow_type:
            query = query.filter(DocumentTask.workflow_type == workflow_type)
        tasks = query.order_by(DocumentTask.created_at.desc()).all()
        return [_public(task, db) for task in tasks]
    finally:
        db.close()


def _update(task_id: str, **kwargs) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        task = db.query(DocumentTask).filter(DocumentTask.task_id == task_id).first()
        if not task:
            return None
        for key, value in kwargs.items():
            setattr(task, key, value)
        db.add(task)
        db.commit()
        db.refresh(task)
        return _public(task, db)
    finally:
        db.close()


def _set_future(task_id: str, future) -> None:
    with _futures_lock:
        _futures[task_id] = future


def _pop_future(task_id: str):
    with _futures_lock:
        return _futures.pop(task_id, None)


def _get_future(task_id: str):
    with _futures_lock:
        return _futures.get(task_id)


def _cancelled_public(task: DocumentTask, db) -> dict[str, Any]:
    task.status = "cancelled"
    task.progress = 100
    if not (task.error or "").strip():
        task.error = "用户已中断该任务。"
    db.add(task)
    db.commit()
    db.refresh(task)
    return _public(task, db)


def _is_cancel_requested(task_id: str) -> bool:
    db = SessionLocal()
    try:
        task = db.query(DocumentTask).filter(DocumentTask.task_id == task_id).first()
        return bool(task and task.status in {"cancelling", "cancelled"})
    finally:
        db.close()


def cancel_task(task_id: str, user_id: int) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        task = (
            db.query(DocumentTask)
            .filter(DocumentTask.task_id == task_id, DocumentTask.user_id == user_id)
            .first()
        )
        if not task:
            return None
        if task.status in {"done", "error", "cancelled"}:
            return _public(task, db)

        future = _get_future(task_id)
        if future and future.cancel():
            return _cancelled_public(task, db)

        task.status = "cancelling"
        task.error = "用户已请求中断，正在停止任务。"
        db.add(task)
        db.commit()
        db.refresh(task)
        return _public(task, db)
    finally:
        db.close()


def create_document_task(
    user_input: str,
    user_id: int,
    route: dict | None = None,
    content_schema: dict | None = None,
    outline_preview: dict | None = None,
    conversation_id: int | None = None,
    message_id: int | None = None,
    workflow_type: str = "document",
) -> dict[str, Any]:
    route = dict(route or {})
    route.setdefault("doc_type", "report")
    route.setdefault("engine", "python-docx")
    route.setdefault("template_id", "simple_v1")
    route.setdefault("output_spec", {}).setdefault("format", "docx")
    if outline_preview:
        route["outline_preview"] = outline_preview
    route["_task_meta"] = {
        "stage": "queued",
        "status_text": _default_status_text("queued"),
    }
    initial_title = ""
    if isinstance(content_schema, dict):
        initial_title = str(content_schema.get("filename") or "").strip()
    if not initial_title:
        initial_title = (user_input[:30].strip() or "document") + ".docx"
    task_id = uuid.uuid4().hex
    db = SessionLocal()
    try:
        task = DocumentTask(
            task_id=task_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            workflow_type=workflow_type or "document",
            title=initial_title,
            status="queued",
            progress=6,
            doc_type=route["doc_type"],
            engine=route["engine"],
            template_id=route["template_id"],
            user_input=user_input or "",
            route_json=_json_dump(route),
            content_schema_json=_json_dump(content_schema) if content_schema is not None else "",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        public = _public(task, db)
    finally:
        db.close()
    future = _executor.submit(_run_task, task_id)
    _set_future(task_id, future)
    return public


def _run_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.query(DocumentTask).filter(DocumentTask.task_id == task_id).first()
        if not task:
            return
        if task.status in {"cancelling", "cancelled"}:
            _cancelled_public(task, db)
            return
        _update_task_progress(task_id, "validated", 12, "任务校验完成")

        route = _json_load(task.route_json, None)
        content_schema = _json_load(task.content_schema_json, None)
        prebuilt_render_content = _is_prebuilt_render_content(content_schema)
        if _is_cancel_requested(task_id):
            task = db.query(DocumentTask).filter(DocumentTask.task_id == task_id).first()
            if task:
                _cancelled_public(task, db)
            return

        last_progress = 12

        def progress_callback(stage: str, progress: int, status_text: str) -> None:
            nonlocal last_progress
            if prebuilt_render_content and int(progress) <= last_progress:
                return
            last_progress = max(last_progress, int(progress))
            _update_task_progress(task_id, stage, progress, status_text)

        if prebuilt_render_content:
            for stage, progress, status_text in (
                ("rendering", 28, "正文已完成，正在准备渲染"),
                ("rendering", 48, "正在解析 Markdown 正文"),
                ("rendering", 68, "正在生成 Word 文件"),
            ):
                if _is_cancel_requested(task_id):
                    task = db.query(DocumentTask).filter(DocumentTask.task_id == task_id).first()
                    if task:
                        _cancelled_public(task, db)
                    return
                _update_task_progress(task_id, stage, progress, status_text)
                last_progress = progress
                time.sleep(0.35)
            generated = generate_document_file(task.user_input, route=route, content_schema=content_schema)
        else:
            # -- MiniCPM segmented pipeline --
            def _mini_progress(data: dict):
                phase = data.get("phase", "")
                msg = data.get("message", "")
                idx = data.get("index", 0)
                total = data.get("total", 0)
                pct = 12 + int((idx / max(total, 1)) * 82)
                sections = data.get("sections")
                _update_task_progress(task_id, phase, pct, msg, sections=sections)

            generated = run_pipeline(
                task.user_input,
                progress_callback=_mini_progress,
                section_count=6,
            )
            # -- end MiniCPM --
        if _is_cancel_requested(task_id):
            try:
                filepath = generated.get("filepath")
                if filepath:
                    Path(filepath).unlink(missing_ok=True)
            except Exception:
                pass
            task = db.query(DocumentTask).filter(DocumentTask.task_id == task_id).first()
            if task:
                _cancelled_public(task, db)
            return

        task = db.query(DocumentTask).filter(DocumentTask.task_id == task_id).first()
        if not task:
            return
        if task.status in {"cancelling", "cancelled"}:
            try:
                filepath = generated.get("filepath")
                if filepath:
                    Path(filepath).unlink(missing_ok=True)
            except Exception:
                pass
            _cancelled_public(task, db)
            return
        _update_task_progress(task_id, "download_card", 94, "正文已生成，正在准备下载卡片")
        task = db.query(DocumentTask).filter(DocumentTask.task_id == task_id).first()
        if not task:
            return
        task.title = generated["filename"]
        db.add(task)
        db.commit()

        rec = File(
            user_id=task.user_id,
            filename=generated["filename"],
            filepath=generated["filepath"],
            filesize=generated["filesize"],
            filetype=generated.get("filetype") or ".docx",
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)

        task = db.query(DocumentTask).filter(DocumentTask.task_id == task_id).first()
        if not task:
            return
        if task.status in {"cancelling", "cancelled"}:
            _cancelled_public(task, db)
            return
        route = _json_load(task.route_json, {})
        if not isinstance(route, dict):
            route = {}
        meta = route.get("_task_meta")
        if not isinstance(meta, dict):
            meta = {}
        meta["stage"] = "done"
        meta["status_text"] = _default_status_text("done")
        quality_check = generated.get("quality_check") if isinstance(generated, dict) else None
        if isinstance(quality_check, dict):
            meta["quality_check"] = quality_check
        route["_task_meta"] = meta
        task.route_json = _json_dump(route)
        task.status = "done"
        task.progress = 100
        task.title = rec.filename
        task.file_id = rec.id
        task.error = None
        db.add(task)
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            task = db.query(DocumentTask).filter(DocumentTask.task_id == task_id).first()
            if task:
                if task.status in {"cancelling", "cancelled"}:
                    _cancelled_public(task, db)
                    return
                task.status = "error"
                task.progress = 100
                task.error = _task_error_message(exc)
                db.add(task)
                db.commit()
        except Exception:
            db.rollback()
    finally:
        _pop_future(task_id)
        db.close()
