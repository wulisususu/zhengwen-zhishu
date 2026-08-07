"""Deterministic post-process wiring of LLM slide content into layout placeholder skeletons.

Structured mode requires every generated page to structurally mirror its assigned
layout's placeholder <g> contract (same ids/types/idx/bounds/order). Rather than
relying on the LLM to emit that exact markup, this module:
  1. Extracts plain text runs from the LLM's freely-generated SVG (document order).
  2. Takes the layout template's exact placeholder skeleton unchanged.
  3. Substitutes extracted text into each text-type placeholder's carrier element,
     in placeholder order (title, then subtitle/body, ...).
  4. Leaves non-text placeholders (picture/chart) as their template default box.

If the number of extracted text runs does not satisfy the layout's required text
placeholders, this raises PlaceholderWiringError. Callers must not catch this to
silently fall back to flat/unstructured output; the caller decides how to handle
the failure (e.g. abort the slide, or surface it to the workflow as a failure).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


class PlaceholderWiringError(Exception):
    """Raised when LLM output cannot be deterministically wired into a layout's placeholders."""


_TEXT_PLACEHOLDER_TYPES = frozenset({"title", "subtitle", "body"})


def _extract_text_runs(svg_text: str) -> list[str]:
    """Return non-empty text content from every <text> element, in document order."""
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise PlaceholderWiringError(f"LLM SVG output is not well-formed XML: {exc}") from exc

    runs: list[str] = []
    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1]
        if tag != "text":
            continue
        # Join direct text plus any tspan children's text, ignoring markup.
        pieces = [elem.text or ""]
        for child in elem:
            pieces.append(child.text or "")
            pieces.append(child.tail or "")
        pieces.append(elem.tail or "") if False else None  # tail of <text> itself is not content
        combined = "".join(pieces).strip()
        if combined:
            runs.append(combined)
    return runs


def _load_template(template_path: Path) -> str:
    return template_path.read_text(encoding="utf-8")


def _placeholder_order(template_svg: str) -> list[tuple[str, str]]:
    """Return [(placeholder_type, idx)] in document order from a layout template."""
    root = ET.fromstring(template_svg)
    order: list[tuple[str, str]] = []
    for child in list(root):
        placeholder = child.get("data-pptx-placeholder")
        idx = child.get("data-pptx-placeholder-idx")
        if placeholder:
            order.append((placeholder, idx or "0"))
    return order


def wire_placeholders(
    *,
    llm_svg_text: str,
    layout_template_path: Path,
) -> str:
    """
    Build a structurally-compliant slide SVG for the given layout by substituting
    text extracted from llm_svg_text into the layout template's exact placeholder
    skeleton (ids/types/idx/bounds/order all come from the template, unchanged).

    Raises PlaceholderWiringError if llm_svg_text does not contain enough text
    runs to fill every text-type placeholder (title/subtitle/body) declared by
    the layout. Non-text placeholders (picture/chart) keep the template's
    default carrier content untouched.
    """
    template_svg = _load_template(layout_template_path)
    order = _placeholder_order(template_svg)
    text_slots = [(ptype, idx) for ptype, idx in order if ptype in _TEXT_PLACEHOLDER_TYPES]

    text_runs = _extract_text_runs(llm_svg_text)
    if len(text_runs) < len(text_slots):
        raise PlaceholderWiringError(
            f"layout requires {len(text_slots)} text placeholder(s) "
            f"({', '.join(t for t, _ in text_slots)}), but LLM output only "
            f"provided {len(text_runs)} text run(s)"
        )

    result = template_svg
    run_iter = iter(text_runs)
    for ptype, idx in order:
        if ptype not in _TEXT_PLACEHOLDER_TYPES:
            continue
        content = next(run_iter)
        escaped = (
            content.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        # Replace the carrier <text ...>...</text> content for this specific
        # placeholder idx. Match the <g id="slot-..." ... data-pptx-placeholder-idx="{idx}" ...>
        # block's inner carrier text node, scoped narrowly to avoid touching
        # other placeholders with the same tag name.
        pattern = re.compile(
            r'(data-pptx-placeholder-idx="' + re.escape(idx) + r'"[^>]*>\s*'
            r'<text\b[^>]*data-pptx-placeholder-carrier="true"[^>]*>)'
            r'[^<]*'
            r'(</text>)'
        )
        new_result, count = pattern.subn(
            lambda m: m.group(1) + escaped + m.group(2), result, count=1
        )
        if count != 1:
            raise PlaceholderWiringError(
                f"could not locate carrier <text> for placeholder idx={idx} "
                f"in layout template {layout_template_path.name}"
            )
        result = new_result

    return result
