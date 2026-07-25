"""Low-level OOXML-safe analysis and slide transition patching for native PPT enhancement."""
from __future__ import annotations

import hashlib
import posixpath
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"p": P_NS, "r": R_NS, "rel": REL_NS}
ET.register_namespace("p", P_NS)
ET.register_namespace("r", R_NS)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _resolve_part(base_part: str, target: str) -> str:
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))


def _presentation_slide_parts(archive: zipfile.ZipFile) -> list[str]:
    root = ET.fromstring(archive.read("ppt/presentation.xml"))
    rels = ET.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
    targets = {item.attrib.get("Id"): item.attrib.get("Target", "") for item in rels}
    parts: list[str] = []
    for slide_id in root.findall(".//p:sldId", NS):
        target = targets.get(slide_id.attrib.get(f"{{{R_NS}}}id"))
        if target:
            parts.append(_resolve_part("ppt/presentation.xml", target))
    return parts


def _transition(root: ET.Element) -> dict[str, Any] | None:
    node = root.find("p:transition", NS)
    if node is None:
        return None
    children = list(node)
    return {
        "type": _local_name(children[0].tag) if children else "none",
        "duration": node.attrib.get("spd"),
        "advance_on_click": node.attrib.get("advClick", "1") != "0",
        "auto_advance_ms": int(node.attrib["advTm"]) if node.attrib.get("advTm", "").isdigit() else None,
    }


def analyze_native_pptx(source: Path) -> dict[str, Any]:
    """Inspect a PPTX package without accessing external targets or changing any part."""
    with zipfile.ZipFile(source) as archive:
        names = set(archive.namelist())
        slide_parts = _presentation_slide_parts(archive)
        has_notes = any(name.startswith("ppt/notesSlides/") and name.endswith(".xml") for name in names)
        slides: list[dict[str, Any]] = []
        for index, part in enumerate(slide_parts, start=1):
            root = ET.fromstring(archive.read(part))
            slides.append({
                "slide_id": f"slide-{index}",
                "index": index,
                "transition": _transition(root),
                "has_timing": root.find("p:timing", NS) is not None,
                "has_notes_slide": has_notes,
            })
        external: list[dict[str, str]] = []
        for name in sorted(item for item in names if item.endswith(".rels")):
            root = ET.fromstring(archive.read(name))
            for item in root.findall("rel:Relationship", NS):
                if item.attrib.get("TargetMode") == "External":
                    external.append({"part": name, "id": item.attrib.get("Id", ""), "type": item.attrib.get("Type", ""), "target": item.attrib.get("Target", "")})
        return {
            "source_sha256": _sha256(source),
            "slide_count": len(slide_parts),
            "slides": slides,
            "notes_slide_count": sum(1 for item in names if item.startswith("ppt/notesSlides/") and item.endswith(".xml")),
            "external_relationships": external,
        }


def _selected(index: int, options: dict[str, Any], has_transition: bool) -> bool:
    scope = options.get("application_scope", "all")
    if scope == "missing_only":
        return not has_transition
    if scope == "selected":
        return index in {int(item) for item in options.get("slide_ids", [])}
    return scope == "all"


def _transition_speed(duration_ms: object) -> str:
    value = int(duration_ms) if isinstance(duration_ms, (int, float)) else 500
    return "fast" if value <= 350 else "slow" if value >= 800 else "med"


def _new_transition(kind: str, options: dict[str, Any]) -> ET.Element:
    attributes = {"spd": _transition_speed(options.get("duration_ms"))}
    if options.get("advance_on_click") is False:
        attributes["advClick"] = "0"
    if isinstance(options.get("auto_advance_ms"), int) and options["auto_advance_ms"] > 0:
        attributes["advTm"] = str(options["auto_advance_ms"])
    node = ET.Element(f"{{{P_NS}}}transition", attributes)
    ET.SubElement(node, f"{{{P_NS}}}{kind}")
    return node



A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS["a"] = A_NS
ET.register_namespace("a", A_NS)


def _field_selected(index: int, config: object) -> bool:
    if not isinstance(config, dict):
        return False
    if config.get("application_scope", "all") == "selected":
        return index in {int(item) for item in config.get("slide_ids", [])}
    return True


