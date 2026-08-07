"""One-page SVG generation, parsing, security validation, and repair."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from app.PPT_master.planning_layout import assign_layout, LayoutAssignmentError, to_converter_layout_key
from app.PPT_master.svg_structured import inject_structured_metadata
from app.PPT_master.placeholder_wiring import wire_placeholders, PlaceholderWiringError

_STRUCTURED_TEMPLATES_DIR = Path(__file__).parent / "structured_templates"
from typing import Awaitable, Callable

from app.PPT_master.llm_client import call_glm
from app.PPT_master.security import inspect_model_svg_output
from app.PPT_master.subprocesses import CommandTimeoutError, run_command


_PAGE_HEADING_RE = re.compile(
    r"^\s*#{1,6}\s*(?:page|slide|第)\s*(\d+)\s*(?:页)?\s*[:：\-—]\s*(.+?)\s*$",
    re.IGNORECASE,
)
_PUBLIC_SECRET_RE = re.compile(
    r"(?i)(?:https?://|file://)\S+|(?:/home|/etc|/proc)/\S+|[A-Za-z]:\\\S+"
)
_SVG_RE = re.compile(r"<svg\b[\s\S]*?</svg>\s*", re.IGNORECASE)
_UNSUPPORTED_TEXT_PROPERTY_RE = re.compile(
    r"unsupported text property ['\"]([A-Za-z0-9_-]+)['\"]", re.IGNORECASE
)
_QUALITY_CHECKER = (
    Path(__file__).resolve().parent / "skill" / "ppt-master" / "scripts" / "svg_quality_checker.py"
)
_DEFAULT_PPT_PYTHON = (
    Path.home() / ".config" / "ai-box" / "runtime" / "ppt-master-venv" / "bin" / "python3"
)

_SINGLE_SLIDE_SYSTEM_PROMPT = """You are a presentation SVG renderer.
Return exactly one complete SVG slide and no explanation.
The SVG must use the requested viewBox, native shapes and text.
Never use script, foreignObject, use, event handlers, filters, external URLs,
file://, data URLs, absolute paths, relative resources, or entity declarations.
Use only svg, g, rect, circle, ellipse, line, polyline, polygon, path, text,
and tspan elements. Use presentation-safe XML attributes, not a style attribute.
For text, use x/y, fill, font-family, font-size, font-weight, text-anchor and
simple tspans. Never use dominant-baseline, baseline-shift, writing-mode,
textLength, lengthAdjust, rotate, CSS declarations, masks, patterns or markers.
Every XML element and attribute must be well formed and closed."""


class SlideOutputError(ValueError):
    pass


@dataclass(frozen=True)
class SlideGenerationResult:
    svg_path: Path | None
    title: str
    errors: list[str]
    metrics: dict[str, int]
    diagnostics: list[dict] = field(default_factory=list)


def _public_text(value: str, limit: int = 500) -> str:
    compact = " ".join(value.split())
    redacted = _PUBLIC_SECRET_RE.sub("[redacted]", compact)
    return redacted[:limit]


def extract_outline(design_spec: str, page_count: int, user_input: str) -> list[dict]:
    titles: dict[int, str] = {}
    for line in design_spec.splitlines():
        match = _PAGE_HEADING_RE.match(line)
        if not match:
            continue
        index = int(match.group(1))
        if 1 <= index <= page_count and index not in titles:
            title = _public_text(match.group(2).strip(" *_`#"), limit=160)
            if title:
                titles[index] = title
    if 1 not in titles:
        topic = _public_text(user_input, limit=160)
        if topic:
            titles[1] = topic
    topic = _public_text(user_input, limit=120) or "当前主题"
    briefs = [
        "建立主题背景和目标", "说明现状、关键问题和影响", "拆解核心方法、数据或案例",
        "给出实施路径和协作机制", "总结阶段成果和风险控制", "提出下一步行动和衡量指标",
        "补充落地场景与资源安排", "收束核心结论和决策建议", "补充长期规划与扩展方向",
        "整理附录要点和参考信息", "给出复盘问题和讨论方向", "形成最终行动清单和责任分工",
    ]
    result = []
    used_titles: set[str] = set()
    for index in range(1, page_count + 1):
        candidate = titles.get(index) or f"{index}. {briefs[index - 1]}"
        if candidate in used_titles:
            candidate = f"{index}. {briefs[index - 1]}"
        used_titles.add(candidate)
        result.append({
            "index": index,
            "title": candidate,
            "content_brief": f"围绕{topic}，{briefs[index - 1]}。本页必须使用不同证据和版式。",
        })
    return result


def summarize_design(design_spec: str) -> dict[str, str]:
    return {"preview": _public_text(design_spec, limit=500)}


def extract_single_svg(raw: str) -> str:
    value = raw.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()

    if value.startswith(("{", "[")):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, list) and decoded:
            decoded = decoded[0]
        if isinstance(decoded, dict) and isinstance(decoded.get("svg"), str):
            value = decoded["svg"].strip()

    match = _SVG_RE.search(value)
    if not match:
        raise SlideOutputError("svg_xml_invalid")
    return match.group(0).strip()


async def _default_model_call(system_prompt: str, user_prompt: str) -> str:
    chunks: list[str] = []
    async for chunk in call_glm(system_prompt, user_prompt):
        chunks.append(chunk)
    return "".join(chunks)


async def _default_quality_check(project: Path, _svg_path: Path) -> list[str]:
    """Run the same export-compatibility checker used by final validation."""

    python = os.environ.get("PPT_MASTER_PYTHON", str(_DEFAULT_PPT_PYTHON))
    try:
        result = await run_command(
            [python, str(_QUALITY_CHECKER), str(project)],
            timeout=120,
            cwd=project.parent,
        )
    except CommandTimeoutError:
        return ["svg_quality_check_timeout"]
    except Exception:
        return ["svg_quality_check_error"]
    if result.returncode == 0:
        return []
    output = (result.stdout + b"\n" + result.stderr).decode("utf-8", "replace")
    return _quality_error_codes(output)


def _quality_error_codes(output: str) -> list[str]:
    """Reduce verbose checker output to safe, actionable repair codes."""

    match = _UNSUPPORTED_TEXT_PROPERTY_RE.search(output)
    if match:
        return [f"svg_unsupported_text_property:{match.group(1).lower()}"]
    patterns = (
        (r"unsupported inline style property ['\"]([A-Za-z0-9_-]+)['\"]", "svg_unsupported_style_property"),
        (r"Bake-required visual (?:property|attribute) ['\"]([A-Za-z0-9_-]+)['\"]", "svg_bake_required_property"),
    )
    for pattern, code in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return [f"{code}:{match.group(1).lower()}"]
    lowered = output.lower()
    categories = (
        ("unsupported visual svg element", "svg_unsupported_visual_element"),
        ("malformed inline style", "svg_malformed_inline_style"),
        ("negative letter-spacing", "svg_invalid_letter_spacing"),
        ("forbidden", "svg_forbidden_construct"),
        ("structured svg root is missing", "svg_structure_metadata_missing"),
    )
    for marker, code in categories:
        if marker in lowered:
            return [code]
    return ["svg_quality_invalid"]


def _base_prompt(
    *,
    index: int,
    title: str,
    page_count: int,
    page_format: str,
    design_spec: str,
    user_input: str,
    source_context: str = "",
    content_brief: str = "",
) -> str:
    viewbox = "1280 720" if page_format == "ppt169" else "960 720"
    return (
        f"Render slide {index} of {page_count}.\n"
        f"Title: {title}\n"
        f"Content brief: {content_brief or title}\n"
        f"Format: {page_format}; required viewBox='0 0 {viewbox}'.\n\n"
        f"Design specification:\n{design_spec}\n\n"
        f"Presentation topic:\n{user_input}\n\n"
        + (f"Selected source material:\n{source_context}\n\n" if source_context else "")
        + "Return exactly one safe SVG document."
    )


async def generate_slide(
    *,
    project_dir: Path | str,
    task_id: str,
    index: int,
    title: str,
    content_brief: str = "",
    page_count: int,
    page_format: str,
    design_spec: str,
    user_input: str,
    source_context: str = "",
    workspace_layouts: list[dict] | None = None,
    model_call: Callable[[str, str], Awaitable[str]] | None = None,
    quality_check: Callable[[Path, Path], Awaitable[list[str]]] | None = None,
    max_repair_retries: int = 2,
) -> SlideGenerationResult:
    del task_id  # Reserved for tracing without exposing it to the model.
    project = Path(project_dir)
    call = model_call or _default_model_call
    check_quality = quality_check or _default_quality_check
    metrics = {
        "model_output_count": 0,
        "svg_xml_invalid_count": 0,
        "svg_sanitize_success_count": 0,
        "svg_validation_blocked_count": 0,
        "model_repair_retry_count": 0,
    }

    # Assign layout if workspace_layouts provided (structured mode)
    assigned_layout_id: str | None = None
    if workspace_layouts:
        try:
            assigned_layout_id = assign_layout(
                slide_index=index,
                slide_title=title,
                slide_brief=content_brief,
                page_count=page_count,
                layouts=workspace_layouts,
            )
        except LayoutAssignmentError as exc:
            # Log warning but continue with flat mode
            import logging
            logging.getLogger(__name__).warning(f"Layout assignment failed for slide {index}: {exc}")
    
    base_prompt = _base_prompt(
        index=index,
        title=title,
        content_brief=content_brief,
        page_count=page_count,
        page_format=page_format,
        design_spec=design_spec,
        user_input=user_input,
        source_context=source_context,
    )
    prompt = base_prompt
    last_errors = ["svg_xml_invalid"]
    last_diagnostics: list[dict] = []
    last_output = ""

    for attempt in range(max_repair_retries + 1):
        if attempt:
            metrics["model_repair_retry_count"] += 1
            prompt = (
                f"{base_prompt}\n\n"
                f"Repair the previous output. Blocking error codes: {', '.join(last_errors)}.\n"
                f"Previous output (untrusted):\n{last_output[:20000]}\n\n"
                "Rebuild the incompatible element using plain native geometry and the "
                "strict attribute subset from the system instructions. Do not repeat any "
                "reported property or construct. Return only the corrected SVG."
            )
        try:
            raw = await call(_SINGLE_SLIDE_SYSTEM_PROMPT, prompt)
        except Exception:
            last_errors = ["model_generation_failed"]
            last_output = ""
            continue

        metrics["model_output_count"] += 1
        last_output = raw
        inspection = inspect_model_svg_output(raw, project_root=project)
        svg_text = inspection.get("svg_text")
        last_errors = list(inspection.get("errors") or [])
        last_diagnostics = list(inspection.get("diagnostics") or [])
        if inspection.get("sanitized") and not last_errors:
            metrics["svg_sanitize_success_count"] += 1

        if "svg_xml_invalid" in last_errors:
            metrics["svg_xml_invalid_count"] += 1
        if last_errors:
            metrics["svg_validation_blocked_count"] += 1
            continue

        svg_dir = project / "svg_output"
        svg_dir.mkdir(parents=True, exist_ok=True)
        svg_dir.chmod(0o700)
        destination = svg_dir / f"page_{index:02d}.svg"
        temporary = svg_dir / f".{destination.name}.{uuid.uuid4().hex}.tmp"
        # Deterministic placeholder wiring if a structured layout was assigned.
        # Wiring failure is an explicit slide-generation error; never silently
        # fall back to flat/unwired structured output.
        if assigned_layout_id:
            converter_layout_key = to_converter_layout_key(assigned_layout_id)
            template_basename = converter_layout_key.replace("-", "_")
            template_path = _STRUCTURED_TEMPLATES_DIR / f"{template_basename}.svg"
            try:
                svg_text = wire_placeholders(
                    llm_svg_text=svg_text,
                    layout_template_path=template_path,
                )
            except PlaceholderWiringError as exc:
                last_errors = [f"placeholder_wiring_failed:{exc}"]
                metrics["svg_validation_blocked_count"] += 1
                continue
        temporary.write_text(svg_text, encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, destination)
        try:
            quality_errors = await check_quality(project, destination)
        except Exception:
            quality_errors = ["svg_quality_check_error"]
        if quality_errors:
            destination.unlink(missing_ok=True)
            last_errors = list(dict.fromkeys(quality_errors))
            last_diagnostics = []
            metrics["svg_validation_blocked_count"] += 1
            continue
        return SlideGenerationResult(destination, title, [], metrics, [])

    return SlideGenerationResult(
        None,
        title,
        list(dict.fromkeys(last_errors)),
        metrics,
        last_diagnostics,
    )
