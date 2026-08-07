"""Test SVG structured metadata injection."""
import pytest
import re
from app.PPT_master.svg_structured import inject_structured_metadata


def test_inject_metadata_adds_attributes():
    """Structured metadata appears on SVG root element."""
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><rect width="100" height="100"/></svg>'
    result = inject_structured_metadata(
        svg_text=svg,
        layout_id="layout-title-content",
        master_id="master-default",
        workspace_id="ws_builtin_ppt169_abc",
    )
    assert 'data-pptx-layout="layout-title-content"' in result
    assert 'data-pptx-master="master-default"' in result
    assert 'data-pptx-master-name="Default Master"' in result
    assert 'data-pptx-page-role="content"' in result


def test_inject_metadata_preserves_viewbox():
    """Metadata injection does not corrupt viewBox."""
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><rect/></svg>'
    result = inject_structured_metadata(
        svg_text=svg,
        layout_id="layout-title",
        master_id="master-default",
        workspace_id="ws_test",
    )
    assert 'viewBox="0 0 1280 720"' in result
    assert '<rect/>' in result


def test_no_injection_for_flat_mode():
    """Returns SVG unchanged when layout_id is None (flat mode)."""
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><rect/></svg>'
    result = inject_structured_metadata(
        svg_text=svg,
        layout_id=None,
        master_id=None,
        workspace_id=None,
    )
    assert result == svg
    assert 'data-pptx' not in result


def test_inject_metadata_valid_xml():
    """Result is valid XML after injection."""
    import xml.etree.ElementTree as ET
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><text>Hello</text></svg>'
    result = inject_structured_metadata(
        svg_text=svg,
        layout_id="layout-section",
        master_id="master-default",
        workspace_id="ws_test",
    )
    root = ET.fromstring(result)
    assert root.tag.endswith("svg")


def test_inject_metadata_adds_id_to_full_canvas_background():
    """Full-canvas background rect gets a stable id (converter requires this)."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">'
        '<rect x="0" y="0" width="1280" height="720" fill="#FFFFFF"/>'
        '<text x="10" y="10">Hi</text>'
        '</svg>'
    )
    result = inject_structured_metadata(
        svg_text=svg,
        layout_id="layout-title",
        master_id="master-default",
        workspace_id="ws1",
    )
    # The full-canvas rect must have an id attribute
    assert re.search(r'<rect[^>]*id="[^"]+"[^>]*width="1280"[^>]*height="720"', result) or \
           re.search(r'<rect[^>]*width="1280"[^>]*height="720"[^>]*id="[^"]+"', result)


def test_inject_metadata_does_not_add_id_to_non_background_rect():
    """A small decorative rect (not full-canvas) should not be forced to have an id."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">'
        '<rect x="10" y="10" width="100" height="50" fill="#FFFFFF"/>'
        '</svg>'
    )
    result = inject_structured_metadata(
        svg_text=svg,
        layout_id="layout-title",
        master_id="master-default",
        workspace_id="ws1",
    )
    # Small rect unaffected - no id forced onto it
    assert '<rect x="10" y="10" width="100" height="50" fill="#FFFFFF"/>' in result