def _replace_native_text(root: ET.Element, *, name: str, text: str | None, config: dict[str, Any] | None = None) -> bool:
    tree = root.find(".//p:spTree", NS)
    if tree is None:
        return False
    existing = []
    max_id = 1
    for node in tree.findall("p:sp", NS):
        c_nv_pr = node.find(".//p:cNvPr", NS)
        if c_nv_pr is not None:
            try:
                max_id = max(max_id, int(c_nv_pr.attrib.get("id", "0")))
            except ValueError:
                pass
            if c_nv_pr.attrib.get("name") == name:
                existing.append(node)
    for node in existing:
        tree.remove(node)
    if text is None:
        return bool(existing)
    config = config or {}
    position = str(config.get("position", "bottom_right"))
    geometry = {
        "bottom_left": ("914400", "3048000"),
        "bottom_center": ("3429000", "4572000"),
        "bottom_right": ("7315200", "2743200"),
    }.get(position, ("7315200", "2743200"))
    size = int(config.get("font_size_pt", 9)) * 100
    color = str(config.get("color", "64748B")).upper()
    shape = ET.SubElement(tree, f"{{{P_NS}}}sp")
    nv = ET.SubElement(shape, f"{{{P_NS}}}nvSpPr")
    ET.SubElement(nv, f"{{{P_NS}}}cNvPr", {"id": str(max_id + 1), "name": name})
    ET.SubElement(nv, f"{{{P_NS}}}cNvSpPr", {"txBox": "1"})
    ET.SubElement(nv, f"{{{P_NS}}}nvPr")
    sp_pr = ET.SubElement(shape, f"{{{P_NS}}}spPr")
    xfrm = ET.SubElement(sp_pr, f"{{{A_NS}}}xfrm")
    ET.SubElement(xfrm, f"{{{A_NS}}}off", {"x": geometry[0], "y": "6400800"})
    ET.SubElement(xfrm, f"{{{A_NS}}}ext", {"cx": geometry[1], "cy": "228600"})
    geometry_node = ET.SubElement(sp_pr, f"{{{A_NS}}}prstGeom", {"prst": "rect"})
    ET.SubElement(geometry_node, f"{{{A_NS}}}avLst")
    ET.SubElement(sp_pr, f"{{{A_NS}}}noFill")
    body = ET.SubElement(shape, f"{{{P_NS}}}txBody")
    ET.SubElement(body, f"{{{A_NS}}}bodyPr")
    ET.SubElement(body, f"{{{A_NS}}}lstStyle")
    paragraph = ET.SubElement(body, f"{{{A_NS}}}p")
    run = ET.SubElement(paragraph, f"{{{A_NS}}}r")
    run_props = ET.SubElement(run, f"{{{A_NS}}}rPr", {"lang": "zh-CN", "sz": str(size)})
    fill = ET.SubElement(run_props, f"{{{A_NS}}}solidFill")
    ET.SubElement(fill, f"{{{A_NS}}}srgbClr", {"val": color})
    ET.SubElement(run, f"{{{A_NS}}}t").text = text
    return True


def _footer_value(options: dict[str, Any], key: str, default: str | None, index: int) -> str | None:
    config = options.get(key)
    if not isinstance(config, dict) or not config.get("enabled"):
        return None
    value = config.get("text", default)
    return str(value).replace("{page}", str(index)) if value is not None else None


CORE_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"
CP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
DCTERMS_NS = "http://purl.org/dc/terms/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
ET.register_namespace("cp", CORE_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("dcterms", DCTERMS_NS)
ET.register_namespace("xsi", XSI_NS)
ET.register_namespace("", CP_NS)


def _set_xml_text(root: ET.Element, tag: str, value: object) -> None:
    if value is None:
        return
    node = root.find(tag)
    if node is None:
        node = ET.SubElement(root, tag)
    node.text = str(value)


def _patch_document_properties(original: zipfile.ZipFile, patched: dict[str, bytes], properties: object) -> None:
    if not isinstance(properties, dict):
        return
    names = {entry.filename for entry in original.infolist()}
    core_name = "docProps/core.xml"
    core = ET.fromstring(patched.get(core_name, original.read(core_name))) if core_name in names or core_name in patched else ET.Element(f"{{{CORE_NS}}}coreProperties")
    for key, tag in (("title", f"{{{DC_NS}}}title"), ("subject", f"{{{DC_NS}}}subject"), ("author", f"{{{DC_NS}}}creator"), ("keywords", f"{{{CP_NS}}}keywords"), ("comments", f"{{{DC_NS}}}description")):
        _set_xml_text(core, tag, properties.get(key))
    patched[core_name] = ET.tostring(core, encoding="utf-8", xml_declaration=True)
    app_name = "docProps/app.xml"
    if "company" in properties:
        app = ET.fromstring(patched.get(app_name, original.read(app_name))) if app_name in names or app_name in patched else ET.Element(f"{{{CP_NS}}}Properties")
        _set_xml_text(app, f"{{{CP_NS}}}Company", properties.get("company"))
        patched[app_name] = ET.tostring(app, encoding="utf-8", xml_declaration=True)
    required_parts = (("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"), ("/docProps/app.xml", "application/vnd.openxmlformats-officedocument.extended-properties+xml"))
    ct_name = "[Content_Types].xml"
    content_types = ET.fromstring(patched.get(ct_name, original.read(ct_name)))
    existing = {node.attrib.get("PartName") for node in content_types}
    if any(part not in existing for part, _ in required_parts):
        for part, content_type in required_parts:
            if part not in existing:
                ET.SubElement(content_types, f"{{{CT_NS}}}Override", {"PartName": part, "ContentType": content_type})
        patched[ct_name] = ET.tostring(content_types, encoding="utf-8", xml_declaration=True)
    rel_name = "_rels/.rels"
    rel_root = ET.fromstring(patched.get(rel_name, original.read(rel_name))) if rel_name in names or rel_name in patched else ET.Element(f"{{{REL_NS}}}Relationships")
    used = {node.attrib.get("Id") for node in rel_root}
    relation_specs = (("docProps/core.xml", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"), ("docProps/app.xml", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties"))
    if any(not any(node.attrib.get("Type") == relationship_type for node in rel_root) for _, relationship_type in relation_specs):
        for target, relationship_type in relation_specs:
            if not any(node.attrib.get("Type") == relationship_type for node in rel_root):
                number = 1
                while f"rId{number}" in used:
                    number += 1
                relation_id = f"rId{number}"
                used.add(relation_id)
                ET.SubElement(rel_root, f"{{{REL_NS}}}Relationship", {"Id": relation_id, "Type": relationship_type, "Target": target})
        patched[rel_name] = ET.tostring(rel_root, encoding="utf-8", xml_declaration=True)

def validate_native_pptx(path: Path) -> dict[str, Any]:
    """Verify package integrity and that every XML/rels part can be parsed."""
    try:
        with zipfile.ZipFile(path) as archive:
            corrupt_part = archive.testzip()
            if corrupt_part:
                raise ValueError(f"native_enhance_zip_corrupt:{corrupt_part}")
            names = archive.namelist()
            if "ppt/presentation.xml" not in names:
                raise ValueError("native_enhance_presentation_missing")
            xml_parts = 0
            for name in names:
                if name.endswith(".xml") or name.endswith(".rels") or name == "[Content_Types].xml":
                    ET.fromstring(archive.read(name))
                    xml_parts += 1
            return {"zip_valid": True, "xml_part_count": xml_parts, "slide_count": len(_presentation_slide_parts(archive))}
    except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError) as exc:
        raise ValueError("native_enhance_output_structure_invalid") from exc


