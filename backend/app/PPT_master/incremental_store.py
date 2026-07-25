"""Durable event sequencing and query snapshots for incremental PPT tasks."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import PPTIncrementalEvent, PPTIncrementalTask


class IncrementalTaskNotFound(LookupError):
    pass


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class IncrementalTaskStore:
    def create_task(
        self,
        db: Session,
        *,
        task_id: str,
        project_id: str,
        user_id: int,
        request_id: str,
        page_count: int,
        source_refs: dict[str, Any] | None = None,
    ) -> PPTIncrementalTask:
        task = PPTIncrementalTask(
            task_id=task_id,
            project_id=project_id,
            user_id=user_id,
            request_id=request_id,
            page_count=page_count,
            status="accepted",
            sequence=0,
            source_refs_json=_dump(source_refs or {}),
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def find_by_request(db: Session, user_id: int, request_id: str) -> PPTIncrementalTask | None:
        return (
            db.query(PPTIncrementalTask)
            .filter(
                PPTIncrementalTask.user_id == user_id,
                PPTIncrementalTask.request_id == request_id,
            )
            .first()
        )

    @staticmethod
    def _task(db: Session, task_id: str) -> PPTIncrementalTask:
        task = db.query(PPTIncrementalTask).filter(PPTIncrementalTask.task_id == task_id).first()
        if task is None:
            raise IncrementalTaskNotFound(task_id)
        return task

    def append_event(
        self,
        db: Session,
        task_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        task = self._task(db, task_id)
        task.sequence = int(task.sequence or 0) + 1
        timestamp = datetime.now(timezone.utc)
        event = PPTIncrementalEvent(
            event_id="evt_" + uuid.uuid4().hex,
            task_id=task.task_id,
            user_id=task.user_id,
            sequence=task.sequence,
            event_type=event_type,
            payload_json=_dump(data),
            timestamp=timestamp.replace(tzinfo=None),
        )
        self._apply_snapshot(task, event_type, data)
        db.add(event)
        db.commit()
        return {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "task_id": task.task_id,
            "project_id": task.project_id,
            "sequence": event.sequence,
            "timestamp": _iso_z(timestamp),
            "data": data,
        }

    @staticmethod
    def _apply_snapshot(task: PPTIncrementalTask, event_type: str, data: dict[str, Any]) -> None:
        if event_type == "planning.started":
            task.status = "planning"
        elif event_type == "planning.completed":
            task.status = "planning_completed"
            task.outline_json = _dump(data.get("outline") or [])
        elif event_type == "slide.started":
            task.status = "generating"
            task.current_slide_json = _dump(data)
        elif event_type == "slide.completed":
            task.status = "generating"
            completed = _load(task.completed_slides_json, [])
            completed.append(data)
            task.completed_slides_json = _dump(completed)
            task.current_slide_json = ""
        elif event_type == "slide.failed":
            task.status = "generating"
            errors = _load(task.errors_json, [])
            item = {"index": data.get("index"), "errors": data.get("errors") or []}
            if data.get("diagnostics"):
                item["diagnostics"] = data["diagnostics"]
            errors.append(item)
            task.errors_json = _dump(errors)
            task.current_slide_json = ""
        elif event_type == "validation.completed":
            task.status = "validation_completed"
            task.metrics_json = _dump(data.get("metrics") or {})
        elif event_type == "export.ready":
            task.status = "export_ready"
            task.final_file_json = _dump(data.get("final_file") or {})
        elif event_type == "task.completed":
            task.status = "completed"
            task.current_slide_json = ""
            if data.get("final_file"):
                task.final_file_json = _dump(data["final_file"])
        elif event_type == "task.failed":
            task.status = "failed"
            task.current_slide_json = ""
            errors = _load(task.errors_json, [])
            error = data.get("error") or data.get("code")
            if error:
                errors.append({"task": str(error)})
                task.errors_json = _dump(errors)

    def snapshot(self, db: Session, task_id: str, owner_user_id: int) -> dict[str, Any]:
        task = (
            db.query(PPTIncrementalTask)
            .filter(
                PPTIncrementalTask.task_id == task_id,
                PPTIncrementalTask.user_id == owner_user_id,
            )
            .first()
        )
        if task is None:
            raise IncrementalTaskNotFound(task_id)
        return {
            "task_id": task.task_id,
            "project_id": task.project_id,
            "request_id": task.request_id,
            "status": task.status,
            "sequence": task.sequence,
            "page_count": task.page_count,
            "outline": _load(task.outline_json, []),
            "completed_slides": _load(task.completed_slides_json, []),
            "current_slide": _load(task.current_slide_json, None),
            "errors": _load(task.errors_json, []),
            "metrics": _load(task.metrics_json, {}),
            "final_file": _load(task.final_file_json, None),
            "sources": _load(task.source_refs_json, {}),
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        }
