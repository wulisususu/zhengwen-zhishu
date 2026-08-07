"""Test structured spec_lock section builder."""
from pathlib import Path
import tempfile
import pytest

from app.PPT_master.structured_spec_lock import (
    build_structured_spec_lock_sections,
    install_structured_templates,
    KIND_TO_LAYOUT_KEY,
    LAYOUT_DISPLAY_NAMES,
)


def test_build_sections_single_page():
    result = build_structured_spec_lock_sections(
        layout_assignments=["layout-title"]
    )
    assert "## pptx_masters" in result
    assert "master-default: Default Master" in result
    assert "## pptx_layouts" in result
    assert "layout-title: master-default | Title | template:layout_title" in result
    assert "## page_pptx_layouts" in result
    assert "P01: layout-title" in result
    assert "## page_layouts" in result
    assert "P01: layout_title" in result


def test_build_sections_multiple_pages():
    result = build_structured_spec_lock_sections(
        layout_assignments=[
            "layout-title",
            "layout-title-content",
            "layout-two-column",
        ]
    )
    # Deduplicated in pptx_layouts
    assert result.count("- layout-title:") == 1
    assert "- layout-title-content:" in result
    assert "- layout-two-column:" in result
    # But all pages listed in page_pptx_layouts
    assert "P01: layout-title" in result
    assert "P02: layout-title-content" in result
    assert "P03: layout-two-column" in result


def test_build_sections_deduplicates_repeated_layouts():
    result = build_structured_spec_lock_sections(
        layout_assignments=[
            "layout-title",
            "layout-title-content",
            "layout-title-content",
            "layout-title-content",
        ]
    )
    # Only one definition line for layout-title-content
    assert result.count("- layout-title-content:") == 1
    # But page assignments listed for each
    assert "P02: layout-title-content" in result
    assert "P03: layout-title-content" in result
    assert "P04: layout-title-content" in result


def test_kind_to_layout_key_covers_all_seven():
    required = {"title", "title_content", "section", "two_column", "image_text", "data", "blank"}
    assert required.issubset(KIND_TO_LAYOUT_KEY.keys())


def test_install_structured_templates_copies_svgs():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        install_structured_templates(project)
        templates = project / "templates"
        assert templates.exists()
        assert (templates / "layout_title.svg").exists()
        assert (templates / "layout_title_content.svg").exists()
        assert (templates / "layout_blank.svg").exists()
        # Verify content has expected metadata
        title_svg = (templates / "layout_title.svg").read_text()
        assert "data-pptx-master=\"master-default\"" in title_svg
        assert "data-pptx-layout=\"layout-title\"" in title_svg
