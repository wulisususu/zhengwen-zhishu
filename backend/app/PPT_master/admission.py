"""Single-worker admission, idempotency, and project quota controls."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PPTGenerationRequest


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$")
_SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(?:https?://|file://)\S+|(?:/home|/etc|/proc|/tmp|/var)/\S+|[A-Za-z]:\\\S+"
)


class GenerationBusyError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class InvalidRequestIdError(ValueError):
    pass


class ProjectQuotaError(RuntimeError):
    pass


@dataclass
class IdempotencyDecision:
    kind: str
    record: PPTGenerationRequest
    event_type: str | None = None
    payload: dict | None = None


class IdempotencyService:
    def begin(
        self,
        db: Session,
        user_id: int,
        request_id: str,
        task_id: str,
    ) -> IdempotencyDecision:
        record = (
            db.query(PPTGenerationRequest)
            .filter(
                PPTGenerationRequest.user_id == user_id,
                PPTGenerationRequest.request_id == request_id,
            )
            .first()
        )
        if record is not None:
            if record.status in {"completed", "failed"}:
                try:
                    payload = json.loads(record.response_json or "{}")
                except json.JSONDecodeError:
                    payload = {"message": "stored result unavailable", "valid": False}
                return IdempotencyDecision(
                    kind="replay",
                    record=record,
                    event_type=record.event_type or ("done" if record.status == "completed" else "fallback"),
                    payload=payload,
                )
            return IdempotencyDecision(kind="active", record=record)

        record = PPTGenerationRequest(
            user_id=user_id,
            request_id=request_id,
            task_id=task_id,
            status="accepted",
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return self.begin(db, user_id, request_id, task_id)
        db.refresh(record)
        return IdempotencyDecision(kind="new", record=record)

    @staticmethod
    def mark_running(db: Session, record_id: int) -> None:
        record = db.get(PPTGenerationRequest, record_id)
        if record is not None:
            record.status = "running"
            db.commit()

    @staticmethod
    def mark_completed(db: Session, record_id: int, file_id: int, payload: dict) -> None:
        record = db.get(PPTGenerationRequest, record_id)
        if record is not None:
            record.status = "completed"
            record.file_id = file_id
            record.event_type = "done"
            record.response_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            record.error_code = ""
            db.commit()

    @staticmethod
    def mark_failed(db: Session, record_id: int, error_code: str, payload: dict) -> None:
        record = db.get(PPTGenerationRequest, record_id)
        if record is not None:
            record.status = "failed"
            record.event_type = "fallback"
            record.response_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            record.error_code = error_code[:64]
            db.commit()


class GenerationLease:
    def __init__(self, limiter: "GenerationLimiter", user_id: int) -> None:
        self._limiter = limiter
        self.user_id = user_id
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._limiter._release(self.user_id)


class GenerationLimiter:
    def __init__(self, max_global: int = 1, max_per_user: int = 1) -> None:
        self.max_global = max_global
        self.max_per_user = max_per_user
        self._lock = asyncio.Lock()
        self._active_global = 0
        self._active_by_user: dict[int, int] = {}

    async def acquire_nowait(self, user_id: int) -> GenerationLease:
        async with self._lock:
            user_count = self._active_by_user.get(user_id, 0)
            if user_count >= self.max_per_user:
                raise GenerationBusyError("user_generation_limit_reached")
            if self._active_global >= self.max_global:
                raise GenerationBusyError("global_generation_limit_reached")
            self._active_global += 1
            self._active_by_user[user_id] = user_count + 1
            return GenerationLease(self, user_id)

    async def _release(self, user_id: int) -> None:
        async with self._lock:
            self._active_global = max(0, self._active_global - 1)
            remaining = self._active_by_user.get(user_id, 0) - 1
            if remaining > 0:
                self._active_by_user[user_id] = remaining
            else:
                self._active_by_user.pop(user_id, None)


# The approved deployment uses one Uvicorn worker. Sharing this instance keeps
# Legacy and incremental PPT requests under the same deployment-wide limit.
generation_limiter = GenerationLimiter(max_global=1, max_per_user=1)


def select_request_id(body_request_id: str | None, header_request_id: str | None) -> str:
    body = (body_request_id or "").strip()
    header = (header_request_id or "").strip()
    if body and header and body != header:
        raise InvalidRequestIdError("idempotency_key_mismatch")
    value = body or header
    if not value:
        raise InvalidRequestIdError("idempotency_key_required")
    if not _REQUEST_ID_RE.fullmatch(value):
        raise InvalidRequestIdError("idempotency_key_invalid")
    return value


def enforce_directory_quota(path: Path | str, max_bytes: int) -> int:
    root = Path(path)
    if not root.exists():
        return 0
    if root.is_symlink():
        raise ProjectQuotaError("project_symlink_forbidden")
    total = 0
    for candidate in root.rglob("*"):
        if candidate.is_symlink():
            raise ProjectQuotaError("project_symlink_forbidden")
        if candidate.is_file():
            total += candidate.stat().st_size
            if total > max_bytes:
                raise ProjectQuotaError("project_quota_exceeded")
    return total


def _redact_text(value: object, limit: int = 500) -> str:
    text = _SENSITIVE_TEXT_RE.sub("[redacted]", str(value or ""))
    compact = " ".join(text.split())
    return compact[:limit]


def _sanitize_diagnostics(value: dict | None) -> dict:
    if not isinstance(value, dict):
        return {}
    payload: dict = {}
    if isinstance(value.get("page_count"), int):
        payload["page_count"] = value["page_count"]
    if isinstance(value.get("project_id"), str):
        payload["project_id"] = _redact_text(value["project_id"], limit=128)
    validation_result = value.get("validation_result")
    if isinstance(validation_result, dict):
        payload["validation_result"] = {
            "passed": bool(validation_result.get("passed")),
            "warnings": [_redact_text(item, limit=120) for item in validation_result.get("warnings") or []],
            "errors": [_redact_text(item, limit=120) for item in validation_result.get("errors") or []],
            "blocking_errors": [
                _redact_text(item, limit=120) for item in validation_result.get("blocking_errors") or []
            ],
        }
    metrics = value.get("metrics")
    if isinstance(metrics, dict):
        payload["metrics"] = {
            str(key): metrics[key]
            for key in sorted(metrics)
            if isinstance(metrics[key], (int, float))
        }
    failed_slides = value.get("failed_slides")
    if isinstance(failed_slides, list):
        safe_slides = []
        for item in failed_slides:
            if not isinstance(item, dict):
                continue
            safe_item = {
                "index": item.get("index"),
                "errors": [_redact_text(code, limit=120) for code in item.get("errors") or []],
            }
            diagnostics = item.get("diagnostics")
            if isinstance(diagnostics, list):
                safe_diagnostics = []
                for detail in diagnostics:
                    if not isinstance(detail, dict):
                        continue
                    safe_diagnostics.append({
                        "category": _redact_text(detail.get("category"), limit=120),
                        "message": _redact_text(detail.get("message"), limit=200),
                        "line": detail.get("line"),
                        "column": detail.get("column"),
                        "snippet": _redact_text(detail.get("snippet"), limit=200),
                    })
                if safe_diagnostics:
                    safe_item["diagnostics"] = safe_diagnostics
            safe_slides.append(safe_item)
        if safe_slides:
            payload["failed_slides"] = safe_slides
    return payload


def cleanup_failed_project(
    project_dir: Path | str,
    *,
    task_id: str,
    error_code: str,
    projects_root: Path | str | None = None,
    diagnostics_root: Path | str | None = None,
    diagnostics: dict | None = None,
) -> bool:
    backend_root = Path(__file__).resolve().parents[2]
    root = Path(projects_root or backend_root / "app" / "PPT_master" / "projects")
    project = Path(project_dir)
    if not project.exists() or project.is_symlink():
        return False
    try:
        resolved_root = root.resolve(strict=True)
        resolved_project = project.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    if resolved_project.parent != resolved_root or not resolved_project.name.startswith("pptgen_"):
        return False

    diagnostic_root = Path(diagnostics_root or backend_root / "data" / "ppt_failures")
    diagnostic_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    diagnostic_root.chmod(0o700)
    safe_task_id = re.sub(r"[^A-Za-z0-9._-]", "_", task_id)[:64] or "unknown"
    diagnostic_path = diagnostic_root / f"{safe_task_id}.json"
    diagnostic = {
        "task_id": safe_task_id,
        "error_code": re.sub(r"[^A-Za-z0-9._:-]", "_", error_code)[:64],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload_removed": True,
    }
    diagnostic.update(_sanitize_diagnostics(diagnostics))
    diagnostic_path.write_text(json.dumps(diagnostic, ensure_ascii=False), encoding="utf-8")
    diagnostic_path.chmod(0o600)
    shutil.rmtree(resolved_project)
    return True