def apply_native_enhancement(source: Path, output: Path, options: dict[str, Any]) -> dict[str, Any]:
    """Create a new PPTX with explicitly selected transitions and AIBox footer fields changed."""
    transition_type = str(options.get("transition_type", "keep"))
    if transition_type not in {"keep", "none", "fade", "push", "wipe", "split", "cover"}:
        raise ValueError("native_enhance_transition_invalid")
    changed = 0
    with zipfile.ZipFile(source) as original:
        slide_parts = _presentation_slide_parts(original)
        patched: dict[str, bytes] = {}
        for index, part in enumerate(slide_parts, start=1):
            root = ET.fromstring(original.read(part))
            dirty = False
            prior = root.find("p:transition", NS)
            if transition_type != "keep" and _selected(index, options, prior is not None):
                if prior is not None:
                    root.remove(prior)
                if transition_type != "none":
                    replacement = _new_transition(transition_type, options)
                    timing = root.find("p:timing", NS)
                    root.insert(list(root).index(timing) if timing is not None else len(root), replacement)
                dirty = True
            fields = (("AIBox_PageNumber", "page_number", str(index)),
                      ("AIBox_Footer", "footer", None),
                      ("AIBox_Date", "date", None))
            for name, key, default in fields:
                config = options.get(key)
                if isinstance(config, dict) and _field_selected(index, config):
                    value = _footer_value(options, key, default, index)
                    dirty = _replace_native_text(root, name=name, text=value, config=config) or dirty
            if dirty:
                patched[part] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                changed += 1
        _patch_document_properties(original, patched, options.get("document_properties"))
        if options.get("remove_external_relationships") is True:
            for entry in original.infolist():
                if not entry.filename.endswith(".rels"):
                    continue
                rel_root = ET.fromstring(original.read(entry.filename))
                removed_ids = [node.attrib.get("Id", "") for node in list(rel_root) if node.attrib.get("TargetMode") == "External"]
                if not removed_ids:
                    continue
                for node in list(rel_root):
                    if node.attrib.get("Id") in removed_ids:
                        rel_root.remove(node)
                patched[entry.filename] = ET.tostring(rel_root, encoding="utf-8", xml_declaration=True)
                directory, filename = posixpath.split(entry.filename)
                if directory.endswith("/_rels") and filename.endswith(".rels"):
                    source_part = posixpath.join(directory[:-6], filename[:-5])
                    if source_part in {item.filename for item in original.infolist()}:
                        source_root = ET.fromstring(patched.get(source_part, original.read(source_part)))
                        for node in source_root.iter():
                            for attr in (f"{{{R_NS}}}id", f"{{{R_NS}}}embed", f"{{{R_NS}}}link"):
                                if node.attrib.get(attr) in removed_ids:
                                    del node.attrib[attr]
                        patched[source_part] = ET.tostring(source_root, encoding="utf-8", xml_declaration=True)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as destination:
            original_names = set()
            for entry in original.infolist():
                original_names.add(entry.filename)
                destination.writestr(entry, patched.get(entry.filename, original.read(entry.filename)))
            for name, value in patched.items():
                if name not in original_names:
                    destination.writestr(name, value)
    return {"source_sha256": _sha256(source), "output_sha256": _sha256(output), "changed_slide_count": changed}
