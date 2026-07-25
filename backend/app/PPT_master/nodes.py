"""LangGraph nodes for PPT-master pipeline."""
import asyncio
import contextvars
import json
import logging
import os
import re
import uuid
from pathlib import Path

from app.PPT_master.state import PipelineState
from app.PPT_master.incremental_slides import extract_outline, generate_slide
from app.PPT_master.llm_client import call_glm, GLMApiError
from app.PPT_master.security import validate_svg_directory
from app.PPT_master.validation import (
    build_validation_result,
    merge_validation_results,
    validate_pptx,
    count_pptx_slides,
)
from app.PPT_master.subprocesses import (
    CommandExecutionError,
    CommandTimeoutError,
    run_command,
)
from app.PPT_master.admission import enforce_directory_quota

logger = logging.getLogger(__name__)

# === SSE context ===
_sse_queue_ctx: contextvars.ContextVar = contextvars.ContextVar("sse_queue", default=None)

def set_sse_queue(queue: asyncio.Queue) -> None:
    _sse_queue_ctx.set(queue)

def get_sse_queue() -> asyncio.Queue | None:
    return _sse_queue_ctx.get(None)

async def _push_sse(event_type: str, data: dict) -> None:
    queue = get_sse_queue()
    if queue:
        await queue.put({"type": event_type, "data": data})

# === Path helpers ===
PROJECTS_ROOT = Path(__file__).resolve().parent.parent.parent  # backend/
SKILL_SCRIPTS = Path(__file__).resolve().parent / "skill" / "ppt-master" / "scripts"
_DEFAULT_PPT_PYTHON = Path.home() / ".config" / "ai-box" / "runtime" / "ppt-master-venv" / "bin" / "python3"
_PROJECT_MAX_BYTES = 200 * 1024 * 1024

def _abs_script(rel_path: str) -> str:
    return str(SKILL_SCRIPTS / rel_path)

def _python() -> str:
    """Return path to ppt-master dedicated venv python."""
    return os.environ.get("PPT_MASTER_PYTHON", str(_DEFAULT_PPT_PYTHON))

# === GLM call with retry wrapper ===

async def _call_glm_with_retry(system_prompt: str, user_prompt: str, step_name: str) -> str:
    """Call GLM-5.2 with 3-retry backoff, return full response text."""
    parts = []
    async for chunk in call_glm(system_prompt, user_prompt):
        parts.append(chunk)
    return "".join(parts)

# === Prompt templates ===

STRATEGIST_PROMPT = """You are a PPT Strategist (presentation design expert). Your role is to analyze the user's input and produce a structured design specification for a PowerPoint presentation.

## Your Task
1. Analyze the user's topic, material, and requirements
2. Determine the visual theme: color palette (3-7 colors with hex codes), font family, overall style
3. Plan each page: page number, layout type, key content points
4. Output TWO sections separated by the delimiter ===SPEC_LOCK===

## Section 1: design_spec.md
A complete design specification in Markdown:

# Design Specification

## Theme
- **Color Palette**: [list hex colors with roles: bg, primary, accent, text, text_secondary, border]
- **Font Family**: [font stack, e.g. "Microsoft YaHei", Arial, sans-serif]
- **Style**: [style description, e.g. swiss-minimal, tech-neon, editorial]

## Page Plan
For each page (1 to N):
### Page X: [Page Title]
- **Layout**: [layout description]
- **Key Content**: [bullet points]
- **Visual Elements**: [icons, shapes to include — no external images]

## Section 2: spec_lock.md (after ===SPEC_LOCK=== delimiter)
A machine-readable execution contract in Markdown:

## canvas
- viewBox: 0 0 1280 720
- format: PPT 16:9

## mode
- mode: briefing

## visual_style
- visual_style: swiss-minimal

## colors
- bg: #HEX
- primary: #HEX
- accent: #HEX
- text: #HEX
- text_secondary: #HEX
- border: #HEX

## typography
- font_family: "Font Name", fallback, sans-serif
- title: 42
- body: 24

## pptx_structure
- mode: flat

## Important
- Colors in Section 2 MUST match Section 1
- title and body are unitless pixel sizes
- Output the delimiter ===SPEC_LOCK=== on its own line between sections
- No markdown code fences, just raw content"""

