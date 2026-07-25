"""Append-only task persistence for native OOXML PPT enhancement."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import File, PPTNativeEnhanceTask
from app.PPT_master.native_enhance import apply_native_enhancement, validate_native_pptx
from app.services.artifact_service import ArtifactService


class NativeEnhanceError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(value: str | None) -> dict[str, Any]:
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


class NativeEnhanceStore:
    def __init__(self, projects_root: Path | str | None = None) -> None:
        self.artifacts = ArtifactService(projects_root=projects_root)
        self.projects_root = self.artifacts.projects_root

    @staticmethod
    def _snapshot(task: PPTNativeEnhanceTask) -> dict[str, Any]:
        return {"task_id": task.task_id, "route_type": task.route_type, "source_file_id": task.source_file_id,
                "source_sha256": task.source_sha256, "output_file_id": task.output_file_id,
                "output_sha256": task.output_sha256, "status": task.status, "stage": task.stage,
                "options": _load(task.options_json), "validation": _load(task.validation_json),
                "artifact_manifest": _load(task.artifact_manifest_json), "error": _load(task.error_json)}

    def _set_stage(self, db: Session, task: PPTNativeEnhanceTask, stage: str) -> None:
        task.stage = stage
        task.status = stage
        db.commit()

    def create_task(self, db: Session, *, user_id: int, source_file_id: int, expected_sha256: str, options: dict[str, Any]) -> dict[str, Any]:
        source = db.query(File).filter(File.id == source_file_id, File.owner_user_id == user_id).first()
        source_path = Path(source.real_path or source.filepath) if source is not None else None
        if source is None or source_path is None or not source_path.is_file() or source_path.suffix.lower() != ".pptx":
            raise NativeEnhanceError("native_enhance_source_not_found")
        source_sha = _sha256(source_path)
        if source_sha != expected_sha256:
            raise NativeEnhanceError("native_enhance_source_sha_changed")
        task = PPTNativeEnhanceTask(task_id="enhance_" + uuid.uuid4().hex, user_id=user_id, source_file_id=source.id,
            source_sha256=source_sha, status="queued", stage="queued", options_json=_json(options))
        db.add(task); db.commit(); db.refresh(task)
        try:
            self._set_stage(db, task, "validating")
            output_path = self.projects_root / "native_enhance" / task.task_id / "enhanced.pptx"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._set_stage(db, task, "patching_transitions")
            report = apply_native_enhancement(source_path, output_path, options)
            self._set_stage(db, task, "validating_output")
            if not output_path.is_file() or _sha256(output_path) == source_sha:
                raise NativeEnhanceError("native_enhance_output_invalid")
            structure_validation = validate_native_pptx(output_path)
            self._set_stage(db, task, "registering_file")
            artifact = self.artifacts.register_pptx(db, owner_user_id=user_id, project_id=task.task_id, task_id=task.task_id, real_path=output_path)
            task.output_file_id = artifact.id; task.output_sha256 = artifact.sha256
            task.validation_json = _json({**structure_validation, "source_sha256": source_sha, "output_sha256": artifact.sha256})
            task.artifact_manifest_json = _json({"source_file_id": source.id, "output_file_id": artifact.id, "output_sha256": artifact.sha256})
            task.status = "completed"; task.stage = "completed"; task.completed_at = datetime.utcnow()
            db.commit(); db.refresh(task)
        except Exception as exc:
            task.status = "failed"; task.stage = "failed"; task.completed_at = datetime.utcnow(); task.error_json = _json({"code": str(exc)})
            db.commit(); db.refresh(task)
            if isinstance(exc, NativeEnhanceError):
                raise
        return self._snapshot(task)

    def get_task(self, db: Session, *, task_id: str, user_id: int) -> dict[str, Any] | None:
        task = db.query(PPTNativeEnhanceTask).filter(PPTNativeEnhanceTask.task_id == task_id, PPTNativeEnhanceTask.user_id == user_id).first()
        return self._snapshot(task) if task else None
