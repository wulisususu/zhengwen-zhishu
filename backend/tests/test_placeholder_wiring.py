"""Tests for deterministic placeholder wiring (post-process, no LLM markup dependency)."""
import pytest
from pathlib import Path
from app.PPT_master.placeholder_wiring import wire_placeholders, PlaceholderWiringError

TEMPLATES_DIR = Path(__file__).parent.parent / "app" / "PPT_master" / "structured_templates"


def test_wire_title_layout_with_matching_text_runs():
    """Title layout needs 2 text runs (title, subtitle); substitutes them into template carriers."""
    llm_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
        '<text x="10" y="10">Annual Review 2026</text>'
        '<text x="10" y="30">Prepared for Leadership</text>'
        '</svg>'
    )
    result = wire_placeholders(
        llm_svg_text=llm_svg,
        layout_template_path=TEMPLATES_DIR / "layout_title.svg",
    )
    assert "Annual Review 2026" in result
    assert "Prepared for Leadership" in result
    assert 'data-pptx-placeholder="title"' in result
    assert 'data-pptx-placeholder="subtitle"' in result
    # Template skeleton (ids, bounds, order) must be preserved unchanged
    assert 'id="slot-title"' in result
    assert 'id="slot-subtitle"' in result
    assert 'data-pptx-placeholder-bounds="140,200,1000,120"' in result


def test_wire_fails_when_not_enough_text_runs():
    """Layout requires 2 text placeholders; LLM output with only 1 text run must fail explicitly."""
    llm_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
        '<text x="10" y="10">Only One Line</text>'
        '</svg>'
    )
    with pytest.raises(PlaceholderWiringError, match="requires 2 text placeholder"):
        wire_placeholders(
            llm_svg_text=llm_svg,
            layout_template_path=TEMPLATES_DIR / "layout_title.svg",
        )


def test_wire_fails_on_malformed_llm_svg():
    """Malformed XML from the LLM must raise explicitly, not silently degrade."""
    with pytest.raises(PlaceholderWiringError, match="not well-formed"):
        wire_placeholders(
            llm_svg_text="<svg><unclosed>",
            layout_template_path=TEMPLATES_DIR / "layout_title.svg",
        )


def test_wire_image_text_layout_keeps_picture_placeholder_untouched():
    """image_text layout has title, picture, body; picture carrier must stay as template default."""
    llm_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
        '<text x="10" y="10">Product Overview</text>'
        '<text x="10" y="30">Our flagship feature set explained.</text>'
        '</svg>'
    )
    result = wire_placeholders(
        llm_svg_text=llm_svg,
        layout_template_path=TEMPLATES_DIR / "layout_image_text.svg",
    )
    assert "Product Overview" in result
    assert "Our flagship feature set explained." in result
    # Picture placeholder's carrier <rect> must remain exactly as template declares it
    assert 'data-pptx-placeholder="picture"' in result
    assert 'fill="#E5E7EB"' in result


def test_wire_two_column_layout_three_text_slots():
    """Two-column layout has 3 text placeholders (title, left body, right body)."""
    llm_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
        '<text x="10" y="10">Comparison</text>'
        '<text x="10" y="30">Option A details</text>'
        '<text x="10" y="50">Option B details</text>'
        '</svg>'
    )
    result = wire_placeholders(
        llm_svg_text=llm_svg,
        layout_template_path=TEMPLATES_DIR / "layout_two_column.svg",
    )
    assert "Comparison" in result
    assert "Option A details" in result
    assert "Option B details" in result
