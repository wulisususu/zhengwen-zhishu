"""SVG structured metadata injection for PPTX layout mapping."""
import re
import uuid
import xml.etree.ElementTree as ET

from app.PPT_master.structured_spec_lock import LAYOUT_DISPLAY_NAMES


def _layout_to_page_role(layout_id: str) -> str:
    """Map layout_id to data-pptx-page-role value."""
    mapping = {
        "layout-title": "cover",
        "layout-section": "section",
        "layout-title-content": "content",
        "layout-two-column": "content",
        "layout-image-text": "content",
        "layout-data": "content",
        "layout-blank": "content",
    }
    return mapping.get(layout_id, "content")


def _layout_display_name(layout_id: str) -> str:
    """Return the canonical display name for a layout key.

    Must match LAYOUT_DISPLAY_NAMES in structured_spec_lock.py exactly,
    since the converter cross-validates data-pptx-layout-name against the
    Layout name declared in spec_lock.md's pptx_layouts section.
    """
    return LAYOUT_DISPLAY_NAMES.get(layout_id, layout_id.replace("-", " ").title())


def _parse_length(value: str | None, default: float = 0.0) -> float:
    if not value:
        return default
    match = re.match(r"^-?\d+(\.\d+)?", value.strip())
    return float(match.group(0)) if match else default


def _is_full_canvas_rect(elem: ET.Element, canvas_w: float, canvas_h: float) -> bool:
    """Mirror the converter's _is_full_canvas_solid_rect eligibility check."""
    tag = elem.tag.rsplit("}", 1)[-1]
    if tag != "rect":
        return False
    if any(elem.get(attr) for attr in ("transform", "filter", "clip-path")):
        return False
    x = _parse_length(elem.get("x"), 0.0)
    y = _parse_length(elem.get("y"), 0.0)
    width = _parse_length(elem.get("width"), 0.0)
    height = _parse_length(elem.get("height"), 0.0)
    return x <= 0 and y <= 0 and width >= canvas_w and height >= canvas_h


def _ensure_background_id(svg_text: str) -> str:
    """Add a stable id to a direct full-canvas <rect> background, if present and unlabeled.

    Uses ElementTree only to *detect* the eligible direct-child rect (by its
    exact x/y/width/height values), then performs a targeted string-level
    insertion of the id="..." attribute on the first matching <rect> opening
    tag in the raw text. This avoids re-serializing the whole tree with
    ET.tostring(), which can corrupt unrelated tags/prefixes when other
    modules have called ET.register_namespace() with a conflicting
    empty-prefix mapping earlier in the process.
    """
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError:
        return svg_text

    view_box = root.get("viewBox", "")
    parts = view_box.split()
    if len(parts) == 4:
        canvas_w, canvas_h = float(parts[2]), float(parts[3])
    else:
        canvas_w = _parse_length(root.get("width"), 0.0)
        canvas_h = _parse_length(root.get("height"), 0.0)
    if canvas_w <= 0 or canvas_h <= 0:
        return svg_text

    target = None
    for child in list(root):
        if _is_full_canvas_rect(child, canvas_w, canvas_h) and not child.get("id"):
            target = child
            break
    if target is None:
        return svg_text

    x = target.get("x", "0")
    y = target.get("y", "0")
    width = target.get("width")
    height = target.get("height")
    if width is None or height is None:
        return svg_text

    # Build a regex that matches this specific direct-child <rect ...> opening
    # tag by its exact x/y/width/height attribute values (in any attribute
    # order), scoped to the first occurrence in document order.
    pattern = re.compile(
        r"<rect\b(?=[^>]*\bx=[\"']" + re.escape(x) + r"[\"'])"
        r"(?=[^>]*\by=[\"']" + re.escape(y) + r"[\"'])"
        r"(?=[^>]*\bwidth=[\"']" + re.escape(width) + r"[\"'])"
        r"(?=[^>]*\bheight=[\"']" + re.escape(height) + r"[\"'])"
        r"[^>]*/?>"
    )
    match = pattern.search(svg_text)
    if match is None:
        return svg_text
    tag_text = match.group(0)
    if "id=" in tag_text:
        return svg_text
    new_id = f"bg-{uuid.uuid4().hex[:8]}"
    updated_tag = re.sub(r"^<rect\b", f'<rect id="{new_id}"', tag_text, count=1)
    return svg_text[: match.start()] + updated_tag + svg_text[match.end():]


def inject_structured_metadata(
    *,
    svg_text: str,
    layout_id: str | None,
    master_id: str | None,
    workspace_id: str | None,
) -> str:
    """
    Inject data-pptx-* attributes onto the SVG root element and ensure any
    full-canvas background <rect> carries a stable id (required by the
    structured converter's Layer/Layout element contract).
    Returns svg_text unchanged when layout_id is None (flat mode).
    """
    if layout_id is None:
        return svg_text

    svg_text = _ensure_background_id(svg_text)

    attrs = (
        f' data-pptx-master="{master_id or "master-default"}"'
        f' data-pptx-master-name="Default Master"'
        f' data-pptx-layout="{layout_id}"'
        f' data-pptx-layout-name="{_layout_display_name(layout_id)}"'
        f' data-pptx-page-role="{_layout_to_page_role(layout_id)}"'
    )

    # Insert attributes into the opening <svg ...> tag
    return re.sub(r'(<svg\b)', r'\1' + attrs, svg_text, count=1)