EXECUTOR_PROMPT = """You are a PPT Executor (presentation SVG designer). Your role is to generate high-quality SVG slides based on a design specification.

## Your Task
Read the design_spec below and generate SVG slides for ALL pages. Each page must be a complete, self-contained SVG.

## SVG Requirements
- viewBox='0 0 1280 720' (16:9) or viewBox='0 0 960 720' (4:3) based on format
- All text in <text> elements with proper font-family, font-size (px), fill color
- Clean geometric shapes: <rect>, <circle>, <path>, <line>
- Color palette strictly from the design_spec
- Safe margins: 80px from all edges for text content
- No external dependencies (fonts, CSS, images) - use system fonts only
- No scripts, animations, or interactivity
- Semantic grouping with <g> elements

## CRITICAL — PowerPoint Compatibility Rules
- **NO filters on <g> elements**: <g> cannot use filter="...". Use filters only on <rect>, <circle>, <path>, and <text> elements directly
- **NO group opacity on <g>**: Do not use opacity="..." on <g> elements. Apply opacity directly to child elements instead
- **NO <use> elements**: Write out shapes directly, do not use <use> references
- **NO external images**: All visuals must be vector shapes only
- **Flatten all text spans**: Use plain <text> elements, avoid nested <tspan>

## Output Format
Output as a valid JSON array (no markdown code fences, just raw JSON):
[
  {
    "page": 1,
    "title": "Page Title",
    "svg": "<svg viewBox='0 0 1280 720' xmlns='http://www.w3.org/2000/svg'>...</svg>"
  },
  ...
]

## Important
- Generate ALL pages specified
- Each SVG must be complete and self-contained
- Output ONLY the JSON array, nothing else
- SVG strings must use single quotes for attributes inside JSON double quotes
- Ensure each SVG is valid XML with no unsupported attributes"""

# === spec_lock helper ===

def _write_spec_lock(proj_dir: str, spec_lock_text: str) -> None:
    """Write spec_lock.md to project directory."""
    if proj_dir:
        lock_path = Path(proj_dir) / "spec_lock.md"
        lock_path.write_text(spec_lock_text.strip(), encoding="utf-8")
        logger.info("spec_lock.md written")


def _build_default_spec_lock(
    page_format: str = "ppt169",
    primary_hex: str = "#2563EB",
    accent_hex: str = "#F59E0B",
    bg_hex: str = "#FFFFFF",
    text_hex: str = "#1E293B",
    text_secondary_hex: str = "#64748B",
    border_hex: str = "#CBD5E1",
    font_family: str = '"Microsoft YaHei", Arial, sans-serif',
    title_size: int = 42,
    body_size: int = 24,
    pptx_structure_mode: str = "flat",
    structured_workspace_id: str | None = None,
    layout_assignments: list[str] | None = None,
) -> str:
    """Build a minimal spec_lock.md for flat-mode export."""
    # Validate structured mode
    if pptx_structure_mode == "structured" and not structured_workspace_id:
        raise ValueError("structured_workspace_id is required when pptx_structure_mode=structured")
    
    if pptx_structure_mode == "structured" and structured_workspace_id:
        # Build full structured contract for converter
        from app.PPT_master.structured_spec_lock import build_structured_spec_lock_sections
        structure_section = "- template_adherence: adaptive"
        if layout_assignments:
            structure_section += build_structured_spec_lock_sections(
                layout_assignments=layout_assignments
            )
    else:
        structure_section = ""
    

    vb = "0 0 1280 720" if page_format == "ppt169" else "0 0 960 720"
    fmt_label = "PPT 16:9" if page_format == "ppt169" else "PPT 4:3"
    return f"""## canvas
- viewBox: {vb}
- format: {fmt_label}

## mode
- mode: briefing

## visual_style
- visual_style: swiss-minimal

## colors
- bg: {bg_hex}
- primary: {primary_hex}
- accent: {accent_hex}
- text: {text_hex}
- text_secondary: {text_secondary_hex}
- border: {border_hex}

## typography
- font_family: {font_family}
- title: {title_size}
- body: {body_size}

## pptx_structure
- mode: {pptx_structure_mode}
{structure_section}"""


