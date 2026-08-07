"""Test layout assignment logic for structured mode."""
import pytest
from app.PPT_master.planning_layout import (
    assign_layout,
    LayoutAssignmentError,
)


def test_assign_layout_title_slide():
    """First slide gets title layout."""
    layouts = [
        {"layout_id": "layout_title", "kind": "title"},
        {"layout_id": "layout_title_content", "kind": "title_content"},
    ]
    
    result = assign_layout(
        slide_index=1,
        slide_title="Welcome",
        slide_brief="Introduction",
        page_count=8,
        layouts=layouts,
    )
    
    assert result == "layout_title"


def test_assign_layout_content_slide():
    """Regular content slides get title_content layout."""
    layouts = [
        {"layout_id": "layout_title", "kind": "title"},
        {"layout_id": "layout_title_content", "kind": "title_content"},
    ]
    
    result = assign_layout(
        slide_index=2,
        slide_title="Key Points",
        slide_brief="Main content",
        page_count=8,
        layouts=layouts,
    )
    
    assert result == "layout_title_content"


def test_assign_layout_section_slide():
    """Section headers detected by keywords."""
    layouts = [
        {"layout_id": "layout_title_content", "kind": "title_content"},
        {"layout_id": "layout_section", "kind": "section"},
    ]
    
    result = assign_layout(
        slide_index=3,
        slide_title="Part II: Analysis",
        slide_brief="Section header",
        page_count=8,
        layouts=layouts,
    )
    
    assert result == "layout_section"


def test_assign_layout_blank_fallback():
    """Falls back to blank if no suitable layout."""
    layouts = [
        {"layout_id": "layout_blank", "kind": "blank"},
    ]
    
    result = assign_layout(
        slide_index=2,
        slide_title="Any Slide",
        slide_brief="Content",
        page_count=8,
        layouts=layouts,
    )
    
    assert result == "layout_blank"


def test_assign_layout_no_layouts_raises():
    """Raises error if no layouts available."""
    with pytest.raises(LayoutAssignmentError, match="No layouts available"):
        assign_layout(
            slide_index=1,
            slide_title="Title",
            slide_brief="Brief",
            page_count=8,
            layouts=[],
        )


def test_assign_layout_missing_required_raises():
    """Raises error if required layout missing."""
    layouts = [
        {"layout_id": "layout_section", "kind": "section"},
    ]
    
    with pytest.raises(LayoutAssignmentError, match="title.*layout"):
        assign_layout(
            slide_index=1,
            slide_title="First",
            slide_brief="Brief",
            page_count=8,
            layouts=layouts,
        )
