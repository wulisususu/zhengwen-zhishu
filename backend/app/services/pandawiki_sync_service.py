"""Background sync from local uploads to PandaWiki."""
from __future__ import annotations

import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from app.database import SessionLocal
from app.models import File, PandaWikiSyncTask

logger = logging.getLogger(__name__)

PANDAWIKI_BASE_URL = os.environ.get("PANDAWIKI_BASE_URL", "http://192.168.10.212:2443").rstrip("/")
PANDAWIKI_ACCOUNT = os.environ.get("PANDAWIKI_ACCOUNT", "admin")
PANDAWIKI_PASSWORD = os.environ.get("PANDAWIKI_PASSWORD", "admin123")
PANDAWIKI_KB_ID = os.environ.get("PANDAWIKI_KB_ID", "kb-wiki-001")
PANDAWIKI_NAV_ID = os.environ.get("PANDAWIKI_NAV_ID", "75247cd8-bc9c-4272-85a9-e80ea0907812")

SYNCABLE_EXTS = {".doc", ".docx", ".pdf", ".md", ".markdown"}
RUNNING_STATUSES = ("queued", "uploading", "parsing", "exporting", "polling", "creating", "releasing")
POLL_INTERVAL_SECONDS = 1.5
POLL_TIMEOUT_SECONDS = 180

_executor = ThreadPoolExecutor(max_workers=1)


def is_pandawiki_sync_supported(filename: str | None) -> bool:
    ext = Path(filename or "").suffix.lower()
    return ext in SYNCABLE_EXTS


