"""Fail-closed security checks for untrusted generated SVG content."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit


_BARE_AMPERSAND_RE = re.compile(r"&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9._:-]*;)")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SVG_ROOT_RE = re.compile(r"<svg\b[\s\S]*?</svg>", re.IGNORECASE)
_SVG_START_RE = re.compile(r"<svg\b", re.IGNORECASE)
_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_XML_DECLARATION_RE = re.compile(r"<\?xml[\s\S]*?\?>", re.IGNORECASE)
_RESOURCE_ATTRIBUTES = {"href", "src"}
_MAX_SVG_BYTES = 5 * 1024 * 1024


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].lower()


def _append_once(errors: list[str], code: str) -> None:
    if code not in errors:
        errors.append(code)


def _line_column_details(text: str, line_number: int, column_number: int) -> tuple[int, int, str]:
    lines = text.splitlines() or [text]
    safe_line = max(1, min(line_number, len(lines)))
    line_text = lines[safe_line - 1]
    safe_column = max(1, min(column_number, len(line_text) + 1))
    start = max(0, safe_column - 41)
    end = min(len(line_text), safe_column + 39)
    snippet = line_text[start:end].strip()
    return safe_line, safe_column, snippet


def _truncated_diagnostic(svg_text: str) -> dict:
    lines = svg_text.splitlines() or [svg_text]
    line_number = len(lines)
    column_number = len(lines[-1]) + 1
    line_number, column_number, snippet = _line_column_details(svg_text, line_number, column_number)
    return {
        "category": "truncated_output",
        "message": "Missing closing </svg> tag",
        "line": line_number,
        "column": column_number,
        "snippet": snippet,
    }


def _parse_error_diagnostic(svg_text: str, error: ET.ParseError) -> dict:
    line_number, column_number = getattr(error, "position", (1, 0))
    line_number, column_number, snippet = _line_column_details(
        svg_text,
        int(line_number or 1),
        int(column_number or 0) + 1,
    )
    message = str(error)
    lowered = message.lower()
    if "no element found" in lowered:
        category = "truncated_output"
    elif "mismatched tag" in lowered or "unclosed token" in lowered:
        category = "tag_not_closed"
    elif "invalid token" in lowered and _BARE_AMPERSAND_RE.search(svg_text):
        category = "unescaped_entity"
    elif "xml or text declaration not at start of entity" in lowered:
        category = "xml_declaration_misplaced"
    elif "junk after document element" in lowered:
        category = "extra_text_after_svg"
    else:
        category = "xml_not_well_formed"
    return {
        "category": category,
        "message": message,
        "line": line_number,
        "column": column_number,
        "snippet": snippet,
    }


def inspect_model_svg_output(
    raw_text: str,
    *,
    project_root: Path,
    registered_resources: set[Path] | None = None,
) -> dict:
    """Extract, repair, parse, and security-check one model SVG response."""

    value = (raw_text or "").strip()
    repairs: list[str] = []
    diagnostics: list[dict] = []

    if "```" in value:
        stripped_lines: list[str] = []
        removed_fence = False
        for line in value.splitlines():
            if line.strip().startswith("```"):
                removed_fence = True
                continue
            stripped_lines.append(line)
        if removed_fence:
            value = "\n".join(stripped_lines).strip()
            repairs.append("markdown_fence_removed")

    if value.startswith(("{", "[")):
        try:
            decoded = json.loads(value)
        except Exception:
            decoded = None
        if isinstance(decoded, list) and decoded:
            decoded = decoded[0]
            repairs.append("json_wrapper_extracted")
        if isinstance(decoded, dict) and isinstance(decoded.get("svg"), str):
            value = decoded["svg"].strip()

    match = _SVG_ROOT_RE.search(value)
    if match:
        prefix = value[: match.start()].strip()
        suffix = value[match.end() :].strip()
        if prefix or suffix:
            repairs.append("outer_text_removed")
        svg_text = match.group(0).strip()
    else:
        start = _SVG_START_RE.search(value)
        if start:
            if value[: start.start()].strip():
                repairs.append("outer_text_removed")
            svg_text = value[start.start() :].strip()
            diagnostics.append(_truncated_diagnostic(svg_text))
            return {
                "svg_text": None,
                "errors": ["svg_xml_invalid"],
                "diagnostics": diagnostics,
                "sanitized": bool(repairs),
                "repairs": list(dict.fromkeys(repairs)),
            }
        return {
            "svg_text": None,
            "errors": ["svg_xml_invalid"],
            "diagnostics": [{
                "category": "svg_root_missing",
                "message": "No <svg> root element found",
                "line": 1,
                "column": 1,
                "snippet": value[:80].strip(),
            }],
            "sanitized": bool(repairs),
            "repairs": list(dict.fromkeys(repairs)),
        }

    declarations = _XML_DECLARATION_RE.findall(svg_text)
    if len(declarations) > 1:
        first = declarations[0]
        svg_text = first + _XML_DECLARATION_RE.sub("", svg_text)
        repairs.append("repeated_xml_declaration_removed")
    elif len(declarations) == 1 and not svg_text.lstrip().startswith(declarations[0]):
        svg_text = _XML_DECLARATION_RE.sub("", svg_text)
        repairs.append("xml_declaration_repositioned")

    if _CONTROL_CHAR_RE.search(svg_text):
        svg_text = _CONTROL_CHAR_RE.sub("", svg_text)
        repairs.append("illegal_control_chars_removed")
    if _BARE_AMPERSAND_RE.search(svg_text):
        svg_text = _BARE_AMPERSAND_RE.sub("&amp;", svg_text)
        repairs.append("xml_entity_escaped")

    try:
        ET.fromstring(svg_text)
    except ET.ParseError as error:
        diagnostics.append(_parse_error_diagnostic(svg_text, error))
        return {
            "svg_text": None,
            "errors": ["svg_xml_invalid"],
            "diagnostics": diagnostics,
            "sanitized": bool(repairs),
            "repairs": list(dict.fromkeys(repairs)),
        }

    errors = validate_svg_text(svg_text, project_root=project_root, registered_resources=registered_resources)
    return {
        "svg_text": None if errors else svg_text,
        "errors": errors,
        "diagnostics": diagnostics,
        "sanitized": bool(repairs),
        "repairs": list(dict.fromkeys(repairs)),
    }


def _resource_error(
    value: str,
    project_root: Path,
    registered_resources: set[Path],
) -> str | None:
    resource = value.strip().strip("'\"")
    if not resource or resource.startswith("#"):
        return None

    if resource.startswith(("/", "\\", "//")) or _WINDOWS_ABSOLUTE_RE.match(resource):
        return "svg_absolute_resource_forbidden"
    parsed = urlsplit(resource)
    if parsed.scheme:
        return "svg_external_resource_forbidden"

    normalized = resource.replace("\\", "/")
    if ".." in normalized.split("/"):
        return "svg_resource_traversal_forbidden"

    root = project_root.resolve()
    candidate = (root / normalized).resolve(strict=False)
    if not candidate.is_relative_to(root):
        return "svg_resource_traversal_forbidden"
    if candidate not in registered_resources:
        return "svg_unregistered_resource_forbidden"
    if not candidate.exists() or not candidate.is_file() or candidate.is_symlink():
        return "svg_resource_invalid"
    return None


def validate_svg_text(
    svg_text: str,
    project_root: Path,
    registered_resources: set[Path] | None = None,
) -> list[str]:
    """Return stable blocking error codes for unsafe SVG content."""

    errors: list[str] = []
    registered = {Path(path).resolve() for path in (registered_resources or set())}
    lowered = svg_text.lower()

    if "<!doctype" in lowered:
        _append_once(errors, "svg_dtd_forbidden")
    if "<!entity" in lowered:
        _append_once(errors, "svg_entity_forbidden")
    if "<?xml-stylesheet" in lowered or re.search(r"@import\s+", lowered):
        _append_once(errors, "svg_external_resource_forbidden")
    if len(svg_text.encode("utf-8", errors="replace")) > _MAX_SVG_BYTES:
        _append_once(errors, "svg_too_large")
    if errors:
        return errors

    try:
        root_element = ET.fromstring(svg_text)
    except ET.ParseError:
        return ["svg_xml_invalid"]

    for element in root_element.iter():
        tag = _local_name(element.tag)
        if tag == "script":
            _append_once(errors, "svg_script_forbidden")
        elif tag == "foreignobject":
            _append_once(errors, "svg_foreign_object_forbidden")
        elif tag == "use":
            _append_once(errors, "svg_use_forbidden")

        for raw_name, raw_value in element.attrib.items():
            name = _local_name(raw_name)
            value = str(raw_value)
            if name.startswith("on"):
                _append_once(errors, "svg_event_handler_forbidden")
            if "javascript:" in value.lower():
                _append_once(errors, "svg_script_forbidden")
            if name in _RESOURCE_ATTRIBUTES:
                code = _resource_error(value, project_root, registered)
                if code:
                    _append_once(errors, code)
            for _, resource in _URL_RE.findall(value):
                code = _resource_error(resource, project_root, registered)
                if code:
                    _append_once(errors, code)

        if element.text:
            for _, resource in _URL_RE.findall(element.text):
                code = _resource_error(resource, project_root, registered)
                if code:
                    _append_once(errors, code)

    return errors


def validate_svg_directory(
    project_dir: Path | str,
    registered_resources: set[Path] | None = None,
) -> list[str]:
    """Validate every generated SVG without following symlinked inputs."""

    project = Path(project_dir)
    svg_dir = project / "svg_output"
    if not project.exists() or not svg_dir.exists() or not svg_dir.is_dir():
        return ["svg_directory_missing"]
    if project.is_symlink() or svg_dir.is_symlink():
        return ["svg_symlink_forbidden"]

    errors: list[str] = []
    svg_files = sorted(svg_dir.glob("*.svg"))
    if not svg_files:
        return ["svg_files_missing"]

    for svg_path in svg_files:
        if svg_path.is_symlink():
            _append_once(errors, "svg_symlink_forbidden")
            continue
        try:
            text = svg_path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError):
            _append_once(errors, "svg_file_unreadable")
            continue
        for code in validate_svg_text(text, project, registered_resources):
            _append_once(errors, code)
    return errors
