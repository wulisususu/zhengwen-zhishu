"""Structured SVG/PPTX validation for the Stage A pipeline."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import BadZipFile, ZipFile


_SLIDE_RE = re.compile(r"^ppt/slides/slide[0-9]+\.xml$")
_REQUIRED_MEMBERS = {
    "[Content_Types].xml": "pptx_content_types_missing",
    "_rels/.rels": "pptx_package_relationships_missing",
    "ppt/presentation.xml": "pptx_presentation_missing",
    "ppt/_rels/presentation.xml.rels": "pptx_presentation_relationships_missing",
}


def _unique(values: list[str] | None) -> list[str]:
    return list(dict.fromkeys(values or []))


def build_validation_result(
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    blocking_errors: list[str] | None = None,
) -> dict:
    warning_list = _unique(warnings)
    error_list = _unique(errors)
    blocking_list = _unique(blocking_errors)
    return {
        "passed": not error_list and not blocking_list,
        "warnings": warning_list,
        "errors": error_list,
        "blocking_errors": blocking_list,
    }


def count_pptx_slides(path: Path | str) -> int:
    """Read the slide part count from the generated OOXML package."""
    candidate = Path(path)
    try:
        with ZipFile(candidate, "r") as archive:
            return len([name for name in archive.namelist() if _SLIDE_RE.match(name)])
    except (BadZipFile, OSError, RuntimeError):
        return 0


def merge_validation_results(*results: dict | None) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    blocking_errors: list[str] = []
    for result in results:
        if not result:
            continue
        warnings.extend(result.get("warnings") or [])
        errors.extend(result.get("errors") or [])
        blocking_errors.extend(result.get("blocking_errors") or [])
    return build_validation_result(warnings, errors, blocking_errors)


def validate_pptx(path: Path | str, expected_pages: int) -> dict:
    candidate = Path(path)
    blocking: list[str] = []
    if candidate.is_symlink():
        return build_validation_result(blocking_errors=["pptx_symlink_forbidden"])
    if not candidate.exists() or not candidate.is_file() or candidate.stat().st_size <= 0:
        return build_validation_result(blocking_errors=["pptx_file_missing"])
    if candidate.suffix.lower() != ".pptx":
        return build_validation_result(blocking_errors=["pptx_extension_invalid"])

    try:
        with ZipFile(candidate, "r") as archive:
            if archive.testzip() is not None:
                return build_validation_result(blocking_errors=["pptx_zip_integrity_failed"])
            names = set(archive.namelist())
            for member, code in _REQUIRED_MEMBERS.items():
                if member not in names:
                    blocking.append(code)
            slides = sorted(name for name in names if _SLIDE_RE.match(name))
            if not slides:
                blocking.append("pptx_slides_missing")
            if len(slides) != expected_pages:
                blocking.append("pptx_page_count_mismatch")

            xml_members = [member for member in _REQUIRED_MEMBERS if member in names]
            xml_members.extend(slides)
            for member in xml_members:
                data = archive.read(member)
                lowered = data.lower()
                if b"<!doctype" in lowered or b"<!entity" in lowered:
                    blocking.append("pptx_xml_entity_forbidden")
                    continue
                try:
                    ET.fromstring(data)
                except ET.ParseError:
                    blocking.append("pptx_xml_invalid")
    except (BadZipFile, OSError, RuntimeError):
        return build_validation_result(blocking_errors=["pptx_zip_invalid"])

    return build_validation_result(blocking_errors=blocking)