def create_pandawiki_sync_task(file_id: int, user_id: int) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        file = db.query(File).filter(File.id == file_id, File.user_id == user_id).first()
        if not file or not is_pandawiki_sync_supported(file.filename):
            return None

        running = (
            db.query(PandaWikiSyncTask)
            .filter(
                PandaWikiSyncTask.file_id == file_id,
                PandaWikiSyncTask.user_id == user_id,
                PandaWikiSyncTask.status.in_(RUNNING_STATUSES),
            )
            .order_by(PandaWikiSyncTask.created_at.desc())
            .first()
        )
        if running:
            return _public_task(running)

        task = PandaWikiSyncTask(
            task_id=uuid.uuid4().hex,
            user_id=user_id,
            file_id=file_id,
            status="queued",
            progress=3,
            stage="queued",
            kb_id=PANDAWIKI_KB_ID,
            nav_id=PANDAWIKI_NAV_ID,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        public = _public_task(task)
    finally:
        db.close()

    _executor.submit(_run_sync_task, public["task_id"])
    return public


def get_pandawiki_sync_task(task_id: str, user_id: int | None = None, file_id: int | None = None) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        query = db.query(PandaWikiSyncTask).filter(PandaWikiSyncTask.task_id == task_id)
        if user_id is not None:
            query = query.filter(PandaWikiSyncTask.user_id == user_id)
        if file_id is not None:
            query = query.filter(PandaWikiSyncTask.file_id == file_id)
        task = query.first()
        return _public_task(task) if task else None
    finally:
        db.close()


def _public_task(task: PandaWikiSyncTask | None) -> dict[str, Any] | None:
    if task is None:
        return None
    return {
        "task_id": task.task_id,
        "user_id": task.user_id,
        "file_id": task.file_id,
        "status": task.status,
        "progress": task.progress,
        "stage": task.stage,
        "kb_id": task.kb_id,
        "nav_id": task.nav_id,
        "remote_key": task.remote_key,
        "remote_doc_id": task.remote_doc_id,
        "remote_node_id": task.remote_node_id,
        "remote_release_id": task.remote_release_id,
        "error": task.error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def _update_task(task_id: str, **kwargs) -> None:
    db = SessionLocal()
    try:
        task = db.query(PandaWikiSyncTask).filter(PandaWikiSyncTask.task_id == task_id).first()
        if not task:
            return
        for key, value in kwargs.items():
            setattr(task, key, value)
        db.add(task)
        db.commit()
    finally:
        db.close()


def _request_json(
    session: requests.Session,
    method: str,
    path: str,
    *,
    token: str | None = None,
    timeout: int = 60,
    **kwargs,
) -> dict[str, Any]:
    headers = dict(kwargs.pop("headers", {}) or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = session.request(method, f"{PANDAWIKI_BASE_URL}{path}", headers=headers, timeout=timeout, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("message") or f"PandaWiki request failed: {path}")
    return payload


def _login(session: requests.Session) -> str:
    payload = _request_json(
        session,
        "POST",
        "/api/v1/user/login",
        json={"account": PANDAWIKI_ACCOUNT, "password": PANDAWIKI_PASSWORD},
        timeout=20,
    )
    token = (((payload.get("data") or {}).get("token")) or "").strip()
    if not token:
        raise RuntimeError("PandaWiki login returned empty token")
    return token


def _pick_doc_id(docs: dict[str, Any] | None) -> tuple[str, str]:
    root = docs or {}
    queue = [root]
    while queue:
        node = queue.pop(0) or {}
        value = (node.get("value") or {}) if isinstance(node, dict) else {}
        if value.get("id"):
            return str(value["id"]), str(value.get("file_type") or "")
        queue.extend(node.get("children") or [])
    raise RuntimeError("PandaWiki parse result missing doc id")


def _poll_export_result(session: requests.Session, token: str, export_task_id: str) -> str:
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    last_status = "pending"
    while time.time() < deadline:
        payload = _request_json(
            session,
            "GET",
            "/api/v1/crawler/result",
            token=token,
            params={"task_id": export_task_id},
            timeout=30,
        )
        data = payload.get("data") or {}
        last_status = str(data.get("status") or "pending")
        if last_status == "completed":
            content = str(data.get("content") or "")
            if not content.strip():
                raise RuntimeError("PandaWiki export returned empty content")
            return content
        if last_status == "failed":
            raise RuntimeError("PandaWiki export failed")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError(f"PandaWiki export timed out with status: {last_status}")


def _run_sync_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.query(PandaWikiSyncTask).filter(PandaWikiSyncTask.task_id == task_id).first()
        if not task:
            return
        file = db.query(File).filter(File.id == task.file_id, File.user_id == task.user_id).first()
        if not file or not os.path.exists(file.filepath):
            raise RuntimeError("上传文件不存在，无法同步到知识库")
        filename = file.filename
        filepath = file.filepath
    finally:
        db.close()

    try:
        _update_task(task_id, status="uploading", progress=10, stage="uploading", error="")
        with requests.Session() as session:
            token = _login(session)

            with open(filepath, "rb") as stream:
                upload = _request_json(
                    session,
                    "POST",
                    "/api/v1/file/upload",
                    token=token,
                    files={"file": (filename, stream, "application/octet-stream")},
                    data={"kb_id": PANDAWIKI_KB_ID},
                    timeout=120,
                )
            remote_key = str((upload.get("data") or {}).get("key") or "")
            if not remote_key:
                raise RuntimeError("PandaWiki upload returned empty key")
            _update_task(task_id, progress=25, remote_key=remote_key)

            _update_task(task_id, status="parsing", progress=35, stage="parsing")
            parsed = _request_json(
                session,
                "POST",
                "/api/v1/crawler/parse",
                token=token,
                json={
                    "kb_id": PANDAWIKI_KB_ID,
                    "crawler_source": "file",
                    "filename": filename,
                    "key": remote_key,
                },
                timeout=120,
            )
            parse_data = parsed.get("data") or {}
            parse_id = str(parse_data.get("id") or "")
            if not parse_id:
                raise RuntimeError("PandaWiki parse returned empty parse id")
            remote_doc_id, file_type = _pick_doc_id(parse_data.get("docs"))
            _update_task(task_id, progress=45, remote_doc_id=remote_doc_id)

            _update_task(task_id, status="exporting", progress=55, stage="exporting")
            exported = _request_json(
                session,
                "POST",
                "/api/v1/crawler/export",
                token=token,
                json={
                    "kb_id": PANDAWIKI_KB_ID,
                    "id": parse_id,
                    "doc_id": remote_doc_id,
                    "file_type": file_type or None,
                },
                timeout=120,
            )
            export_task_id = str((exported.get("data") or {}).get("task_id") or "")
            if not export_task_id:
                raise RuntimeError("PandaWiki export returned empty task id")

            _update_task(task_id, status="polling", progress=68, stage="polling")
            content = _poll_export_result(session, token, export_task_id)

            _update_task(task_id, status="creating", progress=82, stage="creating")
            created = _request_json(
                session,
                "POST",
                "/api/v1/node",
                token=token,
                json={
                    "kb_id": PANDAWIKI_KB_ID,
                    "nav_id": PANDAWIKI_NAV_ID,
                    "type": 2,
                    "name": filename,
                    "content": content,
                    "content_type": "md",
                },
                timeout=120,
            )
            remote_node_id = str((created.get("data") or {}).get("id") or "")
            if not remote_node_id:
                raise RuntimeError("PandaWiki create node returned empty node id")
            _update_task(task_id, progress=90, remote_node_id=remote_node_id)

            _update_task(task_id, status="releasing", progress=95, stage="releasing")
            release = _request_json(
                session,
                "POST",
                "/api/v1/knowledge_base/release",
                token=token,
                json={
                    "kb_id": PANDAWIKI_KB_ID,
                    "message": f"自动导入：{filename}",
                    "tag": f"auto-import-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{task_id[:6]}",
                    "node_ids": [remote_node_id],
                },
                timeout=120,
            )
            remote_release_id = str((release.get("data") or {}).get("id") or "")
            _update_task(
                task_id,
                status="success",
                progress=100,
                stage="released",
                remote_release_id=remote_release_id,
                error="",
            )
    except Exception as exc:
        logger.exception("PandaWiki sync failed for task %s", task_id)
        _update_task(task_id, status="failed", stage="failed", error=str(exc), progress=100)
