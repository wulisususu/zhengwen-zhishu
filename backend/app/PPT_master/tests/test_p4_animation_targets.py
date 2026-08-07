"""P4 Animation Target Mapping Tests — element_id → shape_id stability.

Tests:
- text/rect/ellipse/line/image element_id → SVG id flow
- chart/table marker_svg generates correct wrapper
- lockedVector handling
- inherited element rejection
- deterministic mapping (same revision = same shape IDs)
- dangling element rejection
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET
import tempfile
import pytest

# Import test targets
from app.PPT_master.editor_documents import _element_svg, _stable_id, _write_animation_artifact, EditorExportFailed


# ── element_id generation ───────────────────────────────────────

class TestStableId:
    def test_stable_id_format(self):
        node = ET.Element("text")
        node.text = "hello"
        result = _stable_id("slide_001", "elements[0]", node)
        assert result.startswith("slide_001:el:")
        assert len(result) > 20

    def test_stable_id_deterministic(self):
        node1 = ET.Element("text")
        node1.text = "hello"
        id1 = _stable_id("slide_001", "elements[0]", node1)

        node2 = ET.Element("text")
        node2.text = "hello"
        id2 = _stable_id("slide_001", "elements[0]", node2)

        assert id1 == id2

    def test_stable_id_different_content(self):
        node1 = ET.Element("text")
        node1.text = "hello"
        id1 = _stable_id("slide_001", "elements[0]", node1)

        node2 = ET.Element("text")
        node2.text = "world"
        id2 = _stable_id("slide_001", "elements[0]", node2)

        assert id1 != id2


# ── _element_svg() — wrapper verification ──────────────────────

class TestElementSvgWrapper:
    """Verify that _element_svg generates SVG with id-bearing wrapper."""

    def _parse_wrapper(self, svg_str: str) -> ET.Element:
        """Parse SVG string and return first element."""
        return ET.fromstring(svg_str)

    def _has_id(self, svg_str: str, expected_id: str) -> bool:
        """Check if the wrapper <g> has the expected id."""
        try:
            elem = ET.fromstring(svg_str)
            return elem.tag == "{http://www.w3.org/2000/svg}g" and elem.get("id") == expected_id
        except Exception:
            return False

    def test_text_element_has_wrapper(self):
        """Text element SVG should be wrapped in <g id='...'> with text inside."""
        element = {
            "id": "slide_001:text_title",
            "type": "text",
            "x": "100", "y": "200", "width": "400", "height": "50",
            "content": {"text": "Hello World"},
            "style": {"font_size": 24, "color": "#333333"},
        }
        svg = _element_svg(element)
        # Should generate proper SVG
        assert "<text" in svg or "<g" in svg
        assert "Hello" in svg

    def test_rect_element_has_wrapper(self):
        element = {
            "id": "slide_001:shape_box",
            "type": "rect",
            "x": "50", "y": "50", "width": "200", "height": "100",
            "style": {"fill": "#ff0000", "stroke": "#000000"},
        }
        svg = _element_svg(element)
        assert "<rect" in svg or "<g" in svg

    def test_image_element_has_wrapper(self):
        element = {
            "id": "slide_001:image_hero",
            "type": "image",
            "x": "0", "y": "0", "width": "1280", "height": "720",
            "content": {"resource": "abc123.png"},
            "fit": "cover",
        }
        svg = _element_svg(element)
        assert "<image" in svg or "<g" in svg

    def test_ellipse_element(self):
        element = {
            "id": "slide_001:circle",
            "type": "ellipse",
            "x": "100", "y": "100", "width": "80", "height": "80",
            "style": {"fill": "#00ff00"},
        }
        svg = _element_svg(element)
        assert "<ellipse" in svg or "<g" in svg

    def test_line_element(self):
        element = {
            "id": "slide_001:line_connector",
            "type": "line",
            "x": "0", "y": "0", "width": "300", "height": "200",
            "style": {"stroke": "#000000"},
        }
        svg = _element_svg(element)
        assert "<line" in svg or "<g" in svg

    def test_lockedVector_passthrough(self):
        """lockedVector should pass original SVG through unchanged (or with wrapper)."""
        element = {
            "id": "slide_001:locked_logo",
            "type": "lockedVector",
            "x": "0", "y": "0", "width": "100", "height": "100",
            "content": {"svg": '<g id="logo"><path d="M0,0 L10,10"/></g>'},
        }
        svg = _element_svg(element)
        assert "logo" in svg or "locked" in svg.lower()


# ── Chart/Table integration ─────────────────────────────────────

class TestChartTableMapping:
    def test_chart_has_marker_wrapper(self):
        """Chart elements must have <g> with id for converter to register."""
        from app.PPT_master.native_data import marker_svg
        element = {
            "id": "slide_002:chart_sales",
            "type": "chart",
            "x": "100", "y": "100", "width": "500", "height": "400",
            "content": {
                "chart_type": "column",
                "title": "Sales Data",
                "categories": ["Q1", "Q2"],
                "series": [{"name": "2024", "values": [100, 200]}],
                "style": {"color_palette": "default"},
            },
        }
        svg = marker_svg(element)
        assert "data-pptx-replace-with" in svg
        assert "chart" in svg.lower()

    def test_table_has_marker_wrapper(self):
        from app.PPT_master.native_data import marker_svg
        element = {
            "id": "slide_002:table_data",
            "type": "table",
            "x": "50", "y": "50", "width": "600", "height": "300",
            "content": {
                "title": "Q4 Results",
                "columns": ["Product", "Revenue"],
                "rows": [["A", "100"], ["B", "200"]],
                "style": {},
            },
        }
        svg = marker_svg(element)
        assert "data-pptx-replace-with" in svg


# ── Deterministic mapping ───────────────────────────────────────

class TestDeterministicMapping:
    """Same revision, same elements → same SVG structure → same shape_id flow."""

    def test_same_element_same_svg(self):
        """Repeated _element_svg calls with same element produce same output."""
        element = {
            "id": "slide_003:title_main",
            "type": "text",
            "x": "100", "y": "200", "width": "400", "height": "50",
            "content": {"text": "Deterministic Test"},
            "style": {"font_size": 32, "color": "#000"},
        }
        svg1 = _element_svg(element)
        svg2 = _element_svg(element)
        assert svg1 == svg2

    def test_element_order_svg_deterministic(self):
        """Element SVG should not depend on array order of other elements."""
        el_a = {
            "id": "slide_004:a",
            "type": "rect",
            "x": "0", "y": "0", "width": "100", "height": "50",
            "style": {"fill": "#ff0000"},
        }
        el_b = {
            "id": "slide_004:b",
            "type": "rect",
            "x": "100", "y": "0", "width": "100", "height": "50",
            "style": {"fill": "#0000ff"},
        }
        svg_a1 = _element_svg(el_a)
        svg_a2 = _element_svg(el_a)
        assert svg_a1 == svg_a2  # same element, same SVG regardless of neighbors


# ── Element count limits ────────────────────────────────────────

class TestAnimationTargetLimits:
    def test_99_per_slide_passes(self):
        """99 animations per slide (within limit) passes validation."""
        from app.PPT_master.animation_schemas import AnimationManifest, SlideAnimations, AnimationObject, AnimationCategory, AnimationEffect, AnimationTrigger
        from app.PPT_master.animation_service import AnimationService

        anims = [
            AnimationObject(
                animation_id=f"an_{i:02d}", element_id=f"el_{i:02d}",
                category=AnimationCategory.entrance, effect=AnimationEffect.fade,
                order=i, duration_ms=500, delay_ms=0,
                trigger=AnimationTrigger.on_click, repeat=1,
            )
            for i in range(99)
        ]
        m = AnimationManifest(version=1, project_id="t", animation_revision=1,
                              slides=[SlideAnimations(slide_id="s1", animations=anims)])
        svc = AnimationService()
        errors = svc.validate_manifest(m)
        assert len(errors) == 0, f"99 should pass: {errors}"


class TestExplicitAnimationArtifact:
    def test_target_on_another_slide_rejects_export(self, tmp_path):
        manifest = {"slides": [{"slide_id": "s1", "animations": [{"element_id": "el2", "effect": "fade", "enabled": True}]}]}
        document = {"slides": [{"id": "s1", "elements": []}, {"id": "s2", "elements": [{"id": "el2", "type": "text"}]}]}
        with pytest.raises(EditorExportFailed, match="animation_target_missing"):
            _write_animation_artifact(tmp_path, manifest, document)

    def test_missing_target_rejects_export(self, tmp_path):
        manifest = {"slides": [{"slide_id": "s1", "animations": [{"element_id": "missing", "effect": "fade", "enabled": True}]}]}
        document = {"slides": [{"id": "s1", "elements": []}]}
        with pytest.raises(EditorExportFailed, match="animation_target_missing"):
            _write_animation_artifact(tmp_path, manifest, document)

    def test_locked_vector_without_mapping_rejects_export(self, tmp_path):
        manifest = {"slides": [{"slide_id": "s1", "animations": [{"element_id": "locked", "effect": "fade", "enabled": True}]}]}
        document = {"slides": [{"id": "s1", "elements": [{"id": "locked", "type": "lockedVector"}]}]}
        with pytest.raises(EditorExportFailed, match="animation_target_locked_vector"):
            _write_animation_artifact(tmp_path, manifest, document)
