"""Registered artifact storage and authorization helpers."""

from __future__ import annotations

import hashlib
import mimetypes
import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import File


PPTX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
SVG_MIME_TYPE = "image/svg+xml"
_TASK_ARTIFACT_SUFFIXES = {
    PPTX_MIME_TYPE: ".pptx",
    SVG_MIME_TYPE: ".svg",
}


class ArtifactError(Exception):
    """Base class for safe artifact failures."""


class ArtifactNotFoundError(ArtifactError):
    pass


class ArtifactExpiredError(ArtifactError):
    pass


class ArtifactSecurityError(ArtifactError):
    pass


class ArtifactService:
    def __init__(
        self,
        projects_root: Path | str | None = None,
        legacy_roots: list[Path | str] | None = None,
    ) -> None:
        backend_root = Path(__file__).resolve().parents[2]
        self.projects_root = Path(projects_root or backend_root / "app" / "PPT_master" / "projects")
        if legacy_roots is None:
            legacy_roots = [
                backend_root / "data" / "uploads",
                backend_root / "data" / "generated_docs",
                backend_root / "data" / "output",
                Path(os.environ.get("PPT_HISTORY_ASSETS_ROOT", backend_root / "data" / "ppt_history_assets")),
                Path("/home/youyeetoo/InNet_box/backend/data/uploads"),
                Path("/home/youyeetoo/InNet_box/backend/data/generated_docs"),
            ]
        self.allowed_roots = [self.projects_root, *(Path(root) for root in legacy_roots)]

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _has_symlink_component(path: Path, root: Path) -> bool:
        try:
            relative = path.absolute().relative_to(root.absolute())
        except ValueError:
            return False
        current = root.absolute()
        if current.is_symlink():
            return True
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return True
        return False

    def resolve_registered_path(
        self,
        value: Path | str,
        require_pptx: bool = False,
        allowed_suffixes: set[str] | None = None,
    ) -> Path:
        candidate = Path(value)
        if candidate.is_symlink():
            raise ArtifactSecurityError("artifact_symlink_forbidden")
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ArtifactNotFoundError("artifact_file_missing") from exc
        if not resolved.is_file():
            raise ArtifactNotFoundError("artifact_file_missing")
        if require_pptx and resolved.suffix.lower() != ".pptx":
            raise ArtifactSecurityError("artifact_type_forbidden")
        if allowed_suffixes is not None and resolved.suffix.lower() not in allowed_suffixes:
            raise ArtifactSecurityError("artifact_type_forbidden")

        for root_value in self.allowed_roots:
            root = root_value.resolve(strict=False)
            if resolved.is_relative_to(root):
                if self._has_symlink_component(candidate, root_value):
                    raise ArtifactSecurityError("artifact_symlink_forbidden")
                return resolved
        raise ArtifactSecurityError("artifact_path_outside_allowed_roots")

    def register_pptx(
        self,
        db: Session,
        owner_user_id: int,
        project_id: str,
        task_id: str,
        real_path: Path | str,
        expires_in: timedelta = timedelta(days=7),
    ) -> File:
        resolved = self.resolve_registered_path(real_path, require_pptx=True)
        resolved.chmod(0o600)
        root = self.projects_root.resolve(strict=False)
        current = resolved.parent
        while current.is_relative_to(root):
            current.chmod(0o700)
            if current == root:
                break
            current = current.parent
        size = resolved.stat().st_size
        record = File(
            user_id=owner_user_id,
            owner_user_id=owner_user_id,
            filename=resolved.name,
            filepath=str(resolved),
            real_path=str(resolved),
            filesize=size,
            size=size,
            filetype=".pptx",
            mime_type=PPTX_MIME_TYPE,
            project_id=project_id,
            task_id=task_id,
            sha256=self._sha256(resolved),
            expires_at=datetime.utcnow() + expires_in,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def register_project_asset(
        self,
        db: Session,
        owner_user_id: int,
        project_id: str,
        task_id: str,
        real_path: Path | str,
        mime_type: str,
        expires_in: timedelta = timedelta(days=7),
        registered_resources: set[Path] | None = None,
    ) -> File:
        from app.PPT_master.security import validate_svg_text

        expected_suffix = _TASK_ARTIFACT_SUFFIXES.get(mime_type)
        if expected_suffix != ".svg":
            raise ArtifactSecurityError("artifact_type_forbidden")
        resolved = self.resolve_registered_path(real_path, allowed_suffixes={expected_suffix})
        try:
            svg_text = resolved.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            raise ArtifactSecurityError("artifact_svg_unreadable") from exc
        project_root = resolved.parent.parent if resolved.parent.name == "svg_output" else resolved.parent
        security_errors = validate_svg_text(
            svg_text,
            project_root=project_root,
            registered_resources=registered_resources,
        )
        if security_errors:
            raise ArtifactSecurityError("artifact_svg_unsafe:" + security_errors[0])

        resolved.chmod(0o600)
        root = self.projects_root.resolve(strict=False)
        current = resolved.parent
        while current.is_relative_to(root):
            current.chmod(0o700)
            if current == root:
                break
            current = current.parent
        size = resolved.stat().st_size
        record = File(
            user_id=owner_user_id,
            owner_user_id=owner_user_id,
            filename=resolved.name,
            filepath=str(resolved),
            real_path=str(resolved),
            filesize=size,
            size=size,
            filetype=expected_suffix,
            mime_type=mime_type,
            project_id=project_id,
            task_id=task_id,
            sha256=self._sha256(resolved),
            expires_at=datetime.utcnow() + expires_in,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def _resolve_record_path(self, record: File) -> Path:
        path_value = record.real_path or record.filepath
        if record.task_id:
            expected_suffix = _TASK_ARTIFACT_SUFFIXES.get(record.mime_type or "")
            if expected_suffix is None:
                raise ArtifactSecurityError("artifact_type_forbidden")
            return self.resolve_registered_path(path_value, allowed_suffixes={expected_suffix})
        return self.resolve_registered_path(path_value)

    def get_downloadable(self, db: Session, file_id: int, owner_user_id: int) -> File:
        record = db.query(File).filter(File.id == file_id).first()
        if record is None:
            raise ArtifactNotFoundError("artifact_not_found")
        effective_owner = record.owner_user_id if record.owner_user_id is not None else record.user_id
        if effective_owner != owner_user_id:
            raise ArtifactNotFoundError("artifact_not_found")
        if record.expires_at is not None and record.expires_at <= datetime.utcnow():
            raise ArtifactExpiredError("artifact_expired")
        resolved = self._resolve_record_path(record)
        if record.task_id:
            expected_size = record.size if record.size is not None else record.filesize
            if expected_size != resolved.stat().st_size or not record.sha256:
                raise ArtifactSecurityError("artifact_integrity_mismatch")
            if self._sha256(resolved) != record.sha256:
                raise ArtifactSecurityError("artifact_integrity_mismatch")
        return record

    def download_path(self, record: File) -> Path:
        return self._resolve_record_path(record)

    @staticmethod
    def download_payload(record: File, validation_result: dict, slide_count: int | None = None) -> dict:
        payload = {
            "file_id": record.id,
            "download_url": f"/api/v1/files/{record.id}/download",
            "size": record.size if record.size is not None else record.filesize,
            "sha256": record.sha256 or "",
            "valid": bool(validation_result.get("passed")) and not validation_result.get("blocking_errors"),
            "validation_result": validation_result,
        }
        if slide_count is not None:
            payload["slide_count"] = slide_count
        return payload

    @staticmethod
    def media_type_for(record: File) -> str:
        if record.mime_type and "/" in record.mime_type:
            return record.mime_type
        guessed, _ = mimetypes.guess_type(record.filename)
        return guessed or "application/octet-stream"

    def cleanup_expired(self, db: Session, now: datetime | None = None) -> int:
        cutoff = now or datetime.utcnow()
        records = (
            db.query(File)
            .filter(File.expires_at.is_not(None), File.expires_at <= cutoff, File.task_id.is_not(None))
            .all()
        )
        removed = 0
        for record in records:
            try:
                path = self.download_path(record)
            except ArtifactError:
                path = None
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    continue
            db.delete(record)
            removed += 1
        db.commit()
        return removed
