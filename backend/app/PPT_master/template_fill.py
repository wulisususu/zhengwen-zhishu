"""Native-PPTX template fill state and OOXML adapter boundary."""
from __future__ import annotations

import hashlib
import json
import posixpath
import uuid
import zipfile
import sys
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

_UPSTREAM_SCRIPTS = Path(__file__).resolve().parent / "skill" / "ppt-master" / "scripts"
if str(_UPSTREAM_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_UPSTREAM_SCRIPTS))
from template_fill_pptx import analyze_pptx as _analyze_pptx
from template_fill_pptx import check_plan as _check_plan
from template_fill_pptx import apply_plan as _apply_plan
from template_fill_pptx.ooxml import NS as _OOXML_NS, _parse_slide_refs, _slide_relationships, _normalize_part, _read_xml

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import File, PPTTemplate, PPTTemplateFillPlan, PPTTemplateFillTask
from app.services.artifact_service import ArtifactService

_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_MAX_TEMPLATE_BYTES = 80 * 1024 * 1024
_MAX_TEMPLATE_SLIDES = 100


class TemplateFillPlanNotConfirmed(RuntimeError):
    pass


class TemplateFillPlanConflict(RuntimeError):
    pass


class TemplateFillPlanImmutable(RuntimeError):
    pass


class TemplateFillError(ValueError):
    pass


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()




def _with_slot_confidence(library: dict[str, Any]) -> dict[str, Any]:
    """Add explainable candidates from several independent signals, not text alone."""
    slides = library.get("slides", [])
    for slide in slides if isinstance(slides, list) else []:
        page_role = str(slide.get("page_type") or "")
        for slot in slide.get("slots", []) if isinstance(slide, dict) else []:
            role = str(slot.get("role") or "")
            text = str(slot.get("text") or "").strip()
            name = str(slot.get("shape_name") or "").lower()
            geometry = slot.get("geometry") if isinstance(slot.get("geometry"), dict) else {}
            metrics = slot.get("text_metrics") if isinstance(slot.get("text_metrics"), dict) else {}
            placeholder = slot.get("placeholder") if isinstance(slot.get("placeholder"), dict) else {}
            reasons: list[str] = []
            confidence = 0.25
            ph_type = str(placeholder.get("type") or "").lower()
            if ph_type in {"title", "ctrtitle", "subTitle".lower(), "body", "obj"}:
                confidence += 0.42; reasons.append(f"placeholder:{ph_type}")
            if role in {"title", "subtitle", "body"}:
                confidence += 0.2; reasons.append(f"role:{role}")
            elif role == "label":
                confidence += 0.05; reasons.append("role:label")
            if any(token in name for token in ("title", "subtitle", "body", "content")):
                confidence += 0.12; reasons.append("shape_name_semantic")
            if text:
                confidence += 0.06; reasons.append("existing_text")
            font_size = metrics.get("font_size_px")
            if isinstance(font_size, (int, float)) and font_size >= 24:
                confidence += 0.08; reasons.append("font_hierarchy")
            height = geometry.get("height")
            y = geometry.get("y")
            is_small_footer = (isinstance(font_size, (int, float)) and font_size <= 10) or (isinstance(height, (int, float)) and height <= 28 and isinstance(y, (int, float)) and y >= 600)
            if is_small_footer or any(token in name for token in ("legal", "footer", "copyright", "confidential")):
                confidence -= 0.45; reasons.append("small_footer_or_legal")
            if page_role in {"cover", "title"} and role in {"title", "subtitle"}:
                confidence += 0.08; reasons.append("page_role_match")
            slot["confidence"] = round(max(0.0, min(0.98, confidence)), 2)
            slot["inference_reasons"] = reasons
            slot["fillable"] = slot["confidence"] >= 0.55 and "small_footer_or_legal" not in reasons
    return library

