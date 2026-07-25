"""Generate spec_lock.md sections for structured PPTX export.

Builds converter-compatible contract:
  pptx_structure, pptx_masters, pptx_layouts, page_pptx_layouts, page_layouts
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


# Layout key -> display name mapping
LAYOUT_DISPLAY_NAMES = {
    "layout-title": "Title",
    "layout-title-content": "Title and Content",
    "layout-section": "Section Header",
    "layout-two-column": "Two Column",
    "layout-image-text": "Image with Text",
    "layout-data": "Data Visualization",
    "layout-blank": "Blank",
}

# Internal kind -> converter layout key
KIND_TO_LAYOUT_KEY = {
    "title": "layout-title",
    "title_content": "layout-title-content",
    "section": "layout-section",
    "two_column": "layout-two-column",
    "image_text": "layout-image-text",
    "data": "layout-data",
    "blank": "layout-blank",
}


def install_structured_templates(project_dir: Path) -> None:
    """Copy builtin layout template SVGs to project templates/ directory."""
    templates_dir = project_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    
    source_dir = Path(__file__).parent / "structured_templates"
    for svg_file in source_dir.glob("*.svg"):
        dest = templates_dir / svg_file.name
        if not dest.exists():
            shutil.copy2(svg_file, dest)


def build_structured_spec_lock_sections(
    *,
    layout_assignments: list[str],
    master_key: str = "master-default",
    master_name: str = "Default Master",
) -> str:
    """
    Build pptx_masters, pptx_layouts, page_pptx_layouts, page_layouts sections.
    
    Args:
        layout_assignments: List of layout keys per page (e.g. ["layout-title", "layout-title-content", ...])
        master_key: Master key for all layouts
        master_name: Display name for master
        
    Returns:
        Multi-section string to append to spec_lock.md
    """
    lines = []
    
    # pptx_masters section
    lines.append("\n## pptx_masters")
    lines.append(f"- {master_key}: {master_name}")
    
    # pptx_layouts section - all unique layouts used
    used_keys = sorted(set(layout_assignments))
    lines.append("\n## pptx_layouts")
    for layout_key in used_keys:
        name = LAYOUT_DISPLAY_NAMES.get(layout_key, layout_key)
        # Source is template:<svg_basename_without_ext>
        # Our template files are named like layout_title.svg
        basename = layout_key.replace("-", "_")
        lines.append(f"- {layout_key}: {master_key} | {name} | template:{basename}")
    
    # page_pptx_layouts section - per page assignment
    lines.append("\n## page_pptx_layouts")
    for i, layout_key in enumerate(layout_assignments, 1):
        lines.append(f"- P{i:02d}: {layout_key}")
    
    # page_layouts section - per page template basename
    lines.append("\n## page_layouts")
    for i, layout_key in enumerate(layout_assignments, 1):
        basename = layout_key.replace("-", "_")
        lines.append(f"- P{i:02d}: {basename}")
    
    return "\n".join(lines)
