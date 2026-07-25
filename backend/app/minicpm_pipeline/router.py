"""MiniCPM document generation endpoints — segmented generation with streaming progress."""
import threading
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.errors import ok, fail, ERR_INTERNAL, ERR_NOT_FOUND
from app.models import User

router = APIRouter(prefix="/documents-minicpm", tags=["documents-minicpm"])

# ── 简易内存任务存储 ─────────────────────────────────────────────────
_tasks: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _create_task(user_input: str, user_id: int, attachment_context: str = "") -> dict:
    task_id = uuid.uuid4().hex[:12]
    task = {
        "task_id": task_id,
        "user_id": user_id,
        "status": "pending",
        "phase": "",
        "message": "",
        "current_heading": "",
        "progress_current": 0,
        "progress_total": 0,
        "sections_stream": [],       # 实时累积的已生成章节
        "user_input": user_input,
        "attachment_context": attachment_context,
        "route": None,
        "content_schema": None,
        "file_info": None,
        "total_chars": 0,
        "section_count": 0,
        "error": None,
        "created_at": time.time(),
        "finished_at": None,
    }
    with _lock:
        _tasks[task_id] = task

    t = threading.Thread(target=_run_task, args=(task_id,), daemon=True)
    t.start()
    return task


def _run_task(task_id: str):
    from app.minicpm_pipeline.pipeline import run_pipeline_segmented

    with _lock:
        task = _tasks.get(task_id)
    if not task:
        return

    try:
        def progress(data: dict):
            """接受结构化进度: {phase, message, index, total, heading, sections}"""
            with _lock:
                t = _tasks.get(task_id)
                if not t:
                    return
                t["phase"] = data.get("phase", "")
                t["message"] = data.get("message", "")
                t["status"] = data.get("message", t["phase"])
                t["progress_current"] = data.get("index", 0)
                t["progress_total"] = data.get("total", 0)
                t["current_heading"] = data.get("heading", "")
                # 实时写入已完成章节快照供前端展示
                if "sections" in data:
                    t["sections_stream"] = list(data["sections"])

        result = run_pipeline_segmented(
            user_input=task["user_input"],
            attachment_context=task.get("attachment_context", ""),
            progress_callback=progress,
        )

        with _lock:
            t = _tasks.get(task_id)
            if not t:
                return
            t["status"] = "completed"
            t["phase"] = "completed"
            t["message"] = "文档生成完成"
            t["route"] = result["route"]
            t["content_schema"] = result["content_schema"]
            t["file_info"] = {
                "filename": result["filename"],
                "filepath": result["filepath"],
                "filesize": result["filesize"],
            }
            t["total_chars"] = result.get("total_chars", 0)
            t["section_count"] = result.get("section_count", 0)
            t["finished_at"] = time.time()

    except Exception as exc:
        with _lock:
            t = _tasks.get(task_id)
            if not t:
                return
            t["status"] = "failed"
            t["phase"] = "failed"
            t["message"] = str(exc)
            t["error"] = str(exc)
            t["finished_at"] = time.time()


def _get_task(task_id: str, user_id: int) -> dict | None:
    with _lock:
        task = _tasks.get(task_id)
    if not task or task["user_id"] != user_id:
        return None
    return dict(task)


def _list_tasks(user_id: int) -> list[dict]:
    with _lock:
        return [
            dict(t) for t in _tasks.values()
            if t["user_id"] == user_id
        ][-20:]


# ── 路由 ─────────────────────────────────────────────────────────────

@router.post("/generate")
def generate_document(
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prompt = body.get("prompt") or body.get("content") or body.get("text") or ""
    if not prompt:
        return fail(ERR_INTERNAL, "prompt is required")

    attachment_context = body.get("attachment_context") or ""
    try:
        task = _create_task(prompt, user.id, attachment_context=attachment_context)
        return ok(data={"task": task})
    except Exception as exc:
        return fail(ERR_INTERNAL, str(exc))


@router.get("/tasks/{task_id}")
def task_status(task_id: str, user: User = Depends(get_current_user)):
    task = _get_task(task_id, user.id)
    if not task:
        return fail(ERR_NOT_FOUND, "task not found")
    return ok(data=task)


@router.get("/tasks")
def task_list(user: User = Depends(get_current_user)):
    return ok(data=_list_tasks(user.id))
