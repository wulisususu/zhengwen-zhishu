"""Owner-scoped PPT image asset registration and project manifests."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import File, PPTIncrementalTask, PPTMediaAsset, PPTProjectMediaAsset

_ALLOWED = {"image/png", "image/jpeg", "image/webp"}
_MAX_BYTES = 20 * 1024 * 1024
_MAX_PIXELS = 40_000_000


class MediaAssetError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_info(path: Path) -> tuple[str, int, int]:
    try:
        from PIL import Image
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            mime = Image.MIME.get(image.format or "", "")
    except Exception as exc:
        raise MediaAssetError("image_invalid") from exc
    if mime not in _ALLOWED or width < 1 or height < 1 or width * height > _MAX_PIXELS:
        raise MediaAssetError("image_invalid")
    return mime, width, height


class PptMediaResolver:
    def _require_project(self, db: Session, *, project_id: str, owner_user_id: int) -> None:
        task = db.query(PPTIncrementalTask).filter(
            PPTIncrementalTask.project_id == project_id,
            PPTIncrementalTask.user_id == owner_user_id,
        ).first()
        if task is None:
            raise MediaAssetError("editor_project_not_found")

    def register_file(
        self, db: Session, *, file_id: int, owner_user_id: int, source_type: str,
        project_id: str, source_file_id: int | None = None,
    ) -> dict[str, Any]:
        if source_type not in {"uploaded", "document_extracted", "knowledge_extracted"}:
            raise MediaAssetError("image_source_invalid")
        self._require_project(db, project_id=project_id, owner_user_id=owner_user_id)
        record = db.query(File).filter(
            File.id == file_id,
            or_(File.owner_user_id == owner_user_id, File.user_id == owner_user_id),
        ).first()
        if record is None:
            raise MediaAssetError("image_not_found")
        path = Path(record.real_path or record.filepath)
        if not path.is_file() or path.stat().st_size > _MAX_BYTES:
            raise MediaAssetError("image_invalid")
        mime, width, height = _image_info(path)
        sha256 = record.sha256 or _sha256(path)
        asset = db.query(PPTMediaAsset).filter(
            PPTMediaAsset.owner_user_id == owner_user_id,
            PPTMediaAsset.sha256 == sha256,
        ).first()
        if asset is None:
            asset = PPTMediaAsset(
                asset_id="pptimg_" + uuid.uuid4().hex, file_id=record.id,
                owner_user_id=owner_user_id, source_type=source_type,
                source_file_id=source_file_id, mime_type=mime, width=width,
                height=height, sha256=sha256, status="ready", metadata_json="{}",
            )
            db.add(asset)
            db.flush()
        link = db.query(PPTProjectMediaAsset).filter(
            PPTProjectMediaAsset.project_id == project_id,
            PPTProjectMediaAsset.asset_id == asset.asset_id,
        ).first()
        if link is None:
            db.add(PPTProjectMediaAsset(
                project_id=project_id, asset_id=asset.asset_id,
                owner_user_id=owner_user_id,
            ))
        db.commit()
        db.refresh(asset)
        return self._snapshot(asset)

    def asset_for_project(self, db: Session, *, project_id: str, asset_id: str, owner_user_id: int) -> PPTMediaAsset | None:
        return db.query(PPTMediaAsset).join(
            PPTProjectMediaAsset,
            PPTProjectMediaAsset.asset_id == PPTMediaAsset.asset_id,
        ).filter(
            PPTProjectMediaAsset.project_id == project_id,
            PPTProjectMediaAsset.owner_user_id == owner_user_id,
            PPTMediaAsset.asset_id == asset_id,
            PPTMediaAsset.owner_user_id == owner_user_id,
            PPTMediaAsset.status == "ready",
        ).first()

    def list_project(self, db: Session, *, project_id: str, owner_user_id: int) -> list[dict[str, Any]]:
        self._require_project(db, project_id=project_id, owner_user_id=owner_user_id)
        rows = db.query(PPTMediaAsset).join(
            PPTProjectMediaAsset,
            PPTProjectMediaAsset.asset_id == PPTMediaAsset.asset_id,
        ).filter(
            PPTProjectMediaAsset.project_id == project_id,
            PPTProjectMediaAsset.owner_user_id == owner_user_id,
            PPTMediaAsset.owner_user_id == owner_user_id,
            PPTMediaAsset.status == "ready",
        ).order_by(PPTProjectMediaAsset.created_at.asc()).all()
        return [self._snapshot(row) for row in rows]

    def manifest(self, db: Session, *, project_id: str, owner_user_id: int) -> dict[str, Any]:
        return {"project_id": project_id, "assets": self.list_project(db, project_id=project_id, owner_user_id=owner_user_id)}

    @staticmethod
    def _snapshot(row: PPTMediaAsset) -> dict[str, Any]:
        return {
            "asset_id": row.asset_id, "file_id": row.file_id,
            "source": row.source_type, "source_file_id": row.source_file_id,
            "width": row.width, "height": row.height, "mime_type": row.mime_type,
            "sha256": row.sha256, "status": row.status,
            "download_url": f"/api/v1/files/{row.file_id}/download",
        }


class PptMediaAdapter:
    """Extracts approved document-contained media without changing ParsedFile flows."""

    def __init__(self, storage_root: Path | str | None = None) -> None:
        self.storage_root = Path(storage_root or Path(__file__).resolve().parents[2] / "data" / "ppt_media")
        self.resolver = PptMediaResolver()

    def _source_file(self, db: Session, *, source_file_id: int, owner_user_id: int) -> File:
        source = db.query(File).filter(
            File.id == source_file_id,
            or_(File.owner_user_id == owner_user_id, File.user_id == owner_user_id),
        ).first()
        if source is None:
            raise MediaAssetError("source_file_not_found")
        path = Path(source.real_path or source.filepath)
        if not path.is_file():
            raise MediaAssetError("source_file_not_found")
        return source

    @staticmethod
    def _zip_members(path: Path, prefix: str) -> list[tuple[str, bytes]]:
        from zipfile import BadZipFile, ZipFile
        try:
            with ZipFile(path) as archive:
                members = [item for item in archive.infolist() if item.filename.startswith(prefix) and not item.is_dir()]
                if len(members) > 100:
                    raise MediaAssetError("document_images_too_many")
                result: list[tuple[str, bytes]] = []
                for item in members:
                    if item.file_size > _MAX_BYTES:
                        continue
                    result.append((Path(item.filename).name, archive.read(item)))
                return result
        except BadZipFile as exc:
            raise MediaAssetError("document_images_invalid") from exc

    @staticmethod
    def _pdf_members(path: Path, destination: Path) -> list[tuple[str, bytes]]:
        import subprocess
        destination.mkdir(parents=True, exist_ok=True)
        prefix = destination / "pdfimage"
        try:
            subprocess.run(["pdfimages", "-png", str(path), str(prefix)], check=True, timeout=60, capture_output=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise MediaAssetError("document_images_unavailable") from exc
        return [(item.name, item.read_bytes()) for item in sorted(destination.glob("pdfimage-*.png")) if item.stat().st_size <= _MAX_BYTES]

    def extract_document_images(self, db: Session, *, project_id: str, owner_user_id: int, source_file_id: int) -> list[dict[str, Any]]:
        self.resolver._require_project(db, project_id=project_id, owner_user_id=owner_user_id)
        source = self._source_file(db, source_file_id=source_file_id, owner_user_id=owner_user_id)
        source_path = Path(source.real_path or source.filepath)
        suffix = source_path.suffix.lower()
        if suffix == ".docx":
            members = self._zip_members(source_path, "word/media/")
        elif suffix == ".pptx":
            members = self._zip_members(source_path, "ppt/media/")
        elif suffix == ".pdf":
            members = self._pdf_members(source_path, self.storage_root / f"source_{source.id}" / "pdf")
        else:
            raise MediaAssetError("document_images_unsupported")
        output = self.storage_root / f"source_{source.id}"
        output.mkdir(parents=True, exist_ok=True)
        assets: list[dict[str, Any]] = []
        seen: set[str] = set()
        for original_name, content in members:
            if len(content) > _MAX_BYTES:
                continue
            digest = hashlib.sha256(content).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            extension = Path(original_name).suffix.lower() or ".bin"
            target = output / f"{digest}{extension}"
            if not target.exists():
                target.write_bytes(content)
            try:
                mime, _, _ = _image_info(target)
            except MediaAssetError:
                target.unlink(missing_ok=True)
                continue
            record = db.query(File).filter(File.owner_user_id == owner_user_id, File.sha256 == digest).first()
            if record is None:
                record = File(
                    user_id=owner_user_id, owner_user_id=owner_user_id,
                    filename=f"extracted_{Path(original_name).name}", filepath=str(target), real_path=str(target),
                    filesize=target.stat().st_size, size=target.stat().st_size, filetype=extension,
                    mime_type=mime, sha256=digest,
                )
                db.add(record); db.flush()
            assets.append(self.resolver.register_file(
                db, file_id=record.id, owner_user_id=owner_user_id,
                source_type="document_extracted", project_id=project_id,
                source_file_id=source_file_id,
            ))
        return assets