def _extract_hex_colors(text: str) -> dict:
    """Extract hex color values from design spec text."""
    hexes = re.findall(r'#[0-9A-Fa-f]{6}', text)
    result = {}
    keys = ["primary", "accent", "bg", "text", "text_secondary", "border"]
    for i, h in enumerate(hexes[:len(keys)]):
        result[keys[i]] = h
    # Ensure defaults for unfound colors
    defaults = {
        "bg": "#FFFFFF", "primary": "#2563EB", "accent": "#F59E0B",
        "text": "#1E293B", "text_secondary": "#64748B", "border": "#CBD5E1"
    }
    for k in keys:
        if k not in result:
            result[k] = defaults[k]
    return result


def _extract_font_family(text: str) -> str:
    """Extract font family from design spec text."""
    # Look for common font patterns
    m = re.search(r'(?:font.family|Font Family|font-family)[:\s]*["\']?([^"\'\n]+)["\']?', text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return '"Microsoft YaHei", Arial, sans-serif'

# === Node functions ===

async def parse_node(state: PipelineState) -> PipelineState:
    """Step 1: Initialize project directory via project_manager.py."""
    if state.get("sources"):
        return {
            **state,
            "status": "graceful_fallback",
            "graceful_error": "sources_disabled",
        }
    name = f"pptgen_{uuid.uuid4().hex[:8]}"
    projects_dir = PROJECTS_ROOT / "app" / "PPT_master" / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    fmt = state.get("page_format", "ppt169")
    proj_dir = projects_dir / name  # fallback

    try:
        result = await run_command(
            [_python(), _abs_script("project_manager.py"), "init", name,
             "--format", fmt, "--dir", str(projects_dir)],
            check=True, timeout=60,
            cwd=str(PROJECTS_ROOT),
        )
        logger.info("project_manager init completed")
        # Find the actual created directory (naming: {name}_{format}_{date})
        for d in sorted(projects_dir.iterdir(), key=os.path.getmtime, reverse=True):
            if d.is_dir() and d.name.startswith(name):
                proj_dir = d
                logger.info("Project directory initialized: %s", proj_dir.name)
                break
    except (CommandExecutionError, CommandTimeoutError):
        logger.warning("project_manager init failed, using manual setup")
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "svg_output").mkdir(exist_ok=True)

    enforce_directory_quota(proj_dir, _PROJECT_MAX_BYTES)

    await _push_sse("progress", {"step": "parse", "project": proj_dir.name})

    return {
        **state,
        "project_dir": str(proj_dir),
        "status": "parsed",
        "task_id": state.get("task_id", name),
    }


async def source_md_node(state: PipelineState) -> PipelineState:
    """Step 2: Convert source files to Markdown (skip if no sources)."""
    sources = state.get("sources", [])
    if sources:
        return {
            **state,
            "status": "graceful_fallback",
            "graceful_error": "sources_disabled",
        }
    if not sources:
        logger.debug("No sources provided, skipping source_md")
        return {**state, "status": "source_done"}

    return {**state, "status": "graceful_fallback", "graceful_error": "sources_disabled"}