def _replace_output_images(pptx_path: Path, replacements: list[dict[str, Any]]) -> None:
    """Swap only p:pic image relationships after upstream cloning; frame XML stays intact."""
    if not replacements:
        return
    with zipfile.ZipFile(pptx_path) as archive:
        entries = {item.filename: archive.read(item.filename) for item in archive.infolist() if not item.is_dir()}
    slide_parts = sorted(name for name in entries if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
    rel_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    image_counter = 0
    for replacement in replacements:
        position = int(replacement.get("output_slide_position", 0)) - 1
        if position < 0 or position >= len(slide_parts):
            raise TemplateFillError("template_fill_image_slide_invalid")
        image_path = Path(replacement.get("image_path") or "")
        if image_path.suffix.lower() not in {".png", ".jpg", ".jpeg"} or not image_path.is_file():
            raise TemplateFillError("template_fill_image_invalid")
        slide_part = slide_parts[position]
        rel_part = f"{slide_part.rsplit('/', 1)[0]}/_rels/{slide_part.rsplit('/', 1)[1]}.rels"
        if rel_part not in entries:
            raise TemplateFillError("template_fill_image_relationship_missing")
        root = ET.fromstring(entries[slide_part]); rel_root = ET.fromstring(entries[rel_part])
        shape_id = str(replacement.get("shape_id") or "")
        picture = next((node for node in root.findall(".//p:pic", _OOXML_NS) if (node.find(".//p:cNvPr", _OOXML_NS) is not None and node.find(".//p:cNvPr", _OOXML_NS).attrib.get("id") == shape_id)), None)
        if picture is None:
            raise TemplateFillError("template_fill_image_target_missing")
        blip = picture.find(".//a:blip", _OOXML_NS)
        embed = blip.attrib.get(f"{{{_OOXML_NS['r']}}}embed") if blip is not None else None
        relationship = next((node for node in rel_root.findall(f"{{{rel_namespace}}}Relationship") if node.attrib.get("Id") == embed and node.attrib.get("Type", "").endswith("/image")), None)
        if relationship is None:
            raise TemplateFillError("template_fill_image_relationship_missing")
        image_counter += 1
        suffix = ".jpg" if image_path.suffix.lower() in {".jpg", ".jpeg"} else ".png"
        media_part = f"ppt/media/template-fill-{image_counter}-{uuid.uuid4().hex[:12]}{suffix}"
        entries[media_part] = image_path.read_bytes()
        relationship.attrib["Target"] = f"../media/{Path(media_part).name}"
        entries[rel_part] = ET.tostring(rel_root, encoding="utf-8", xml_declaration=True)
    with tempfile.NamedTemporaryFile(prefix="template-fill-media-", suffix=".pptx", dir=pptx_path.parent, delete=False) as handle:
        candidate = Path(handle.name)
    try:
        with zipfile.ZipFile(candidate, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in entries.items():
                archive.writestr(name, value)
        candidate.replace(pptx_path)
    finally:
        candidate.unlink(missing_ok=True)

def _enrich_template_library(source_path: Path, library: dict[str, Any]) -> dict[str, Any]:
    """Add read-only OOXML facts needed by the UI while retaining upstream analysis."""
    library = dict(library)
    library.pop("source_pptx", None)
    slides_by_index = {int(item.get("slide_index", 0)): item for item in library.get("slides", [])}
    theme: dict[str, Any] = {"major_font": None, "minor_font": None, "colors": {}}
    with zipfile.ZipFile(source_path) as archive:
        names = set(archive.namelist())
        if "ppt/_rels/presentation.xml.rels" not in names:
            library["theme"] = theme
            return library
        for name in sorted(name for name in names if name.startswith("ppt/theme/") and name.endswith(".xml"))[:1]:
            root = ET.fromstring(archive.read(name))
            major = root.find(".//a:fontScheme/a:majorFont/a:latin", _OOXML_NS)
            minor = root.find(".//a:fontScheme/a:minorFont/a:latin", _OOXML_NS)
            theme["major_font"] = major.attrib.get("typeface") if major is not None else None
            theme["minor_font"] = minor.attrib.get("typeface") if minor is not None else None
            for color in root.findall(".//a:clrScheme/*", _OOXML_NS):
                value = color.find("a:srgbClr", _OOXML_NS) or color.find("a:sysClr", _OOXML_NS)
                if value is not None:
                    theme["colors"][color.tag.rsplit("}", 1)[-1]] = value.attrib.get("val") or value.attrib.get("lastClr")
        for ref in _parse_slide_refs(archive):
            slide = slides_by_index.get(ref.index)
            if slide is None:
                continue
            slide["slide_id"] = ref.rel_id
            slide["slide_part"] = ref.part_name
            root = _read_xml(archive, ref.part_name)
            rels = _slide_relationships(archive, ref.rels_name)
            layout_rel = next((item for item in rels.values() if item.get("type", "").endswith("/slideLayout")), None)
            layout: dict[str, Any] = {"layout_part": None, "master_part": None}
            if layout_rel:
                layout_part = _normalize_part(layout_rel["target"], ref.part_name)
                layout["layout_part"] = layout_part
                layout_rels = _slide_relationships(archive, f"{layout_part.rsplit('/', 1)[0]}/_rels/{layout_part.rsplit('/', 1)[1]}.rels")
                master_rel = next((item for item in layout_rels.values() if item.get("type", "").endswith("/slideMaster")), None)
                if master_rel:
                    layout["master_part"] = _normalize_part(master_rel["target"], layout_part)
            slide["layout"] = layout
            slot_by_id = {str(item.get("slot_id")): item for item in slide.get("slots", [])}
            for slot in slide.get("slots", []):
                slot_id = str(slot.get("slot_id") or "")
                if not slot.get("shape_id") and "_sh" in slot_id:
                    slot["shape_id"] = slot_id.rsplit("_sh", 1)[-1]
            placeholders, images, locked = [], [], []
            for shape in root.findall(".//p:sp", _OOXML_NS):
                c_nv_pr = shape.find(".//p:cNvPr", _OOXML_NS)
                shape_id = str(c_nv_pr.attrib.get("id")) if c_nv_pr is not None else ""
                name = c_nv_pr.attrib.get("name", "") if c_nv_pr is not None else ""
                slot = slot_by_id.get(f"s{ref.index:02d}_sh{shape_id}")
                ph = shape.find(".//p:ph", _OOXML_NS)
                if slot is not None:
                    slot["shape_id"] = shape_id; slot["shape_name"] = name
                    if ph is not None:
                        slot["placeholder"] = {"type": ph.attrib.get("type", "obj"), "idx": ph.attrib.get("idx")}
                if ph is not None:
                    placeholders.append({"shape_id": shape_id, "shape_name": name, "type": ph.attrib.get("type", "obj"), "idx": ph.attrib.get("idx")})
            for picture in root.findall(".//p:pic", _OOXML_NS):
                c_nv_pr = picture.find(".//p:cNvPr", _OOXML_NS)
                images.append({"shape_id": str(c_nv_pr.attrib.get("id")) if c_nv_pr is not None else "", "shape_name": c_nv_pr.attrib.get("name", "") if c_nv_pr is not None else ""})
            for tag, kind in (("p:grpSp", "group"), ("p:cxnSp", "connector"), ("p:contentPart", "content_part"), ("p:oleObj", "ole")):
                for node in root.findall(f".//{tag}", _OOXML_NS):
                    c_nv_pr = node.find(".//p:cNvPr", _OOXML_NS)
                    locked.append({"kind": kind, "shape_id": str(c_nv_pr.attrib.get("id")) if c_nv_pr is not None else None, "shape_name": c_nv_pr.attrib.get("name", "") if c_nv_pr is not None else ""})
            for table in slide.get("tables", []):
                table_id = str(table.get("table_id") or "")
                table["shape_id"] = table_id.rsplit("tbl", 1)[-1] if "tbl" in table_id else table_id
            for chart in slide.get("charts", []):
                chart_id = str(chart.get("chart_id") or "")
                chart["shape_id"] = chart_id.rsplit("ch", 1)[-1] if "ch" in chart_id else chart_id
            slide["placeholders"] = placeholders
            slide["images"] = images
            slide["locked_objects"] = locked
    library["theme"] = theme
    return library

def _render_template_previews(source_path: Path, target_dir: Path, slide_count: int) -> list[Path]:
    """Render a copied input in an isolated scratch directory; never re-save the template."""
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="template-preview-", dir=target_dir.parent) as scratch_text:
        scratch = Path(scratch_text)
        copied_source = scratch / "source.pptx"
        shutil.copy2(source_path, copied_source)
        command = ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(scratch), str(copied_source)]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90, check=False)
        pdf_path = scratch / "source.pdf"
        if result.returncode != 0 or not pdf_path.is_file():
            raise TemplateFillError("template_preview_render_failed")
        prefix = scratch / "slide"
        rendered = subprocess.run(["pdftoppm", "-png", "-r", "110", str(pdf_path), str(prefix)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90, check=False)
        images = sorted(scratch.glob("slide-*.png"))
        if rendered.returncode != 0 or len(images) != slide_count:
            raise TemplateFillError("template_preview_page_count_invalid")
        results: list[Path] = []
        for index, image in enumerate(images, start=1):
            destination = target_dir / f"page_{index:02d}.png"
            shutil.copyfile(image, destination)
            destination.chmod(0o600)
            results.append(destination)
        return results

def _safe_pptx(path: Path) -> None:
    if path.suffix.lower() != ".pptx" or not path.is_file() or path.stat().st_size > _MAX_TEMPLATE_BYTES:
        raise TemplateFillError("template_file_invalid")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > 5000:
                raise TemplateFillError("template_zip_invalid")
            total = sum(item.file_size for item in infos)
            compressed = max(1, sum(item.compress_size for item in infos))
            if total > _MAX_TEMPLATE_BYTES * 8 or total / compressed > 150:
                raise TemplateFillError("template_zip_invalid")
            names = {item.filename for item in infos}
            if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
                raise TemplateFillError("template_pptx_invalid")
            if any(".." in Path(item.filename).parts or item.filename.startswith("/") for item in infos):
                raise TemplateFillError("template_zip_invalid")
            if any(name.lower().endswith("vbaproject.bin") for name in names):
                raise TemplateFillError("template_macro_forbidden")
    except zipfile.BadZipFile as exc:
        raise TemplateFillError("template_pptx_invalid") from exc


class TemplateFillStore:
    """Owner-scoped template records; the apply operation is guarded by confirmation."""

    @staticmethod
    def require_confirmed(plan: dict) -> None:
        if plan.get("status") != "confirmed":
            raise TemplateFillPlanNotConfirmed("template_fill_plan_not_confirmed")

    @staticmethod
    def _source(db: Session, source_file_id: int, user_id: int) -> File:
        source = db.query(File).filter(
            File.id == source_file_id,
            or_(File.owner_user_id == user_id, File.user_id == user_id),
        ).first()
        if source is None:
            raise TemplateFillError("template_file_not_found")
        path = Path(source.real_path or source.filepath)
        _safe_pptx(path)
        return source

    @staticmethod
    def _snapshot(record: PPTTemplate) -> dict[str, Any]:
        return {
            "template_id": record.template_id, "owner_user_id": record.owner_user_id,
            "source_file_id": record.source_file_id, "title": record.title,
            "status": record.status, "sha256": record.sha256,
            "slide_count": record.slide_count, "canvas_width": record.canvas_width,
            "canvas_height": record.canvas_height, "analysis": _loads(record.analysis_json, {}),
            "preview_manifest": _loads(record.preview_manifest_json, {}),
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    def register_template(self, db: Session, *, source_file_id: int, user_id: int, title: str = "") -> dict[str, Any]:
        source = self._source(db, source_file_id, user_id)
        path = Path(source.real_path or source.filepath)
        digest = source.sha256 or _sha256(path)
        existing = db.query(PPTTemplate).filter(
            PPTTemplate.owner_user_id == user_id, PPTTemplate.source_file_id == source.id,
        ).first()
        if existing is None:
            existing = PPTTemplate(
                template_id="ptpl_" + uuid.uuid4().hex, owner_user_id=user_id,
                source_file_id=source.id, title=(title.strip() or source.filename)[:256],
                status="uploaded", sha256=digest,
            )
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return self._snapshot(existing)

    def analyze_template(self, db: Session, *, template_id: str, user_id: int) -> dict[str, Any]:
        record = db.query(PPTTemplate).filter(
            PPTTemplate.template_id == template_id, PPTTemplate.owner_user_id == user_id,
        ).first()
        if record is None:
            raise TemplateFillError("template_not_found")
        source = self._source(db, record.source_file_id, user_id)
        source_path = Path(source.real_path or source.filepath)
        if record.status == "analyzed" and record.sha256 == _sha256(source_path) and _loads(record.preview_manifest_json, {}).get("slides"):
            return self._snapshot(record)
        library = _with_slot_confidence(_enrich_template_library(source_path, _analyze_pptx(source_path)))
        slide_count = int(library.get("slide_count") or len(library.get("slides") or []))
        if slide_count < 1 or slide_count > _MAX_TEMPLATE_SLIDES:
            raise TemplateFillError("template_slide_count_invalid")
        canvas = library.get("canvas_px") or {}
        preview_root = ArtifactService().projects_root / "template_previews" / record.template_id
        preview_paths = _render_template_previews(source_path, preview_root, slide_count)
        preview_slides = []
        for slide, preview_path in zip(library.get("slides", []), preview_paths):
            preview = File(user_id=user_id, owner_user_id=user_id, filename=preview_path.name, filepath=str(preview_path), real_path=str(preview_path), filesize=preview_path.stat().st_size, size=preview_path.stat().st_size, filetype=".png", mime_type="image/png", project_id=record.template_id, sha256=_sha256(preview_path))
            db.add(preview)
            db.flush()
            preview_slides.append({"slide_index": slide.get("slide_index"), "preview_file_id": preview.id, "download_url": f"/api/v1/files/{preview.id}/download"})
        record.status = "analyzed"
        record.slide_count = slide_count
        record.canvas_width = int(canvas.get("width") or 0)
        record.canvas_height = int(canvas.get("height") or 0)
        record.analysis_json = _dumps(library)
        record.preview_manifest_json = _dumps({"template_id": record.template_id, "slides": preview_slides})
        db.commit()
        db.refresh(record)
        return self._snapshot(record)

    def get_template(self, db: Session, *, template_id: str, user_id: int) -> dict[str, Any] | None:
        record = db.query(PPTTemplate).filter(
            PPTTemplate.template_id == template_id, PPTTemplate.owner_user_id == user_id,
        ).first()
        return self._snapshot(record) if record else None

    @staticmethod
    def _plan_snapshot(record: PPTTemplateFillPlan) -> dict[str, Any]:
        plan = _loads(record.plan_json, {})
        return {"plan_id": record.plan_id, "template_id": record.template_id, "owner_user_id": record.owner_user_id, "source_file_ids": _loads(record.source_file_ids_json, []), "status": record.status, "revision": record.revision, "plan": plan}

    @staticmethod
    def _new_public_plan(template: dict[str, Any], template_id: str, source_file_ids: list[int], selected_slides: list[int]) -> dict[str, Any]:
        """Expose stable slide/shape selectors, never mutable analyzer array positions."""
        requested = list(dict.fromkeys(selected_slides))
        slides_by_index = {int(item.get("slide_index", 0)): item for item in template["analysis"].get("slides", [])}
        if any(index not in slides_by_index for index in requested):
            raise TemplateFillError("template_selected_slide_not_found")
        public_slides = []
        for output_order, index in enumerate(requested, start=1):
            slide = slides_by_index[index]
            values: list[dict[str, Any]] = []
            for slot in slide.get("slots", []):
                if not slot.get("shape_id"):
                    continue
                values.append({
                    "shape_id": str(slot["shape_id"]), "slot_type": "text", "action": "keep",
                    "value": str(slot.get("text") or ""), "source_refs": [],
                })
            for image in slide.get("images", []):
                if image.get("shape_id"):
                    values.append({"shape_id": str(image["shape_id"]), "slot_type": "image", "action": "keep", "value": "", "source_refs": []})
            for table in slide.get("tables", []):
                values.append({"shape_id": str(table.get("shape_id") or table.get("table_id")), "slot_type": "table", "action": "keep", "value": table.get("rows", []), "source_refs": []})
            for chart in slide.get("charts", []):
                values.append({"shape_id": str(chart.get("shape_id") or chart.get("chart_id")), "slot_type": "chart", "action": "keep", "value": {"categories": chart.get("categories", []), "series": chart.get("series", [])}, "source_refs": []})
            public_slides.append({
                "template_slide_id": str(slide.get("slide_id") or f"slide:{index}"),
                "template_slide_index": index, "output_order": output_order, "slot_values": values,
            })
        return {"schema": "ai_box_template_fill.v1", "template_id": template_id, "source_file_ids": source_file_ids, "selected_slides": public_slides, "status": "draft", "revision": 1}

    @staticmethod
    def _to_upstream_plan(plan: dict[str, Any]) -> dict[str, Any]:
        """Translate the product-safe plan to the vendored upstream OOXML plan."""
        converted_slides: list[dict[str, Any]] = []
        selected = sorted(plan.get("selected_slides", []), key=lambda item: int(item.get("output_order", 0)))
        for slide in selected:
            replacements: list[dict[str, Any]] = []
            table_edits: list[dict[str, Any]] = []
            chart_edits: list[dict[str, Any]] = []
            for value in slide.get("slot_values", []):
                action = value.get("action")
                if action == "keep":
                    continue
                kind = value.get("slot_type")
                selector = {"shape_id": str(value.get("shape_id") or "")}
                if not selector["shape_id"]:
                    raise TemplateFillError("template_fill_slot_selector_invalid")
                if kind == "text":
                    replacements.append({**selector, "text": "" if action == "clear" else str(value.get("value") or "")})
                elif kind == "table":
                    rows_or_cells = value.get("value")
                    if not isinstance(rows_or_cells, list):
                        raise TemplateFillError("template_fill_table_value_invalid")
                    # Analyzer output is row/cells metadata; the upstream writer
                    # expects a flat list of cell edits. Preserve only writable
                    # cells and keep the original grid/formatting untouched.
                    cells = [
                        cell
                        for row in rows_or_cells
                        for cell in (
                            row.get("cells", []) if isinstance(row, dict) and isinstance(row.get("cells"), list)
                            else row if isinstance(row, list)
                            else [row]
                        )
                        if isinstance(cell, dict)
                    ]
                    if not cells:
                        raise TemplateFillError("template_fill_table_value_invalid")
                    if action == "clear":
                        cells = [{**cell, "text": ""} for cell in cells]
                    table_edits.append({**selector, "cells": cells})
                elif kind == "chart":
                    payload = value.get("value")
                    if not isinstance(payload, dict):
                        raise TemplateFillError("template_fill_chart_value_invalid")
                    categories = payload.get("categories", [])
                    series = payload.get("series", [])
                    if not isinstance(categories, list) or not isinstance(series, list):
                        raise TemplateFillError("template_fill_chart_value_invalid")
                    if action == "clear":
                        categories = ["" for _ in categories]
                        series = [{**item, "name": "", "values": [0 for _ in item.get("values", [])]} for item in series if isinstance(item, dict)]
                    chart_edits.append({**selector, "categories": categories, "series": series})
                elif kind == "image":
                    # Images are applied after upstream cloning to preserve the original p:pic frame/effects.
                    continue
                else:
                    raise TemplateFillError("template_fill_slot_type_invalid")
            converted_slides.append({"source_slide": int(slide["template_slide_index"]), "replacements": replacements, "table_edits": table_edits, "chart_edits": chart_edits})
        if not converted_slides:
            raise TemplateFillError("template_fill_selected_slides_empty")
        return {"schema": "template_fill_pptx_plan.v1", "status": "confirmed", "slides": converted_slides}

    def create_fill_plan(self, db: Session, *, template_id: str, user_id: int, selected_slides: list[int], source_file_ids: list[int]) -> dict[str, Any]:
        template = self.get_template(db, template_id=template_id, user_id=user_id)
        if template is None or template.get("status") != "analyzed":
            raise TemplateFillError("template_not_analyzed")
        if not selected_slides or any(not isinstance(item, int) or item < 1 for item in selected_slides):
            raise TemplateFillError("template_selected_slides_invalid")
        plan = self._new_public_plan(template, template_id, source_file_ids, selected_slides)
        record = PPTTemplateFillPlan(plan_id="fillplan_" + uuid.uuid4().hex, template_id=template_id, owner_user_id=user_id, source_file_ids_json=_dumps(source_file_ids), plan_json=_dumps(plan), status="draft", revision=1)
        db.add(record); db.commit(); db.refresh(record)
        return self._plan_snapshot(record)

    def get_fill_plan(self, db: Session, *, plan_id: str, user_id: int) -> dict[str, Any] | None:
        record = db.query(PPTTemplateFillPlan).filter(PPTTemplateFillPlan.plan_id == plan_id, PPTTemplateFillPlan.owner_user_id == user_id).first()
        return self._plan_snapshot(record) if record else None

    def update_fill_plan(self, db: Session, *, plan_id: str, user_id: int, expected_revision: int, plan: dict[str, Any]) -> dict[str, Any] | None:
        record = db.query(PPTTemplateFillPlan).filter(PPTTemplateFillPlan.plan_id == plan_id, PPTTemplateFillPlan.owner_user_id == user_id).first()
        if record is None:
            return None
        if record.status != "draft":
            raise TemplateFillPlanImmutable("template_fill_plan_confirmed")
        if expected_revision != record.revision:
            raise TemplateFillPlanConflict("template_fill_plan_revision_conflict")
        if plan.get("status", "draft") != "draft" or not isinstance(plan.get("selected_slides"), list):
            raise TemplateFillError("template_fill_plan_invalid")
        for item in plan["selected_slides"]:
            if not isinstance(item, dict) or not isinstance(item.get("template_slide_index"), int) or not isinstance(item.get("slot_values"), list):
                raise TemplateFillError("template_fill_plan_invalid")
            for slot in item["slot_values"]:
                if not isinstance(slot, dict) or slot.get("slot_type") not in {"text", "image", "table", "chart"} or slot.get("action") not in {"keep", "replace", "clear"}:
                    raise TemplateFillError("template_fill_plan_invalid")
        plan["template_id"] = record.template_id
        plan["source_file_ids"] = _loads(record.source_file_ids_json, [])
        plan["status"] = "draft"
        plan["revision"] = record.revision + 1
        record.plan_json = _dumps(plan)
        record.revision += 1
        db.commit(); db.refresh(record)
        return self._plan_snapshot(record)

    @staticmethod
    def _task_snapshot(record: PPTTemplateFillTask) -> dict[str, Any]:
        return {
            "task_id": record.task_id, "template_id": record.template_id, "plan_id": record.plan_id,
            "route_type": record.route_type, "source_file_id": record.source_file_id,
            "output_file_id": record.output_file_id, "status": record.status,
            "validation": _loads(record.validation_json, {}), "artifact_manifest": _loads(record.artifact_manifest_json, {}),
            "error": _loads(record.error_json, {}),
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        }

    @staticmethod
    def _set_task_status(db: Session, task: PPTTemplateFillTask, status: str) -> None:
        task.status = status
        db.commit()

    @staticmethod
    def _validate_output(path: Path, *, expected_slide_count: int, source_sha256: str) -> dict[str, Any]:
        """Validate the generated package without ever modifying its OOXML.

        This is deliberately stricter than a ZIP smoke test: every XML and
        relationship part must parse, each internal target must exist, and the
        slide -> layout -> master chain must remain usable by PowerPoint.
        """
        _safe_pptx(path)
        output_sha256 = _sha256(path)
        if output_sha256 == source_sha256:
            raise TemplateFillError("template_fill_output_equals_source")

        rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"

        def relationship_source(rels_name: str) -> str:
            if rels_name == "_rels/.rels":
                return ""
            directory, filename = posixpath.split(rels_name)
            if not directory.endswith("/_rels") or not filename.endswith(".rels"):
                raise TemplateFillError("template_fill_relationship_part_invalid")
            return posixpath.join(directory[:-6], filename[:-5]).lstrip("/")

        def relationship_target(source_part: str, target: str) -> str:
            # OPC relationship targets are package-relative to their source part.
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target)).lstrip("/")
            if not resolved or resolved.startswith("../") or resolved == "..":
                raise TemplateFillError("template_fill_relationship_target_invalid")
            return resolved

        try:
            with zipfile.ZipFile(path) as archive:
                names = {entry.filename for entry in archive.infolist() if not entry.is_dir()}
                xml_parts = [name for name in names if name.endswith(".xml") or name.endswith(".rels") or name == "[Content_Types].xml"]
                for xml_part in xml_parts:
                    try:
                        ET.fromstring(archive.read(xml_part))
                    except ET.ParseError as exc:
                        raise TemplateFillError("template_fill_xml_invalid") from exc

                relation_count = 0
                external_relationship_count = 0
                for rel_name in sorted(name for name in names if name.endswith(".rels")):
                    root = ET.fromstring(archive.read(rel_name))
                    source_part = relationship_source(rel_name)
                    for relation in root.findall(f"{{{rel_ns}}}Relationship"):
                        relation_count += 1
                        target = relation.attrib.get("Target", "")
                        if not target:
                            raise TemplateFillError("template_fill_relationship_target_missing")
                        if relation.attrib.get("TargetMode") == "External":
                            external_relationship_count += 1
                            raise TemplateFillError("template_fill_external_relationship_forbidden")
                        if relationship_target(source_part, target) not in names:
                            raise TemplateFillError("template_fill_relationship_target_missing")

                refs = _parse_slide_refs(archive)
                if len(refs) != expected_slide_count:
                    raise TemplateFillError("template_fill_output_slide_count_invalid")
                master_parts: set[str] = set()
                layout_parts: set[str] = set()
                for ref in refs:
                    if ref.part_name not in names or ref.rels_name not in names:
                        raise TemplateFillError("template_fill_slide_relationship_missing")
                    slide_rels = _slide_relationships(archive, ref.rels_name)
                    layout = next((item for item in slide_rels.values() if item.get("type", "").endswith("/slideLayout")), None)
                    if not layout:
                        raise TemplateFillError("template_fill_slide_layout_missing")
                    layout_part = _normalize_part(layout["target"], ref.part_name)
                    if layout_part not in names:
                        raise TemplateFillError("template_fill_slide_layout_missing")
                    layout_parts.add(layout_part)
                    layout_rels_name = f"{layout_part.rsplit('/', 1)[0]}/_rels/{layout_part.rsplit('/', 1)[1]}.rels"
                    if layout_rels_name not in names:
                        raise TemplateFillError("template_fill_layout_master_missing")
                    layout_rels = _slide_relationships(archive, layout_rels_name)
                    master = next((item for item in layout_rels.values() if item.get("type", "").endswith("/slideMaster")), None)
                    if not master:
                        raise TemplateFillError("template_fill_layout_master_missing")
                    master_part = _normalize_part(master["target"], layout_part)
                    if master_part not in names:
                        raise TemplateFillError("template_fill_layout_master_missing")
                    master_parts.add(master_part)

                media_count = sum(name.startswith("ppt/media/") for name in names)
                chart_count = sum(name.startswith("ppt/charts/chart") and name.endswith(".xml") for name in names)
                embedding_count = sum(name.startswith("ppt/embeddings/") for name in names)
                table_count = sum(archive.read(ref.part_name).count(b"<a:tbl") for ref in refs)
        except zipfile.BadZipFile as exc:
            raise TemplateFillError("template_fill_output_invalid") from exc

        # LibreOffice is used only as a non-mutating openability/render check on
        # the newly generated file. The original template is never opened for save.
        office_render_valid = False
        with tempfile.TemporaryDirectory(prefix="template-fill-verify-") as verify_dir:
            result = subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf", "--outdir", verify_dir, str(path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90, check=False,
            )
            expected_pdf = Path(verify_dir) / f"{path.stem}.pdf"
            office_render_valid = result.returncode == 0 and expected_pdf.is_file() and expected_pdf.stat().st_size > 0
        if not office_render_valid:
            raise TemplateFillError("template_fill_output_openability_invalid")

        return {
            "zip_valid": True, "xml_valid": True, "relationship_valid": True,
            "office_render_valid": office_render_valid, "slide_count": expected_slide_count,
            "master_count": len(master_parts), "layout_count": len(layout_parts),
            "chart_count": chart_count, "table_count": table_count, "media_count": media_count,
            "embedding_count": embedding_count, "relationship_count": relation_count,
            "external_relationship_count": external_relationship_count,
            "source_sha256": source_sha256, "output_sha256": output_sha256,
        }

    @staticmethod
    def _image_requests(db: Session, *, user_id: int, plan: dict[str, Any]) -> list[dict[str, Any]]:
        requests: list[dict[str, Any]] = []
        selected = sorted(plan.get("selected_slides", []), key=lambda item: int(item.get("output_order", 0)))
        for position, slide in enumerate(selected, start=1):
            for slot in slide.get("slot_values", []):
                if slot.get("slot_type") != "image" or slot.get("action") != "replace":
                    continue
                refs = slot.get("source_refs")
                if not isinstance(refs, list) or len(refs) != 1 or not isinstance(refs[0], dict):
                    raise TemplateFillError("template_fill_image_source_required")
                file_id = refs[0].get("file_id")
                if not isinstance(file_id, int):
                    raise TemplateFillError("template_fill_image_source_required")
                image = db.query(File).filter(File.id == file_id, or_(File.owner_user_id == user_id, File.user_id == user_id)).first()
                if image is None:
                    raise TemplateFillError("template_fill_image_not_authorized")
                image_path = Path(image.real_path or image.filepath)
                if image_path.suffix.lower() not in {".png", ".jpg", ".jpeg"} or not image_path.is_file():
                    raise TemplateFillError("template_fill_image_invalid")
                requests.append({"output_slide_position": position, "shape_id": str(slot.get("shape_id") or ""), "image_path": image_path})
        return requests

    def apply_fill_plan(self, db: Session, *, plan_id: str, user_id: int, expected_revision: int) -> dict[str, Any] | None:
        record = db.query(PPTTemplateFillPlan).filter(PPTTemplateFillPlan.plan_id == plan_id, PPTTemplateFillPlan.owner_user_id == user_id).first()
        if record is None:
            return None
        if record.status != "confirmed":
            raise TemplateFillPlanNotConfirmed("template_fill_plan_not_confirmed")
        if expected_revision != record.revision:
            raise TemplateFillPlanConflict("template_fill_plan_revision_conflict")
        template = db.query(PPTTemplate).filter(PPTTemplate.template_id == record.template_id, PPTTemplate.owner_user_id == user_id).first()
        if template is None:
            raise TemplateFillError("template_not_found")
        source = self._source(db, template.source_file_id, user_id)
        source_path = Path(source.real_path or source.filepath)
        source_sha256 = _sha256(source_path)
        if source_sha256 != template.sha256:
            raise TemplateFillError("template_source_sha_changed")
        source_file_ids = _loads(record.source_file_ids_json, [])
        for source_file_id in source_file_ids:
            item = db.query(File).filter(File.id == source_file_id, or_(File.owner_user_id == user_id, File.user_id == user_id)).first()
            if item is None:
                raise TemplateFillError("template_fill_source_not_authorized")
        plan = _loads(record.plan_json, {})
        task = PPTTemplateFillTask(task_id="filltask_" + uuid.uuid4().hex, template_id=template.template_id, plan_id=record.plan_id, user_id=user_id, route_type="template_fill", source_file_id=source.id, status="queued", options_json=_dumps({"fill_plan_revision": record.revision}))
        db.add(task); db.commit(); db.refresh(task)
        stage = "queued"
        try:
            stage = "validating"; self._set_task_status(db, task, stage)
            upstream_plan = self._to_upstream_plan(plan)
            report = _check_plan(_loads(template.analysis_json, {}), upstream_plan)
            if int((report.get("summary") or {}).get("error") or 0) > 0:
                raise TemplateFillError("template_fill_plan_validation_failed")
            root = ArtifactService().projects_root / "template_fill" / task.task_id
            output_path = root / "filled.pptx"
            stage = "cloning"; self._set_task_status(db, task, stage)
            stage = "applying_text"; self._set_task_status(db, task, stage)
            stage = "applying_native_data"; self._set_task_status(db, task, stage)
            _apply_plan(source_path, upstream_plan, output_path, transition="keep")
            stage = "applying_media"; self._set_task_status(db, task, stage)
            _replace_output_images(output_path, self._image_requests(db, user_id=user_id, plan=plan))
            stage = "validating_output"; self._set_task_status(db, task, stage)
            validation = self._validate_output(output_path, expected_slide_count=len(upstream_plan["slides"]), source_sha256=source_sha256)
            stage = "registering_file"; self._set_task_status(db, task, stage)
            artifact = ArtifactService().register_pptx(db, owner_user_id=user_id, project_id=template.template_id, task_id=task.task_id, real_path=output_path)
            task.output_file_id = artifact.id
            task.validation_json = _dumps(validation)
            task.artifact_manifest_json = _dumps({"output_file_id": artifact.id, "output_sha256": artifact.sha256, "output_size": artifact.size or artifact.filesize, "source_template_sha256": source_sha256, "fill_plan_revision": record.revision, "output_path_type": "registered_artifact"})
            task.status = "completed"
            task.completed_at = datetime.utcnow()
            db.commit(); db.refresh(task)
        except Exception as exc:
            task.status = "failed"
            task.completed_at = datetime.utcnow()
            task.error_json = _dumps({"code": str(exc), "stage": stage})
            db.commit(); db.refresh(task)
        return self._task_snapshot(task)

    def get_fill_task(self, db: Session, *, task_id: str, user_id: int) -> dict[str, Any] | None:
        task = db.query(PPTTemplateFillTask).filter(PPTTemplateFillTask.task_id == task_id, PPTTemplateFillTask.user_id == user_id).first()
        return self._task_snapshot(task) if task else None

    def confirm_fill_plan(self, db: Session, *, plan_id: str, user_id: int) -> dict[str, Any] | None:
        record = db.query(PPTTemplateFillPlan).filter(PPTTemplateFillPlan.plan_id == plan_id, PPTTemplateFillPlan.owner_user_id == user_id).first()
        if record is None:
            return None
        plan = _loads(record.plan_json, {})
        plan["status"] = "confirmed"
        record.plan_json = _dumps(plan)
        record.status = "confirmed"
        db.commit(); db.refresh(record)
        return self._plan_snapshot(record)

    def get_template_slides(self, db: Session, *, template_id: str, user_id: int) -> list[dict[str, Any]] | None:
        template = self.get_template(db, template_id=template_id, user_id=user_id)
        if template is None:
            return None
        previews = {item.get("slide_index"): item for item in (template.get("preview_manifest") or {}).get("slides", [])}
        result = []
        for slide in (template.get("analysis") or {}).get("slides", []):
            item = {key: value for key, value in slide.items() if key not in {"source_pptx"}}
            item.update(previews.get(item.get("slide_index"), {}))
            result.append(item)
        return result

    def list_templates(self, db: Session, *, user_id: int) -> list[dict[str, Any]]:
        rows = db.query(PPTTemplate).filter(PPTTemplate.owner_user_id == user_id).order_by(PPTTemplate.updated_at.desc()).all()
        return [self._snapshot(row) for row in rows]
