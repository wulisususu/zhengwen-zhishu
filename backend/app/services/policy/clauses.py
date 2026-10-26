"""Clause segmentation for policy text.

Splits by the document's own hierarchy markers — 第X编/章/节/条, 一、, （一）,
1., （1） — never by length. A fixed-size chunker (like the knowledge base's
500-character chunks) cuts articles apart and breaks citation anchors, so it
must not be used for policy text.

Guarantees:
- every clause keeps its full original text (marker included), unmodified;
- paragraphs without a marker are continuation text of the current clause;
- concatenating all clauses in ``sequence`` order reproduces every paragraph;
- when the structure cannot be trusted (no markers at all, numbering out of
  order, extraction flagged unreliable) text is kept and ``needs_review`` set.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN = "零〇一二两三四五六七八九十百千"

# (kind, rank, regex). Lower rank = higher level. Markers only count at the
# start of a paragraph, so "依照本办法第五条" inside a sentence is ignored.
_MARKERS = [
    ("part", 0, re.compile(rf"^(第[{_CN}\d]+编)\s*(.*)$")),
    ("chapter", 1, re.compile(rf"^(第[{_CN}\d]+章)\s*(.*)$")),
    ("section", 2, re.compile(rf"^(第[{_CN}\d]+节)\s*(.*)$")),
    ("article", 3, re.compile(rf"^(第[{_CN}\d]+条)[\s　]*(.*)$")),
    ("cn_item", 4, re.compile(rf"^([{_CN}]+、)\s*(.*)$")),
    ("paren_cn", 5, re.compile(rf"^([（(][{_CN}]+[)）])\s*(.*)$")),
    ("arabic", 6, re.compile(r"^(\d{1,3}[.．、])(?!\d)\s*(.*)$")),
    ("paren_arabic", 7, re.compile(r"^([（(]\d{1,3}[)）])\s*(.*)$")),
]
_HEADING_KINDS = {"part", "chapter", "section"}
_NUMBER_RE = re.compile(rf"[{_CN}]+|\d+")
LONG_CLAUSE_CHARS = 3000


@dataclass
class ClauseDraft:
    sequence: int
    article_number: str | None
    heading: str | None
    content: str
    parent_index: int | None
    level: int
    kind: str
    needs_review: bool
    source_anchor: str


def chinese_number(text: str) -> int | None:
    """Parse 一..九千九百九十九 or ASCII digits; None if not a number."""
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if any(ch not in _CN_DIGITS and ch not in _CN_UNITS for ch in text):
        return None
    total, current = 0, 0
    for ch in text:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
        else:
            unit = _CN_UNITS[ch]
            total += (current or 1) * unit
            current = 0
    return total + current


def _marker_number(label: str) -> int | None:
    match = _NUMBER_RE.search(label)
    return chinese_number(match.group(0)) if match else None


def _match_marker(paragraph: str):
    for kind, rank, regex in _MARKERS:
        m = regex.match(paragraph)
        if m:
            return kind, rank, m.group(1), m.group(2).strip()
    return None


def _paragraphs(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def segment(text: str, *, reliable: bool = True) -> list[ClauseDraft]:
    paragraphs = _paragraphs(text)
    if not paragraphs:
        return []

    matches = [_match_marker(p) for p in paragraphs]
    if not any(matches):
        # No recognisable structure: keep every paragraph, flag all for review.
        return [
            ClauseDraft(i + 1, None, None, p, None, 0, "paragraph", True, f"段落{i + 1}")
            for i, p in enumerate(paragraphs)
        ]

    clauses: list[ClauseDraft] = []
    stack: list[int] = []  # indexes of open ancestors, ordered by rank
    last_number: dict[tuple[int | None, str], int] = {}

    for paragraph, marker in zip(paragraphs, matches):
        if marker is None:
            if clauses:
                clauses[-1].content += "\n" + paragraph
            else:
                clauses.append(ClauseDraft(1, None, "序言", paragraph, None, 0, "preamble", False, "序言"))
            continue

        kind, rank, label, rest = marker
        while stack and clauses[stack[-1]].level >= rank:
            stack.pop()
        parent = stack[-1] if stack else None
        heading = None
        if kind in _HEADING_KINDS or (kind == "cn_item" and rest and len(rest) <= 30 and not rest.endswith(("。", "；", "；"))):
            heading = rest or None

        number = _marker_number(label)
        # 编/章/节/条 are numbered through the whole document; items restart under each parent.
        key = (None, kind) if kind in _HEADING_KINDS or kind == "article" else (parent, kind)
        previous = last_number.get(key)
        out_of_order = number is None or (previous is not None and number != previous + 1) or (previous is None and number not in (None, 1))
        if number is not None:
            last_number[key] = number

        anchor_parts = [clauses[i].article_number for i in stack if clauses[i].article_number] + [label]
        clauses.append(
            ClauseDraft(
                sequence=len(clauses) + 1,
                article_number=label,
                heading=heading,
                content=paragraph,
                parent_index=parent,
                level=rank,
                kind=kind,
                needs_review=out_of_order,
                source_anchor=">".join(anchor_parts),
            )
        )
        stack.append(len(clauses) - 1)

    for clause in clauses:
        if len(clause.content) > LONG_CLAUSE_CHARS or not reliable:
            clause.needs_review = True
    return clauses