async def spec_node(state: PipelineState) -> PipelineState:
    """Step 3: Generate design_spec.md + spec_lock.md via GLM-5.2."""
    await _push_sse("progress", {"step": "spec", "message": "Planning design specification..."})

    fmt = state.get("page_format", "ppt169")
    pages = state.get("page_count", 8)
    user_input = state["user_input"]
    source_context = state.get("source_context", "")
    user_prompt = (
        f"Create a design specification for a {pages}-page {fmt} presentation.\n\n"
        f"Topic/Material:\n{user_input}\n\n"
        + (f"Selected source material:\n{source_context}\n\n" if source_context else "")
        + "Output both sections (design_spec and spec_lock) separated by ===SPEC_LOCK==="
    )

    try:
        full_response = await _call_glm_with_retry(STRATEGIST_PROMPT, user_prompt, "spec")
    except GLMApiError as e:
        return {**state, "status": "graceful_fallback", "graceful_error": str(e)[:200]}

    # Split response into design_spec and spec_lock
    if "===SPEC_LOCK===" in full_response:
        parts = full_response.split("===SPEC_LOCK===", 1)
        design_spec = parts[0].strip()
        spec_lock_text = parts[1].strip()
    else:
        design_spec = full_response.strip()
        # Build default spec_lock from extracted values
        colors = _extract_hex_colors(design_spec)
        font = _extract_font_family(design_spec)
        spec_lock_text = _build_default_spec_lock(
            page_format=fmt,
            primary_hex=colors.get("primary", "#2563EB"),
            accent_hex=colors.get("accent", "#F59E0B"),
            bg_hex=colors.get("bg", "#FFFFFF"),
            text_hex=colors.get("text", "#1E293B"),
            text_secondary_hex=colors.get("text_secondary", "#64748B"),
            border_hex=colors.get("border", "#CBD5E1"),
            font_family=font,
            pptx_structure_mode=state.get("pptx_structure_mode", "flat"),
            structured_workspace_id=state.get("structured_workspace_id"),
        )

    # Write both files
    proj_dir = state.get("project_dir", "")
    if proj_dir:
        (Path(proj_dir) / "design_spec.md").write_text(design_spec, encoding="utf-8")
        _write_spec_lock(proj_dir, spec_lock_text)
        enforce_directory_quota(proj_dir, _PROJECT_MAX_BYTES)

    await _push_sse("spec", {"design_spec_preview": design_spec[:500]})
    return {**state, "design_spec": design_spec, "status": "spec_done"}


async def svg_node(state: PipelineState) -> PipelineState:
    """Step 4: Generate SVG pages one page at a time with per-slide repair."""
    pages = state.get("page_count", 8)
    await _push_sse("progress", {"step": "svg", "current": 0, "total": pages,
                                 "message": "Generating SVG slides..."})

    design_spec = state.get("design_spec", "")
    page_format = state.get("page_format", "ppt169")
    user_input = state["user_input"]
    proj_dir = state.get("project_dir", "")
    if not proj_dir:
        return {**state, "status": "graceful_fallback", "graceful_error": "project_directory_missing"}

    svg_pages: list[dict] = []
    failed_slides: list[dict] = []
    svg_metrics = {
        "model_output_count": 0,
        "svg_xml_invalid_count": 0,
        "svg_sanitize_success_count": 0,
        "svg_validation_blocked_count": 0,
        "model_repair_retry_count": 0,
    }

    for item in extract_outline(design_spec, pages, user_input):
        index = int(item["index"])
        title = str(item["title"])
        result = await generate_slide(
            project_dir=proj_dir,
            task_id=state.get("task_id", ""),
            index=index,
            title=title,
            content_brief=str(item.get("content_brief") or title),
            page_count=pages,
            page_format=page_format,
            design_spec=design_spec,
            user_input=user_input,
        )
        for key in svg_metrics:
            svg_metrics[key] += int(result.metrics.get(key, 0))
        if result.svg_path is None:
            failure = {"index": index, "title": title, "errors": result.errors}
            if result.diagnostics:
                failure["diagnostics"] = result.diagnostics
            failed_slides.append(failure)
        else:
            svg_pages.append({"page": index, "title": title})
        await _push_sse("progress", {
            "step": "svg",
            "current": index,
            "total": pages,
            "message": f"Generated {len(svg_pages)} of {pages} slides",
        })

    enforce_directory_quota(proj_dir, _PROJECT_MAX_BYTES)
    await _push_sse("progress", {
        "step": "svg_done",
        "current": pages,
        "total": pages,
        "completed": len(svg_pages),
        "failed": len(failed_slides),
    })
    return {
        **state,
        "svg_pages": svg_pages,
        "failed_slides": failed_slides,
        "svg_metrics": svg_metrics,
        "status": "svg_done",
    }


