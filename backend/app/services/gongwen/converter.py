"""Structured 通知 → gongwen-kit component spec (+ text index for anchor mapping).

The spec is plain data: a list of components whose `type` is one of
COMPONENT_TYPES and whose values are strings / lists of strings / ints. The
fixed Node bridge (node/render_notice.js) maps each type to one gongwen-kit
call and validates the spec again. No code is generated or evaluated.

Heading numbers are structural: a typed prefix such as 「一、」 is stripped and
gongwen-kit numbers headings automatically, so the DOCX numbering is always
continuous. Gaps in the typed numbering are reported by rules.check_numbering.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.gongwen.rules import parse_number
from app.services.gongwen.schema import FieldSegment, NoticeDraft, TextSegment

SPEC_VERSION = 1
COMPONENT_TYPES = ("letterhead", "title", "zhusong", "p", "h1", "h2", "h3", "h4",
                   "table", "fujian", "luokuan", "fuzhu", "banji")
# 版心宽 156 mm ≈ 8844 twips (A4 210 − 左 28 − 右 26)
TEXT_WIDTH_TWIPS = 8800
MIN_COL_TWIPS = 900
PLACEHOLDER = "【待补充：{}】"


@dataclass
class IndexEntry:
    anchor: str
    precision: str      # segment | block | none
    section: str
    label: str
    text: str
    is_table: bool = False


_FIELD_NAMES = {"recipient": "主送机关", "issuer": "发文机关", "undertaker": "承办部门"}


def _visible_text(draft: NoticeDraft, block) -> str:
    """Block text for rendering: empty fields show a visible placeholder instead of vanishing."""
    return "".join(
        s.text if isinstance(s, TextSegment)
        else (getattr(draft.fields, s.field).strip() or PLACEHOLDER.format(_FIELD_NAMES[s.field]))
        for s in block.segments
    )


def _strip_number(text: str) -> str:
    parsed = parse_number(text)
    return text[parsed[2]:] if parsed else text


def _table_widths(head: list[str], rows: list[list[str]]) -> list[int]:
    weights = []
    for col in range(len(head)):
        longest = max(len(head[col]), *(len(r[col]) for r in rows))
        weights.append(max(2, min(longest, 20)))
    total = sum(weights)
    widths = [max(MIN_COL_TWIPS, TEXT_WIDTH_TWIPS * w // total) for w in weights]
    overflow = sum(widths) - TEXT_WIDTH_TWIPS
    while overflow > 0:   # shave the widest column until it fits
        i = widths.index(max(widths))
        cut = min(overflow, widths[i] - MIN_COL_TWIPS)
        if cut <= 0:
            break
        widths[i] -= cut
        overflow -= cut
    return widths


def build_spec(draft: NoticeDraft, draft_mark: str | None = None) -> tuple[dict, list[IndexEntry]]:
    fields = draft.fields
    issuer = fields.issuer.strip() or PLACEHOLDER.format("发文机关")
    index: list[IndexEntry] = []
    comps: list[dict] = []

    doc_no = draft.docNumber.text.strip() if draft.docNumber else ""
    if fields.issuer.strip():
        comps.append({"type": "letterhead", "agency": fields.issuer.strip(),
                      "docNo": doc_no or PLACEHOLDER.format("发文字号")})
        if draft.docNumber:
            index.append(IndexEntry(draft.docNumber.id, "segment", "head", "发文字号", doc_no))
    title = draft.title.strip() or PLACEHOLDER.format("标题")
    comps.append({"type": "title", "lines": list(draft.titleLines) if draft.titleLines else [title]})

    recipient_done = False
    attachments: list[str] = []
    label = "开头段"
    for block in draft.blocks:
        text = _visible_text(draft, block)
        section = block.section or "body"
        if block.kind == "recipient":
            if not recipient_done:
                comps.append({"type": "zhusong", "text": text.strip() or PLACEHOLDER.format("主送机关")})
                recipient_done = True
                _index_block(index, draft, block, "head", "主送机关", text)
        elif block.kind.startswith("heading"):
            level = int(block.kind[-1])
            if level == 1:
                label = text.strip() or label
            comps.append({"type": f"h{level}", "text": _strip_number(text).strip()})
            _index_block(index, draft, block, section, label, _strip_number(text))
        elif block.kind == "paragraph":
            if text.strip():
                comps.append({"type": "p", "text": text})
                _index_block(index, draft, block, section, label, text)
        elif block.kind == "table":
            t = block.table
            comps.append({"type": "table", "caption": t.caption, "head": list(t.head),
                          "rows": [list(r) for r in t.rows], "widths": _table_widths(t.head, t.rows)})
            index.append(IndexEntry(block.id, "block", section, t.caption or label,
                                    "\n".join([t.caption, *t.head, *(c for r in t.rows for c in r)]), is_table=True))
        elif block.kind == "attachment":
            name = text.strip()
            for prefix in ("附件：", "附件:"):
                name = name.removeprefix(prefix)
            if name:
                attachments.append(name)
                _index_block(index, draft, block, block.section or "attach", "附件说明", name)
        elif block.kind == "signature":
            index.append(IndexEntry(block.id, "block", block.section or "sign", "落款",
                                    f"{issuer}\n{draft.signDate}"))
    if not recipient_done:
        recipient = fields.recipient.strip() or PLACEHOLDER.format("主送机关")
        comps.insert(2 if fields.issuer.strip() else 1, {"type": "zhusong", "text": recipient})
    if attachments:
        comps.append({"type": "fujian", "items": attachments})
    comps.append({"type": "luokuan", "unit": issuer,
                  "date": draft.signDate.strip() or PLACEHOLDER.format("成文日期")})
    if draft.note.strip():
        comps.append({"type": "fuzhu", "text": draft.note.strip()})
    banji = draft.banji
    if (banji and banji.printer.strip() and banji.printDate.strip()) or draft_mark is not None:
        comps.append({"type": "banji", "copyTo": [c for c in banji.copyTo if c.strip()] if banji else [],
                      "issuer": banji.printer.strip() if banji and banji.printer.strip() else PLACEHOLDER.format("印发机关"),
                      "date": banji.printDate.strip() if banji and banji.printDate.strip() else PLACEHOLDER.format("印发日期")})
        index.append(IndexEntry("", "none", "banji", "版记",
                                "\n".join([*banji.copyTo, banji.printer, banji.printDate]) if banji else ""))
    if not any(b.kind == "signature" for b in draft.blocks):
        index.append(IndexEntry("", "none", "sign", "落款", f"{issuer}\n{draft.signDate}"))
    index.append(IndexEntry("", "none", "head", "标题", title))
    spec = {"version": SPEC_VERSION, "docType": "notice", "title": title,
            "draftMark": draft_mark, "components": comps}
    return spec, index


def _index_block(index: list[IndexEntry], draft: NoticeDraft, block, section: str, label: str, text: str) -> None:
    for seg in block.segments:
        if isinstance(seg, TextSegment) and seg.id:
            index.append(IndexEntry(seg.id, "segment", section, label, seg.text))
        elif isinstance(seg, FieldSegment):
            value = getattr(draft.fields, seg.field).strip() or PLACEHOLDER.format(_FIELD_NAMES[seg.field])
            index.append(IndexEntry(seg.id, "segment", section, label, value))
    index.append(IndexEntry(block.id, "block", section, label, text))
