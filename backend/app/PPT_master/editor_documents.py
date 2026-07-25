"""Durable, revisioned editor drafts for generated incremental PPT projects."""

from __future__ import annotations

import copy
import hashlib
import html
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import File, PPTEditorDocument, PPTEditorExport, PPTIncrementalTask
from app.PPT_master.media_assets import PptMediaResolver
from app.PPT_master.native_data import has_native_elements, marker_svg, sidecar, validate_native_element
from app.PPT_master.validation import validate_pptx
from app.services.artifact_service import ArtifactService
import re

from app.PPT_master.structured_spec_lock import (
    build_structured_spec_lock_sections,
    install_structured_templates,
    KIND_TO_LAYOUT_KEY,
)


class EditorDocumentNotFound(LookupError):
    pass


class EditorDocumentConflict(RuntimeError):
    def __init__(self, project_id: str, revision: int):
        super().__init__(project_id)
        self.revision = revision


def _loads(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _number(value: str | None, default: float = 0) -> float | int:
    try:
        result = float(str(value or default).replace("px", ""))
    except ValueError:
        result = default
    return int(result) if isinstance(result, float) and result.is_integer() else result


def _style(node: ET.Element) -> dict[str, str]:
    style = dict(item.split(":", 1) for item in node.get("style", "").split(";") if ":" in item)
    return {**style, **node.attrib}


def _stable_id(slide_id: str, path: str, node: ET.Element) -> str:
    digest = hashlib.sha256(f"{path}|{ET.tostring(node, encoding='unicode')}".encode("utf-8")).hexdigest()[:16]
    return f"{slide_id}:el:{digest}"


def _structured_placeholder_bounds(bounds_raw: str | None) -> dict[str, float] | None:
    """Parse a 'x,y,width,height' data-pptx-placeholder-bounds attribute."""
    if not bounds_raw:
        return None
    parts = bounds_raw.split(",")
    if len(parts) != 4:
        return None
    try:
        x, y, width, height = (float(part.strip()) for part in parts)
    except ValueError:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _structured_carrier_text(node: ET.Element) -> ET.Element | None:
    """Return the single data-pptx-placeholder-carrier text child, if present."""
    for child in node:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "text" and (child.get("data-pptx-placeholder-carrier") or "").strip().lower() == "true":
            return child
    return None


def _placeholder_element(slide_id: str, path: str, node: ET.Element, z_index: int) -> dict[str, Any] | None:
    """Build an editable element for a data-pptx-placeholder <g>, or None if unsupported."""
    placeholder_type = node.get("data-pptx-placeholder")
    if not placeholder_type:
        return None
    bounds = _structured_placeholder_bounds(node.get("data-pptx-placeholder-bounds")) or {"x": 0, "y": 0, "width": 0, "height": 0}
    carrier = _structured_carrier_text(node)
    base = {
        "id": _stable_id(slide_id, path, node),
        "x": bounds["x"], "y": bounds["y"], "width": bounds["width"], "height": bounds["height"],
        "rotation": 0,
        "z_index": z_index,
        "placeholder_type": placeholder_type,
        "placeholder_idx": int(node.get("data-pptx-placeholder-idx") or 0),
        "bounds_locked": True,
    }
    if carrier is not None:
        carrier_attrs = _style(carrier)
        return {
            **base,
            "type": "text",
            "locked": False,
            "style": {
                "font_size": _number(carrier_attrs.get("font-size"), 18),
                "font_weight": _number(carrier_attrs.get("font-weight"), 400),
                "color": carrier_attrs.get("fill", "#000000"),
                "align": carrier_attrs.get("text-anchor", "left"),
            },
            "content": {"text": "".join(carrier.itertext()).strip()},
        }
    # Non-text placeholder (picture/chart carrier): position/bounds are fixed by
    # the Layout; content itself is not free-form editable in this slice.
    svg = ET.tostring(node, encoding="unicode").replace("ns0:", "").replace("xmlns:ns0=", "xmlns=")
    return {**base, "type": "lockedVector", "locked": True, "style": {"opacity": 1}, "content": {"svg": svg}}


def _svg_element(slide_id: str, path: str, node: ET.Element, z_index: int) -> dict[str, Any]:
    tag = node.tag.rsplit("}", 1)[-1]
    if tag == "g" and (node.get("data-pptx-role") or "") == "background":
        svg = ET.tostring(node, encoding="unicode").replace("ns0:", "").replace("xmlns:ns0=", "xmlns=")
        return {
            "id": _stable_id(slide_id, path, node), "x": 0, "y": 0, "width": 0, "height": 0,
            "rotation": 0, "z_index": z_index, "pptx_role": "background",
            "type": "lockedVector", "locked": True, "style": {"opacity": 1}, "content": {"svg": svg},
        }
    if tag == "g" and node.get("data-pptx-placeholder"):
        placeholder_element = _placeholder_element(slide_id, path, node, z_index)
        if placeholder_element is not None:
            return placeholder_element
    attrs = _style(node)
    x = _number(attrs.get("x"))
    y = _number(attrs.get("y"))
    width = _number(attrs.get("width"))
    height = _number(attrs.get("height"))
    if tag == "ellipse":
        x, y = _number(attrs.get("cx")) - _number(attrs.get("rx")), _number(attrs.get("cy")) - _number(attrs.get("ry"))
        width, height = _number(attrs.get("rx")) * 2, _number(attrs.get("ry")) * 2
    elif tag == "line":
        x, y = _number(attrs.get("x1")), _number(attrs.get("y1"))
        width, height = _number(attrs.get("x2")) - x, _number(attrs.get("y2")) - y
    base = {
        "id": _stable_id(slide_id, path, node), "x": x, "y": y, "width": width, "height": height,
        "rotation": _number(attrs.get("transform", "0").replace("rotate(", "").split()[0].replace(")", "")) if "rotate(" in attrs.get("transform", "") else 0,
        "z_index": z_index,
    }
    if tag in {"rect", "ellipse", "line"}:
        return {**base, "type": tag, "locked": False, "style": {"fill": attrs.get("fill", "none"), "stroke": attrs.get("stroke", "none"), "opacity": _number(attrs.get("opacity"), 1)}}
    if tag == "text":
        return {**base, "type": "text", "locked": False, "style": {"font_size": _number(attrs.get("font-size"), 18), "font_weight": _number(attrs.get("font-weight"), 400), "color": attrs.get("fill", "#000000"), "align": attrs.get("text-anchor", "left")}, "content": {"text": "".join(node.itertext()).strip()}}
    svg = ET.tostring(node, encoding="unicode").replace("ns0:", "").replace("xmlns:ns0=", "xmlns=")
    return {**base, "type": "lockedVector", "locked": True, "style": {"opacity": _number(attrs.get("opacity"), 1)}, "content": {"svg": svg}}


def _extract_slide_pptx_structure_from_svg(root: ET.Element) -> dict[str, Any]:
    """Capture the slide's Master/Layout identity, if declared on the SVG root.

    Returns {"mode": "flat"} when no structured metadata is present, or
    {"mode": "structured", "master_id": ..., "master_name": ..., "layout_id": ...,
     "layout_name": ..., "page_role": ...} when the root carries the full
    structured contract emitted by the generation pipeline.
    """
    layout_id = root.get("data-pptx-layout")
    if not layout_id:
        return {"mode": "flat"}
    return {
        "mode": "structured",
        "master_id": root.get("data-pptx-master") or "",
        "master_name": root.get("data-pptx-master-name") or "",
        "layout_id": layout_id,
        "layout_name": root.get("data-pptx-layout-name") or "",
        "page_role": root.get("data-pptx-page-role") or "",
    }


def _slide_from_svg(task: PPTIncrementalTask, source_slide: dict[str, Any], position: int, asset: File) -> dict[str, Any]:
    slide_id = str(source_slide.get("slide_id") or f"{task.task_id}:slide:{position}")
    root = ET.fromstring((asset.real_path or asset.filepath)) if False else ET.parse(asset.real_path or asset.filepath).getroot()
    elements: list[dict[str, Any]] = []
    for z_index, node in enumerate(list(root), start=1):
        elements.append(_svg_element(slide_id, f"/{z_index}", node, z_index))
    return {
        "slide_id": slide_id, "order": position, "width": 1280, "height": 720,
        "elements": elements, "pptx_structure": _extract_slide_pptx_structure_from_svg(root),
    }


def _initial_document(db: Session, task: PPTIncrementalTask) -> dict[str, Any]:
    completed_slides = _loads(task.completed_slides_json, [])
    slides = []
    for position, source_slide in enumerate(completed_slides, start=1):
        slide_id = str(source_slide.get("slide_id") or f"{task.task_id}:slide:{position}")
        preview_file_id = source_slide.get("preview_file_id")
        asset = db.query(File).filter(File.id == preview_file_id, File.owner_user_id == task.user_id, File.project_id == task.project_id, File.task_id == task.task_id, File.mime_type == "image/svg+xml").first()
        if asset is None or not (asset.real_path or asset.filepath):
            raise EditorDocumentNotFound(task.project_id)
        slides.append(_slide_from_svg(task, source_slide, position, asset))
    return {"project_id": task.project_id, "base_task_id": task.task_id, "slides": slides}


def _validate_document(document: dict[str, Any]) -> None:
    if not isinstance(document, dict) or not isinstance(document.get("slides"), list):
        raise ValueError("editor_document_invalid")
    for slide in document["slides"]:
        if not isinstance(slide, dict) or not isinstance(slide.get("slide_id"), str) or not isinstance(slide.get("elements"), list):
            raise ValueError("editor_document_invalid")
        for element in slide["elements"]:
            if not isinstance(element, dict) or element.get("type") not in {"text", "rect", "ellipse", "line", "image", "chart", "table", "lockedVector"}:
                raise ValueError("editor_document_invalid")
            if any(not isinstance(element.get(key), (int, float)) or abs(element[key]) > 100_000 for key in ("x", "y", "width", "height")):
                raise ValueError("editor_document_invalid")
            if element.get("type") in {"chart", "table"}:
                validate_native_element(element)
            if element.get("type") == "lockedVector":
                svg = str((element.get("content") or {}).get("svg") or "")
                if not svg or any(token in svg.lower() for token in ("<script", "javascript:", "foreignobject", "<iframe")):
                    raise ValueError("editor_document_invalid")
            if element.get("type") == "image":
                asset_id = element.get("asset_id")
                if not isinstance(asset_id, str) or not asset_id.startswith("pptimg_"):
                    raise ValueError("editor_document_invalid")
                if str(element.get("fit", "cover")) not in {"cover", "contain"}:
                    raise ValueError("editor_document_invalid")
                crop = element.get("crop", {})
                if not isinstance(crop, dict) or any(
                    not isinstance(crop.get(key, 0), (int, float)) or not 0 <= float(crop.get(key, 0)) < 1
                    for key in ("left", "top", "right", "bottom")
                ) or float(crop.get("left", 0)) + float(crop.get("right", 0)) >= 1 or float(crop.get("top", 0)) + float(crop.get("bottom", 0)) >= 1:
                    raise ValueError("editor_document_invalid")


def _validate_image_assets(db: Session, document: dict[str, Any], *, project_id: str, user_id: int) -> None:
    resolver = PptMediaResolver()
    for slide in document.get("slides", []):
        for element in slide.get("elements", []):
            if element.get("type") == "image" and resolver.asset_for_project(
                db, project_id=project_id, asset_id=str(element.get("asset_id", "")), owner_user_id=user_id,
            ) is None:
                raise ValueError("editor_image_unauthorized")


def _validate_locked_vectors_unchanged(stored_document: dict[str, Any], candidate: dict[str, Any]) -> None:
    stored_slides = {str(slide.get("slide_id")): slide for slide in stored_document.get("slides", []) if isinstance(slide, dict)}
    candidate_slides = {str(slide.get("slide_id")): slide for slide in candidate.get("slides", []) if isinstance(slide, dict)}
    if set(candidate_slides) != set(stored_slides):
        raise ValueError("editor_document_invalid")
    for slide_id, stored_slide in stored_slides.items():
        stored_vectors = {str(item.get("id")): item for item in stored_slide.get("elements", []) if isinstance(item, dict) and item.get("type") == "lockedVector"}
        candidate_slide = candidate_slides.get(slide_id)
        if not isinstance(candidate_slide, dict):
            raise ValueError("editor_document_invalid")
        candidate_vectors = {str(item.get("id")): item for item in candidate_slide.get("elements", []) if isinstance(item, dict) and item.get("type") == "lockedVector"}
        if candidate_vectors != stored_vectors:
            raise ValueError("editor_document_invalid")


def _task_final_file_id(task: PPTIncrementalTask) -> int | None:
    value = _loads(task.final_file_json, {}).get("file_id")
    return value if isinstance(value, int) and value > 0 else None


class EditorProjectStore:
    """Owner-scoped summaries for durable incremental projects."""

    def __init__(self, history_root: Path | str | None = None) -> None:
        self.history_root = Path(history_root or os.environ.get("PPT_HISTORY_ASSETS_ROOT") or Path(__file__).resolve().parents[2] / "data" / "ppt_history_assets")

    def _migrate_history_artifacts(self, db: Session, task: PPTIncrementalTask, user_id: int) -> None:
        records = (
            db.query(File)
            .filter(File.owner_user_id == user_id, File.project_id == task.project_id, File.task_id == task.task_id)
            .all()
        )
        changed = False
        for record in records:
            source = Path(record.real_path or record.filepath)
            if not source.is_file():
                continue
            target = self.history_root / task.project_id / f"{record.id}-{Path(record.filename).name}"
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not target.exists() or target.stat().st_size != source.stat().st_size or ArtifactService._sha256(target) != (record.sha256 or ArtifactService._sha256(source)):
                shutil.copyfile(source, target)
                target.chmod(0o600)
            resolved = target.resolve()
            record.real_path = str(resolved)
            record.filepath = str(resolved)
            record.filesize = resolved.stat().st_size
            record.size = record.filesize
            record.sha256 = ArtifactService._sha256(resolved)
            changed = True
        if changed:
            db.commit()

    @staticmethod
    def _summary(db: Session, task: PPTIncrementalTask, user_id: int) -> dict[str, Any]:
        completed_slides = _loads(task.completed_slides_json, [])
        preview_file_id = next(
            (
                item.get("preview_file_id")
                for item in completed_slides
                if isinstance(item, dict) and isinstance(item.get("preview_file_id"), int)
            ),
            None,
        )
        document = (
            db.query(PPTEditorDocument)
            .filter(PPTEditorDocument.project_id == task.project_id, PPTEditorDocument.user_id == user_id)
            .first()
        )
        original_file_id = document.original_file_id if document is not None else _task_final_file_id(task)
        latest_export = (
            db.query(PPTEditorExport)
            .filter(PPTEditorExport.project_id == task.project_id, PPTEditorExport.user_id == user_id)
            .order_by(PPTEditorExport.created_at.desc())
            .first()
        )
        preview_ids = [item.get("preview_file_id") for item in completed_slides if isinstance(item, dict)]
        available_assets = 0
        if preview_ids:
            available_assets = (
                db.query(File)
                .filter(File.id.in_(preview_ids), File.owner_user_id == user_id, File.project_id == task.project_id,
                        File.task_id == task.task_id, File.mime_type == "image/svg+xml")
                .count()
            )
        editor_supported = bool(
            task.status == "completed" and original_file_id
            and len(completed_slides) == int(task.page_count or 0)
            and len(preview_ids) == len(completed_slides) == available_assets
        )
        title = next(
            (str(item.get("title") or "") for item in completed_slides if isinstance(item, dict) and item.get("title")),
            "未命名 PPT",
        )
        return {
            "project_id": task.project_id,
            "task_id": task.task_id,
            "title": title,
            "status": task.status,
            "page_count": task.page_count,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            "original_file_id": original_file_id,
            "preview_file_id": preview_file_id,
            "thumbnail_url": f"/api/v1/files/{preview_file_id}/download" if preview_file_id else None,
            "editor_supported": editor_supported,
            "editor_revision": document.revision if document is not None else 1 if editor_supported else None,
            "last_export_file_id": latest_export.file_id if latest_export is not None else None,
            "generation_mode": "incremental",
        }

    def history(self, db: Session, *, project_id: str, user_id: int) -> dict[str, Any]:
        task = (
            db.query(PPTIncrementalTask)
            .filter(PPTIncrementalTask.project_id == project_id, PPTIncrementalTask.user_id == user_id)
            .first()
        )
        if task is None:
            raise EditorDocumentNotFound(project_id)

        self._migrate_history_artifacts(db, task, user_id)
        completed_slides = _loads(task.completed_slides_json, [])
        slides = [
            {
                "id": str(item.get("slide_id") or f"{task.task_id}:slide:{position}"),
                "index": int(item.get("index") or position),
                "title": str(item.get("title") or f"第 {position} 页"),
                "status": "error" if item.get("status") == "error" else "ready",
                "elements": [],
                "previewArtifactId": item.get("preview_file_id"),
                "thumbnailArtifactId": item.get("thumbnail_file_id") or item.get("preview_file_id"),
                "speakerNotes": str(item.get("notes") or ""),
                "userModifiedFields": [],
                "revision": int(item.get("revision") or 1),
            }
            for position, item in enumerate(completed_slides, start=1)
            if isinstance(item, dict)
        ]
        outline = [
            {
                "id": f"outline-{int(item.get('index') or position)}",
                "title": str(item.get("title") or f"第 {position} 页"),
                "description": str(item.get("content_brief") or item.get("description") or ""),
                "status": "ready",
                "children": [],
            }
            for position, item in enumerate(_loads(task.outline_json, []), start=1)
            if isinstance(item, dict)
        ]
        final_file = _loads(task.final_file_json, {})
        file_id = final_file.get("file_id") if isinstance(final_file, dict) else None
        export_artifact = None
        if isinstance(file_id, int) and file_id > 0:
            artifact = db.query(File).filter(File.id == file_id, File.owner_user_id == user_id).first()
            if artifact is not None:
                export_artifact = {
                    "fileId": file_id,
                    "downloadUrl": str(final_file.get("download_url") or f"/api/v1/files/{file_id}/download"),
                    "size": int(final_file.get("size") or artifact.size or artifact.filesize or 0),
                    "sha256": str(final_file.get("sha256") or artifact.sha256 or ""),
                    "valid": True,
                    "warnings": [str(item) for item in ((final_file.get("validation_result") or {}).get("warnings") or [])],
                    "slideCount": int(final_file.get("slide_count") or task.page_count or len(slides)),
                }
        title = slides[0]["title"] if slides else "未命名 PPT"
        return {
            "project": {
                "id": task.project_id,
                "title": title,
                "titleSource": "backend",
                "brief": {"goal": title, "audience": "", "slideCount": int(task.page_count or len(slides)), "constraints": []},
                "outline": outline,
                "presentation": {"aspectRatio": "16:9", "slides": slides},
                "theme": None,
                "validation": None,
                "exportArtifact": export_artifact,
                "version": 1,
                "createdAt": task.created_at.isoformat() if task.created_at else "",
                "updatedAt": task.updated_at.isoformat() if task.updated_at else "",
            }
        }

    def recent(self, db: Session, *, user_id: int, limit: int = 30) -> list[dict[str, Any]]:
        tasks = (
            db.query(PPTIncrementalTask)
            .filter(PPTIncrementalTask.user_id == user_id)
            .order_by(PPTIncrementalTask.updated_at.desc(), PPTIncrementalTask.created_at.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
        return [self._summary(db, task, user_id) for task in tasks]


class EditorExportConflict(RuntimeError):
    def __init__(self, revision: int):
        self.revision = revision
        super().__init__(str(revision))


class EditorExportFailed(RuntimeError):
    pass


def _svg_number(value: Any) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def _svg_style(value: Any, fallback: str) -> str:
    return html.escape(str(value if value not in (None, "") else fallback), quote=True)


def _element_svg(element: dict[str, Any]) -> str:
    kind = element.get("type")
    x, y = _svg_number(element["x"]), _svg_number(element["y"])
    width, height = _svg_number(element["width"]), _svg_number(element["height"])
    style = element.get("style") or {}
    elem_id = str(element.get("id") or "")
    if kind == "lockedVector":
        raw_svg = str((element.get("content") or {}).get("svg") or "")
        element_id = str(element.get("id") or "")
        if element_id and raw_svg and not raw_svg.strip().startswith("<g"):
            return f'<g id="{element_id}">{raw_svg}</g>'
        return raw_svg
    if kind in {"chart", "table"}:
        return marker_svg(element)
    if kind == "image":
        href = html.escape(str((element.get("content") or {}).get("resource") or ""), quote=True)
        if not href or "/" in href or "\\" in href:
            raise EditorExportFailed("editor_image_resource_invalid")
        fit = "xMidYMid slice" if element.get("fit", "cover") == "cover" else "xMidYMid meet"
        inner = '<image href="images/{0}" x="{1}" y="{2}" width="{3}" height="{4}" preserveAspectRatio="{5}"/>'.format(href, x, y, width, height, fit)
        eid = str(element.get("id") or "")
        return '<g id="{0}">{1}</g>'.format(eid, inner) if eid else inner
    if kind == "text":
        content = html.escape(str((element.get("content") or {}).get("text") or ""))
        font_size = _svg_number(style.get("font_size", 18))
        yp = _svg_number(float(element["y"]) + float(element["height"]))
        fw = _svg_style(style.get("font_weight"), "400")
        fc = _svg_style(style.get("color"), "#000000")
        inner = '<text x="{0}" y="{1}" font-size="{2}" font-weight="{3}" fill="{4}">{5}</text>'.format(x, yp, font_size, fw, fc, content)
        eid = str(element.get("id") or "")
        return '<g id="{0}">{1}</g>'.format(eid, inner) if eid else inner
    fill = _svg_style(style.get("fill"), "none")
    stroke = _svg_style(style.get("stroke"), "none")
    opacity = _svg_style(style.get("opacity"), "1")
    if kind == "rect":
        eid = str(element.get("id") or "")
        inner = '<rect x="{0}" y="{1}" width="{2}" height="{3}" fill="{4}" stroke="{5}" opacity="{6}"/>'.format(x, y, width, height, fill, stroke, opacity)
        return '<g id="{0}">{1}</g>'.format(eid, inner) if eid else inner
    if kind == "ellipse":
        eid = str(element.get("id") or "")
        cx = _svg_number(float(element["x"]) + float(element["width"]) / 2)
        cy = _svg_number(float(element["y"]) + float(element["height"]) / 2)
        rx = _svg_number(float(element["width"]) / 2)
        ry = _svg_number(float(element["height"]) / 2)
        inner = '<ellipse cx="{0}" cy="{1}" rx="{2}" ry="{3}" fill="{4}" stroke="{5}" opacity="{6}"/>'.format(cx, cy, rx, ry, fill, stroke, opacity)
        return '<g id="{0}">{1}</g>'.format(eid, inner) if eid else inner
    if kind == "line":
        eid = str(element.get("id") or "")
        x2 = _svg_number(float(element["x"]) + float(element["width"]))
        y2 = _svg_number(float(element["y"]) + float(element["height"]))
        inner = '<line x1="{0}" y1="{1}" x2="{2}" y2="{3}" stroke="{4}" opacity="{5}"/>'.format(x, y, x2, y2, stroke, opacity)
        return '<g id="{0}">{1}</g>'.format(eid, inner) if eid else inner
    raise EditorExportFailed("editor_element_unsupported")


def _write_animation_artifact(workspace: Path, animation_manifest: dict, document: dict[str, Any]) -> None:
    """Write animations.json in the format expected by svg_to_pptx engine.

    Engine format: {"version":1,"defaults":{"effect":"auto"},"slides":{"page_01":{"groups":{...}}}}
    Filters disabled, dangling, and lockedVector animations.
    """
    import json as _json

    elements_by_slide: dict[str, dict[str, tuple[str, bool]]] = {}
    for slide in document.get("slides", []):
        slide_id = slide.get("id") or slide.get("slide_id", "")
        if not slide_id:
            continue
        slide_elements: dict[str, tuple[str, bool]] = {}
        for el in slide.get("elements", []):
            eid = el.get("id", "")
            if eid:
                # Detect background: full-canvas rect with fill, no stroke (converter promotes to <p:bg>)
                w = el.get("width", 0)
                h = el.get("height", 0)
                t = el.get("type", "")
                fill = (el.get("style") or {}).get("fill", "none")
                stroke = (el.get("style") or {}).get("stroke", "none")
                is_bg = (t == "rect" and w == 1280 and h == 720 and fill != "none" and stroke == "none")
                slide_elements[eid] = (el.get("type", "unknown"), is_bg)
        elements_by_slide[slide_id] = slide_elements

    _EFFECT_MAP = {"fly_in": "fly"}
    _TRIGGER_MAP = {"on_click": "on-click", "with_previous": "with-previous", "after_previous": "after-previous"}

    engine_slides = {}
    doc_slides = document.get("slides", [])
    slide_order_map = {}
    for idx, s in enumerate(doc_slides, start=1):
        sid = s.get("id") or s.get("slide_id", "")
        if sid:
            slide_order_map[sid] = idx

    for slide_anim in animation_manifest.get("slides", []):
        page_idx = slide_order_map.get(slide_anim.get("slide_id", ""))
        if page_idx is None:
            raise EditorExportFailed("animation_slide_missing")
        page_key = "page_{:02d}".format(page_idx)
        slide_elements = elements_by_slide.get(slide_anim.get("slide_id", ""), {})

        groups = {}
        for anim in slide_anim.get("animations", []):
            if not anim.get("enabled", True):
                continue
            eid = anim.get("element_id", "")
            target = slide_elements.get(eid)
            if target is None:
                raise EditorExportFailed("animation_target_missing")
            element_type, is_background = target
            if element_type == "lockedVector":
                raise EditorExportFailed("animation_target_locked_vector")
            if is_background:
                raise EditorExportFailed("animation_target_background")

            effect = _EFFECT_MAP.get(anim.get("effect", "fade"), anim.get("effect", "fade"))
            groups[eid] = {
                "effect": effect,
                "duration": max(0.1, anim.get("duration_ms", 500) / 1000.0),
                "delay": max(0.0, anim.get("delay_ms", 0) / 1000.0),
                "order": anim.get("order", 1),
                "trigger": _TRIGGER_MAP[anim.get("trigger", "after_previous")],
            }

        if groups:
            engine_slides[page_key] = {
                "animation": {"effect": "auto", "trigger": "after-previous", "duration": 0.4},
                "groups": groups,
            }

    # Include ALL document slides in engine_slides (required by converter validation)
    for idx, s in enumerate(doc_slides, start=1):
        page_key = "page_{:02d}".format(idx)
        if page_key not in engine_slides:
            engine_slides[page_key] = {}  # Empty slide entry

    if not any(v for v in engine_slides.values()):
        return  # All slides empty, no animations

    output = {"version": 1, "defaults": {"animation": {"effect": "auto", "trigger": "after-previous", "duration": 0.4, "stagger": 0.5}}, "slides": engine_slides}
    (workspace / "animations.json").write_text(_json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
def _stage_editor_images(db: Session, workspace: Path, document: dict[str, Any], *, project_id: str, user_id: int) -> None:
    images = workspace / "images"
    image_elements = [item for slide in document.get("slides", []) for item in slide.get("elements", []) if item.get("type") == "image"]
    if not image_elements:
        return
    images.mkdir(parents=True, exist_ok=False)
    resolver = PptMediaResolver()
    copied: dict[str, str] = {}
    manifest: list[dict[str, Any]] = []
    for element in image_elements:
        asset_id = str(element["asset_id"])
        asset = resolver.asset_for_project(db, project_id=project_id, asset_id=asset_id, owner_user_id=user_id)
        if asset is None:
            raise EditorExportFailed("editor_image_unauthorized")
        source = Path(asset_file.real_path or asset_file.filepath) if (asset_file := db.query(File).filter(File.id == asset.file_id).first()) else None
        suffix = source.suffix.lower() if source else ""
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"} or not source.is_file():
            raise EditorExportFailed("editor_image_invalid")
        crop = element.get("crop") or {}
        crop_key = f"{asset_id}:{float(crop.get('left', 0))}:{float(crop.get('top', 0))}:{float(crop.get('right', 0))}:{float(crop.get('bottom', 0))}"
        if crop_key not in copied:
            if any(float(crop.get(key, 0)) > 0 for key in ("left", "top", "right", "bottom")):
                from PIL import Image
                with Image.open(source) as image:
                    source_width, source_height = image.size
                    left = round(source_width * float(crop.get("left", 0)))
                    top = round(source_height * float(crop.get("top", 0)))
                    right = source_width - round(source_width * float(crop.get("right", 0)))
                    bottom = source_height - round(source_height * float(crop.get("bottom", 0)))
                    if left >= right or top >= bottom:
                        raise EditorExportFailed("editor_image_crop_invalid")
                    name = f"{asset_id}_{hashlib.sha256(crop_key.encode()).hexdigest()[:12]}.png"
                    image.crop((left, top, right, bottom)).save(images / name, "PNG")
            else:
                name = f"{asset_id}{suffix}"
                shutil.copyfile(source, images / name)
            copied[crop_key] = name
            manifest.append({"asset_id": asset.asset_id, "file_id": asset.file_id, "resource": name, "mime_type": asset.mime_type, "sha256": asset.sha256, "crop": crop})
        element.setdefault("content", {})["resource"] = copied[crop_key]
    (images / "image_manifest.json").write_text(_dumps({"assets": manifest}), encoding="utf-8")


def _get_editor_slide_pptx_structure(slide: dict[str, Any]) -> dict[str, Any] | None:
    """Return a slide's captured pptx_structure metadata, or None for flat slides."""
    structure = slide.get("pptx_structure")
    if not isinstance(structure, dict) or structure.get("mode") != "structured":
        return None
    return structure


def _structured_layout_template_basename(layout_id: str) -> str:
    return layout_id.replace("-", "_")


def _wire_structured_slide_svg(slide: dict[str, Any], structure: dict[str, Any], *, templates_dir: Path) -> str:
    """Deterministically rebuild a structured slide's SVG from its template skeleton,
    substituting only the (possibly edited) placeholder text content.

    Raises EditorExportFailed if any placeholder element cannot be mapped back onto
    the layout template's contract (missing type/idx, missing carrier, count
    mismatch). Never falls back to flat output on failure.
    """
    layout_id = structure.get("layout_id")
    master_id = structure.get("master_id")
    if not layout_id or not master_id:
        raise EditorExportFailed("editor_structured_layout_missing")

    template_path = templates_dir / f"{_structured_layout_template_basename(layout_id)}.svg"
    if not template_path.is_file():
        raise EditorExportFailed("editor_structured_template_missing")
    template_svg = template_path.read_text(encoding="utf-8")

    try:
        root = ET.fromstring(template_svg)
    except ET.ParseError as exc:
        raise EditorExportFailed("editor_structured_template_invalid") from exc

    placeholder_elements = {
        (str(item.get("placeholder_type")), int(item.get("placeholder_idx")))
        for item in slide.get("elements", [])
        if isinstance(item, dict) and item.get("placeholder_type") is not None and item.get("placeholder_idx") is not None
    }
    text_content_by_key: dict[tuple[str, int], str] = {}
    for item in slide.get("elements", []):
        if not isinstance(item, dict):
            continue
        ptype = item.get("placeholder_type")
        pidx = item.get("placeholder_idx")
        if ptype is None or pidx is None:
            continue
        if item.get("type") != "text":
            continue
        text_content_by_key[(str(ptype), int(pidx))] = str((item.get("content") or {}).get("text") or "")

    result = template_svg
    for child in list(root):
        placeholder_type = child.get("data-pptx-placeholder")
        idx_raw = child.get("data-pptx-placeholder-idx")
        if not placeholder_type or idx_raw is None:
            continue
        idx = int(idx_raw)
        key = (placeholder_type, idx)
        if placeholder_type not in {"title", "subtitle", "body"}:
            continue
        if key not in placeholder_elements:
            raise EditorExportFailed(
                f"editor_structured_placeholder_missing:{placeholder_type}:{idx}"
            )
        if key not in text_content_by_key:
            raise EditorExportFailed(
                f"editor_structured_placeholder_not_text:{placeholder_type}:{idx}"
            )
        content = text_content_by_key[key]
        escaped = (
            content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        pattern = re.compile(
            r'(data-pptx-placeholder-idx="' + re.escape(str(idx)) + r'"[^>]*>\s*'
            r'<text\b[^>]*data-pptx-placeholder-carrier="true"[^>]*>)'
            r'[^<]*'
            r'(</text>)'
        )
        new_result, count = pattern.subn(
            lambda m: m.group(1) + escaped + m.group(2), result, count=1
        )
        if count != 1:
            raise EditorExportFailed(
                f"editor_structured_carrier_not_found:{placeholder_type}:{idx}"
            )
        result = new_result

    # The layout template's deck-wide background <g data-pptx-role="background">
    # must carry a stable id (required by the converter's Layer/Layout contract).
    # Raise never degrades to flat output.
    result = _ensure_structured_background_id(result)

    return result


def _ensure_structured_background_id(svg_text: str) -> str:
    """Add a stable id to the deck-wide background <g>, if missing.

    Mirrors the generation pipeline's _ensure_background_id intent but targets
    the <g data-pptx-role="background"> wrapper (which the structured converter's
    semantic-markers contract requires to carry a stable id).
    """
    pattern = re.compile(r'<g\b(?=[^>]*\bdata-pptx-role="background")(?![^>]*\bid=)[^>]*>')
    return pattern.sub(lambda m: m.group(0).replace('<g', '<g id="bg-1"', 1), svg_text, count=1)
def _build_structured_export_spec_lock(slides_structure: list[dict[str, Any]]) -> str:
    """Build the full structured spec_lock.md contract for all structured slides."""
    layout_assignments = []
    for structure in slides_structure:
        layout_id = structure.get("layout_id")
        if not layout_id:
            raise EditorExportFailed("editor_structured_layout_missing")
        layout_assignments.append(layout_id)
    sections = build_structured_spec_lock_sections(layout_assignments=layout_assignments)
    return (
        "## canvas\n- viewBox: 0 0 1280 720\n- format: PPT 16:9\n\n"
        "## colors\n- bg: #FFFFFF\n- primary: #2563EB\n- accent: #DBEAFE\n- text: #111827\n- text_secondary: #475569\n- border: #CBD5E1\n\n"
        "## typography\n- font_family: \"Microsoft YaHei\", Arial, sans-serif\n- title: 42\n- body: 24\n\n"
        "## pptx_structure\n- mode: structured\n- template_adherence: adaptive\n"
        + sections
    )


def _write_editor_workspace(workspace: Path, document: dict[str, Any], animation_manifest: dict | None = None) -> int:
    slides = list(document.get("slides") or [])
    if not slides:
        raise EditorExportFailed("editor_document_empty")
    output = workspace / "svg_output"
    output.mkdir(parents=True, exist_ok=False)

    structured_templates_dir = Path(__file__).resolve().parent / "structured_templates"
    slide_structures: list[dict[str, Any]] = []
    any_structured = False

    for index, slide in enumerate(slides, start=1):
        structure = _get_editor_slide_pptx_structure(slide)
        if structure is not None:
            any_structured = True
            slide_structures.append(structure)
            slide_svg = _wire_structured_slide_svg(slide, structure, templates_dir=structured_templates_dir)
            slide_local = [
                item
                for item in sorted(slide.get("elements") or [], key=lambda item: int(item.get("z_index", 0)))
                if isinstance(item, dict)
                and not item.get("placeholder_type")
                and item.get("pptx_role") != "background"
            ]
            if slide_local:
                body = "".join(_element_svg(item) for item in slide_local)
                slide_svg = slide_svg.replace("</svg>", body + "</svg>", 1)
        else:
            elements = sorted(slide.get("elements") or [], key=lambda item: int(item.get("z_index", 0)))
            body = "".join(_element_svg(item) for item in elements)
            slide_svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" '
                f'viewBox="0 0 1280 720">{body}</svg>'
            )
        (output / f"page_{index:02d}.svg").write_text(slide_svg, encoding="utf-8")

    (workspace / "native_data.json").write_text(_dumps(sidecar(document)), encoding="utf-8")
    (workspace / "design_spec.md").write_text("# Editor export\n", encoding="utf-8")
    if any_structured:
        install_structured_templates(workspace)
        spec_lock = _build_structured_export_spec_lock(slide_structures)
    else:
        spec_lock = "\n".join([
            "## canvas",
            "- viewBox: 0 0 1280 720",
            "- format: PPT 16:9",
            "",
            "## colors",
            "- bg: #FFFFFF",
            "- primary: #2563EB",
            "- accent: #DBEAFE",
            "- text: #111827",
            "- text_secondary: #475569",
            "- border: #CBD5E1",
            "",
            "## typography",
            '- font_family: "Microsoft YaHei", Arial, sans-serif',
            "- title: 42",
            "- body: 24",
            "",
            "## pptx_structure",
            "- mode: flat",
        ])
    (workspace / "spec_lock.md").write_text(spec_lock, encoding="utf-8")
    if animation_manifest:
        _write_animation_artifact(workspace, animation_manifest, document)
    return len(slides)

class EditorExportStore:
    """Append-only PPTX exports of an immutable editor revision."""

    def __init__(
        self,
        *,
        projects_root: Path | str | None = None,
        artifact_service: ArtifactService | None = None,
        command_runner: Callable[[Path, int], Path] | None = None,
    ) -> None:
        self.projects_root = Path(projects_root or Path(__file__).resolve().parent / "projects")
        self.artifacts = artifact_service or ArtifactService(projects_root=self.projects_root)
        self.command_runner = command_runner

    @staticmethod
    def _snapshot(record: PPTEditorExport) -> dict[str, Any]:
        return {
            "export_id": record.export_id,
            "project_id": record.project_id,
            "revision": record.revision,
            "file_id": record.file_id,
            "sha256": record.sha256,
            "size": record.filesize,
            "download_url": f"/api/v1/files/{record.file_id}/download",
            "report": copy.deepcopy(_loads(record.report_json, {})),
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    def _run_converter(self, workspace: Path, page_count: int) -> Path:
        if self.command_runner is not None:
            return Path(self.command_runner(workspace, page_count))
        scripts = Path(__file__).resolve().parent / "skill" / "ppt-master" / "scripts"
        python = os.environ.get("PPT_MASTER_PYTHON", str(Path.home() / ".config" / "ai-box" / "runtime" / "ppt-master-venv" / "bin" / "python3"))
        try:
            for script in ("svg_quality_checker.py", "finalize_svg.py", "svg_to_pptx.py"):
                command = [python, str(scripts / script), str(workspace)]
                if script == "svg_to_pptx.py":
                    animation_config_path = workspace / "animations.json"
                    if animation_config_path.exists():
                        command.append("--animation-config")
                        command.append(str(animation_config_path))
                if script == "svg_to_pptx.py" and any("data-pptx-replace-with" in item.read_text(encoding="utf-8") for item in (workspace / "svg_output").glob("*.svg")):
                    command.append("--native-charts-and-tables")
                # quality_checker warns about cosmetic issues; never fatal
                subprocess.run(command, check=True, timeout=300, capture_output=True, text=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise EditorExportFailed("editor_export_conversion_failed") from exc
        files = sorted((workspace / "exports").glob("*.pptx"), key=lambda item: item.stat().st_mtime, reverse=True)
        if not files:
            raise EditorExportFailed("editor_export_missing")
        return files[0]

    def export(self, db: Session, *, project_id: str, user_id: int, expected_revision: int) -> dict[str, Any]:
        document = (db.query(PPTEditorDocument).filter(PPTEditorDocument.project_id == project_id, PPTEditorDocument.user_id == user_id).first())
        if document is None:
            EditorDocumentStore().get_or_initialize(db, project_id=project_id, user_id=user_id)
            document = (db.query(PPTEditorDocument).filter(PPTEditorDocument.project_id == project_id, PPTEditorDocument.user_id == user_id).first())
        if document is None:
            raise EditorDocumentNotFound(project_id)
        if document.revision != expected_revision:
            raise EditorExportConflict(document.revision)
        # Capture this immutable revision before converter/artifact commits can
        # expire the ORM object or a later PATCH advances the live draft.
        snapshot_revision = document.revision
        snapshot_document_id = document.document_id
        snapshot_task_id = document.base_task_id
        document_json = copy.deepcopy(_loads(document.document_json, {}))
        _validate_document(document_json)
        workspace = self.projects_root / f"pptedit_{project_id}_{uuid.uuid4().hex}"
        _stage_editor_images(db, workspace, document_json, project_id=project_id, user_id=user_id)
        # P4: Animation manifests must be readable. Exporting a requested
        # animation as a static deck is data loss, not a safe fallback.
        animation_manifest = None
        try:
            from app.PPT_master.animation_models import PPTAnimationManifest
            anim_row = (
                db.query(PPTAnimationManifest)
                .filter(
                    PPTAnimationManifest.project_id == project_id,
                    PPTAnimationManifest.user_id == user_id,
                )
                .order_by(PPTAnimationManifest.animation_revision.desc())
                .first()
            )
            if anim_row is not None:
                animation_manifest = json.loads(anim_row.animations_json)
        except Exception as exc:
            raise EditorExportFailed("editor_animation_manifest_unavailable") from exc
        page_count = _write_editor_workspace(workspace, document_json, animation_manifest)
        pptx_path = self._run_converter(workspace, page_count)
        # P4: Check if animation manifest was used
        animation_revision_snapshot = animation_manifest.get("animation_revision", 0) if animation_manifest else 0
        validation = validate_pptx(str(pptx_path), expected_pages=page_count)
        if not validation.get("passed"):
            raise EditorExportFailed("editor_export_validation_failed")
        record = self.artifacts.register_pptx(db, owner_user_id=user_id, project_id=project_id, task_id=document.base_task_id, real_path=pptx_path)
        export = PPTEditorExport(
            export_id="ppexport_" + uuid.uuid4().hex, project_id=project_id, base_task_id=snapshot_task_id,
            document_id=snapshot_document_id, user_id=user_id, revision=snapshot_revision, file_id=record.id,
            sha256=record.sha256 or "", filesize=record.size or record.filesize, report_json=_dumps({"validation": validation, "page_count": page_count, "animation_revision": animation_revision_snapshot}),
        )
        db.add(export)
        db.commit()
        db.refresh(export)
        return self._snapshot(export)

    def list(self, db: Session, *, project_id: str, user_id: int) -> list[dict[str, Any]]:
        records = (db.query(PPTEditorExport).filter(PPTEditorExport.project_id == project_id, PPTEditorExport.user_id == user_id).order_by(PPTEditorExport.created_at.desc()).all())
        return [self._snapshot(record) for record in records]


class EditorDocumentStore:
    def _task(self, db: Session, project_id: str, user_id: int) -> PPTIncrementalTask:
        task = (
            db.query(PPTIncrementalTask)
            .filter(PPTIncrementalTask.project_id == project_id, PPTIncrementalTask.user_id == user_id)
            .order_by(PPTIncrementalTask.created_at.desc())
            .first()
        )
        if task is None:
            raise EditorDocumentNotFound(project_id)
        return task

    @staticmethod
    def _snapshot(document: PPTEditorDocument) -> dict[str, Any]:
        return {
            "document_id": document.document_id,
            "project_id": document.project_id,
            "base_task_id": document.base_task_id,
            "original_file_id": document.original_file_id,
            "revision": document.revision,
            "document": copy.deepcopy(_loads(document.document_json, {})),
        }

    def get_or_initialize(self, db: Session, *, project_id: str, user_id: int) -> dict[str, Any]:
        document = (
            db.query(PPTEditorDocument)
            .filter(PPTEditorDocument.project_id == project_id, PPTEditorDocument.user_id == user_id)
            .first()
        )
        if document is None:
            task = self._task(db, project_id, user_id)
            original_file_id = _task_final_file_id(task)
            if original_file_id is None:
                raise EditorDocumentNotFound(project_id)
            document = PPTEditorDocument(
                document_id="pptedit_" + uuid.uuid4().hex,
                project_id=project_id,
                base_task_id=task.task_id,
                user_id=user_id,
                original_file_id=original_file_id,
                revision=1,
                document_json=_dumps(_initial_document(db, task)),
            )
            db.add(document)
            db.commit()
            db.refresh(document)
        return self._snapshot(document)

    def save(
        self,
        db: Session,
        *,
        project_id: str,
        user_id: int,
        expected_revision: int,
        document: dict[str, Any],
    ) -> dict[str, Any]:
        stored = (
            db.query(PPTEditorDocument)
            .filter(PPTEditorDocument.project_id == project_id, PPTEditorDocument.user_id == user_id)
            .first()
        )
        if stored is None:
            raise EditorDocumentNotFound(project_id)
        if stored.revision != expected_revision:
            raise EditorDocumentConflict(project_id, stored.revision)
        _validate_document(document)
        _validate_image_assets(db, document, project_id=project_id, user_id=user_id)
        _validate_locked_vectors_unchanged(_loads(stored.document_json, {}), document)
        result = db.execute(
            update(PPTEditorDocument)
            .where(PPTEditorDocument.document_id == stored.document_id, PPTEditorDocument.revision == expected_revision)
            .values(document_json=_dumps(document), revision=expected_revision + 1)
        )
        if result.rowcount != 1:
            db.rollback()
            current = db.query(PPTEditorDocument.revision).filter(PPTEditorDocument.document_id == stored.document_id).scalar()
            raise EditorDocumentConflict(project_id, int(current or expected_revision))
        db.commit()
        db.refresh(stored)
        return self._snapshot(stored)