async def validate_node(state: PipelineState) -> PipelineState:
    """Step 5: Run the blocking SVG security and quality gates."""
    proj_dir = state.get("project_dir", "")
    await _push_sse("progress", {"step": "validate", "message": "Running SVG quality check..."})
    failed_slides = list(state.get("failed_slides") or [])
    svg_metrics = state.get("svg_metrics") or {}

    if not proj_dir:
        validation_result = build_validation_result(blocking_errors=["svg_directory_missing"])
        await _push_sse("validate", validation_result)
        return {
            **state,
            "status": "validation_failed",
            "svg_security_errors": ["svg_directory_missing"],
            "validation_result": validation_result,
        }

    if failed_slides:
        validation_result = build_validation_result(blocking_errors=["svg_xml_invalid"])
        await _push_sse("validate", validation_result)
        return {
            **state,
            "status": "validation_failed",
            "validation_result": validation_result,
            "failed_slides": failed_slides,
            "svg_metrics": svg_metrics,
        }

    image_dir = Path(proj_dir) / "images"
    registered_media_resources = {
        path.resolve()
        for path in image_dir.glob("*")
        if path.is_file() and not path.is_symlink()
    } if image_dir.is_dir() else set()
    security_errors = validate_svg_directory(proj_dir, registered_resources=registered_media_resources)
    if security_errors:
        logger.warning("SVG security gate blocked export: %s", ",".join(security_errors))
        validation_result = build_validation_result(blocking_errors=security_errors)
        await _push_sse("validate", validation_result)
        return {
            **state,
            "status": "validation_failed",
            "svg_security_errors": security_errors,
            "validation_result": validation_result,
        }

    svg_dir = Path(proj_dir) / "svg_output"
    if len(sorted(svg_dir.glob("*.svg"))) != int(state.get("page_count", 0)):
        validation_result = build_validation_result(blocking_errors=["svg_page_count_mismatch"])
        await _push_sse("validate", validation_result)
        return {
            **state,
            "status": "validation_failed",
            "validation_result": validation_result,
            "svg_metrics": svg_metrics,
        }

    try:
        result = await run_command(
            [_python(), _abs_script("svg_quality_checker.py"), proj_dir],
            timeout=120,
            cwd=str(PROJECTS_ROOT),
        )
        if result.returncode != 0:
            validation_result = build_validation_result(blocking_errors=["svg_quality_check_failed"])
        else:
            validation_result = build_validation_result()
        logger.info("svg_quality_checker completed with code %s", result.returncode)
    except CommandTimeoutError:
        logger.warning("svg_quality_checker timed out")
        validation_result = build_validation_result(blocking_errors=["svg_quality_check_timeout"])
    except Exception:
        logger.exception("svg_quality_checker failed")
        validation_result = build_validation_result(blocking_errors=["svg_quality_check_error"])

    await _push_sse("validate", validation_result)
    return {
        **state,
        "status": "validated" if validation_result["passed"] else "validation_failed",
        "validation_result": validation_result,
        "svg_metrics": svg_metrics,
    }


