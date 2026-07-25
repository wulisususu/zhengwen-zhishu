"""Deterministic, authorized image slot planning for incremental PPT projects."""
from __future__ import annotations
from typing import Any

def build_image_slots(assets: list[dict[str, Any]], *, page_count: int) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for index, asset in enumerate(assets[:max(0, page_count)], 1):
        asset_id, file_id, resource = asset.get("asset_id"), asset.get("file_id"), asset.get("resource")
        if not isinstance(asset_id, str) or not asset_id.startswith("pptimg_") or not isinstance(file_id, int) or file_id <= 0 or not isinstance(resource, str) or "/" in resource or "\\" in resource:
            continue
        width, height = max(1, int(asset.get("width") or 1)), max(1, int(asset.get("height") or 1))
        slots.append({"slide_index": index, "asset_id": asset_id, "file_id": file_id, "resource": resource, "purpose": "来源图片", "preferred_source": "provided", "aspect_ratio": "16:9" if width / height >= 1.3 else "4:3", "position": "right"})
    return slots


def inject_slot_image(svg_path: Any, slot: dict[str, Any]) -> bool:
    """Append a local-only image fallback when the SVG executor omitted an approved slot."""
    from pathlib import Path
    from xml.etree import ElementTree as ET
    resource = slot.get("resource")
    if not isinstance(resource, str) or not resource or "/" in resource or "\\" in resource:
        return False
    path = Path(svg_path)
    root = ET.parse(path).getroot()
    if any(node.tag.rsplit("}", 1)[-1] == "image" for node in root.iter()):
        return False
    namespace = "{http://www.w3.org/2000/svg}" if root.tag.startswith("{") else ""
    attrs = {"href": f"images/{resource}", "x": "730", "y": "150", "width": "470", "height": "360", "preserveAspectRatio": "xMidYMid meet"}
    root.append(ET.Element(f"{namespace}image", attrs))
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=False)
    return True
