"""Layout assignment logic for structured PPT generation."""
import re
from typing import TypedDict


class LayoutInfo(TypedDict):
    layout_id: str
    kind: str


class LayoutAssignmentError(Exception):
    """Raised when layout assignment fails."""
    pass


def assign_layout(
    *,
    slide_index: int,
    slide_title: str,
    slide_brief: str,
    page_count: int,
    layouts: list[LayoutInfo],
) -> str:
    """
    Assign appropriate layout_id for a slide based on its position and content.
    
    Rules:
    - First slide (index=1): use 'title' layout
    - Section headers (Part, Chapter, Section keywords): use 'section' layout
    - Regular content: use 'title_content' layout
    - Fallback: 'blank' layout if nothing else available
    
    Args:
        slide_index: 1-based slide number
        slide_title: Slide title text
        slide_brief: Content brief text
        page_count: Total number of slides
        layouts: Available layouts from workspace
        
    Returns:
        layout_id string
        
    Raises:
        LayoutAssignmentError: If no suitable layout found
    """
    if not layouts:
        raise LayoutAssignmentError("No layouts available in workspace")
    
    # Build lookup by kind
    by_kind: dict[str, str] = {}
    for layout in layouts:
        kind = layout.get("kind", "")
        layout_id = layout.get("layout_id", "")
        if kind and layout_id:
            by_kind[kind] = layout_id
    
    # Rule 1: First slide gets title layout
    if slide_index == 1:
        if "title" in by_kind:
            return by_kind["title"]
        raise LayoutAssignmentError("First slide requires 'title' layout, but none found in workspace")
    
    # Rule 2: Detect section headers by keywords
    combined = f"{slide_title} {slide_brief}".lower()
    section_keywords = [
        r'\bpart\s+[ivxIVX0-9]+',  # Part I, Part 2, etc.
        r'\bchapter\s+[0-9]+',
        r'\bsection\s+[0-9]+',
        r'第[一二三四五六七八九十]+[部章节]',  # Chinese: 第一部分, 第二章, etc.
    ]
    
    for pattern in section_keywords:
        if re.search(pattern, combined):
            if "section" in by_kind:
                return by_kind["section"]
            break  # Keywords matched but no section layout, fall through
    
    # Rule 3: Regular content slides
    if "title_content" in by_kind:
        return by_kind["title_content"]
    
    # Rule 4: Fallback to blank
    if "blank" in by_kind:
        return by_kind["blank"]
    
    # No suitable layout found
    available = ", ".join(sorted(by_kind.keys()))
    raise LayoutAssignmentError(
        f"No suitable layout found for slide {slide_index}. "
        f"Available kinds: {available}"
    )


def to_converter_layout_key(layout_id: str) -> str:
    """Convert internal workspace layout_id (layout_title) to converter layout_key (layout-title)."""
    return layout_id.replace("_", "-")