async def export_node(state: PipelineState) -> PipelineState:
    """Step 6: finalize_svg -> svg_to_pptx -> collect pptx."""
    proj_dir = state.get("project_dir", "")
    await _push_sse("progress", {"step": "export", "message": "Exporting PPTX..."})

    validation_result = state.get("validation_result") or build_validation_result(
        blocking_errors=["validation_not_run"]
    )
    if not validation_result.get("passed") or validation_result.get("blocking_errors"):
        await _push_sse("fallback", {
            "message": "PPT 质检未通过",
            "valid": False,
            "validation_result": validation_result,
            "failed_slides": state.get("failed_slides") or [],
            "metrics": state.get("svg_metrics") or {},
        })
        return {
            **state,
            "pptx_valid": False,
            "status": "graceful_fallback",
            "graceful_error": "validation_failed",
            "validation_result": validation_result,
        }

    if not proj_dir:
        validation_result = merge_validation_results(
            validation_result,
            build_validation_result(blocking_errors=["project_directory_missing"]),
        )
        return {
            **state,
            "pptx_valid": False,
            "status": "graceful_fallback",
            "graceful_error": "project_directory_missing",
            "validation_result": validation_result,
        }

    requested_pages = int(state.get("page_count", 0))
    svg_dir = Path(proj_dir) / "svg_output"
    svg_files = sorted(svg_dir.glob("page_*.svg"))
    if len(svg_files) != requested_pages:
        mismatch = build_validation_result(
            errors=[f"page_count_mismatch: requested={requested_pages}, outline={requested_pages}, completed={len(svg_files)}, exported=0"],
            blocking_errors=["page_count_mismatch"],
        )
        return {**state, "pptx_valid": False, "status": "graceful_fallback", "graceful_error": "page_count_mismatch", "validation_result": mismatch}

    # Run finalize_svg then svg_to_pptx (skip total_md_split — speaker notes optional)
    script_chain = [
        ("finalize_svg.py", 300),
        ("svg_to_pptx.py", 300),
    ]

    for script, timeout in script_chain:
        try:
            result = await run_command(
                [_python(), _abs_script(script), proj_dir],
                check=True, timeout=timeout,
                cwd=str(PROJECTS_ROOT),
            )
            enforce_directory_quota(proj_dir, _PROJECT_MAX_BYTES)
            logger.info("%s completed with code %s", script, result.returncode)
        except CommandTimeoutError:
            code = "export_timeout"
            logger.error("%s timed out", script)
        except CommandExecutionError:
            code = "export_failed"
            logger.exception("%s failed", script)
        except Exception:
            code = "export_error"
            logger.exception("%s failed unexpectedly", script)
        else:
            continue

        validation_result = merge_validation_results(
            validation_result,
            build_validation_result(blocking_errors=[f"{code}:{script}"]),
        )
        await _push_sse("fallback", {
            "message": "PPTX export failed",
            "valid": False,
            "validation_result": validation_result,
        })
        return {
            **state,
            "pptx_valid": False,
            "status": "graceful_fallback",
            "graceful_error": code,
            "validation_result": validation_result,
        }

    # Find exported pptx
    exports_dir = Path(proj_dir) / "exports"
    pptx_path = ""
    pptx_size = 0
    if exports_dir.exists():
        pptx_files = sorted(exports_dir.glob("*.pptx"), key=os.path.getmtime, reverse=True)
        if pptx_files:
            pptx_path = str(pptx_files[0])
            pptx_size = os.path.getsize(pptx_path)

    pptx_result = validate_pptx(pptx_path, expected_pages=requested_pages)
    validation_result = merge_validation_results(validation_result, pptx_result)
    if not validation_result["passed"]:
        await _push_sse("fallback", {
            "message": "PPTX structure validation failed",
            "valid": False,
            "validation_result": validation_result,
        })
        return {
            **state,
            "pptx_path": "",
            "pptx_size": 0,
            "pptx_valid": False,
            "status": "graceful_fallback",
            "graceful_error": "pptx_validation_failed",
            "validation_result": validation_result,
        }

    return {
        **state,
        "pptx_path": pptx_path,
        "pptx_size": pptx_size,
        "pptx_valid": True,
        "slide_count": count_pptx_slides(pptx_path),
        "status": "done",
        "validation_result": validation_result,
    }
