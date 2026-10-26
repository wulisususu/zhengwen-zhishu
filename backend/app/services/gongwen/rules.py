"""Own deterministic review rules (InNet_box layer).

Covers what gongwen-kit does not check (S1: 0/5): missing elements, numbering
continuity, stated counts vs listed items, sign date completeness, and whether
cited policies are linked. Policy validity is NOT judged here: the policy
library is a separate module; until it answers, every reference is reported as
unverified and client-provided statuses are ignored.

Each finding anchors to an id that exists in the draft (segment or block id),
or to nothing (anchor "", precision "none"). Ids are never invented.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field

from app.services.gongwen.schema import Block, FieldSegment, NoticeDraft, TextSegment

# ── numbering ────────────────────────────────────────────────────────────
_CN = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
       "六": 6, "七": 7, "八": 8, "九": 9}


def cn_to_int(text: str) -> int | None:
    """一..九十九 (also 两); arabic digits pass through."""
    if text.isdigit():
        return int(text)
    if not text or any(ch not in _CN and ch != "十" for ch in text):
        return None
    if "十" not in text:
        return _CN[text] if len(text) == 1 else None
    tens, _, ones = text.partition("十")
    if len(tens) > 1 or len(ones) > 1:
        return None
    return (_CN[tens] if tens else 1) * 10 + (_CN[ones] if ones else 0)


# Prefix level: 1「一、」 2「（一）」 3「1.」 4「（1）」 (GB/T 9704 7.3.3); half-width parens accepted.
_LEVEL_PATTERNS = [
    (1, re.compile(r"^([一二三四五六七八九十]{1,3})、\s*")),
    (2, re.compile(r"^[（(]([一二三四五六七八九十]{1,3})[）)]\s*")),
    (3, re.compile(r"^(\d{1,2})[.．](?!\d)\s*")),
    (4, re.compile(r"^[（(](\d{1,2})[）)]\s*")),
]
_LEVEL_FORM = {1: "{}、", 2: "（{}）", 3: "{}.", 4: "（{}）"}
_CN_DIGIT = "零一二三四五六七八九"


def int_to_cn(n: int) -> str:
    if n < 10:
        return _CN_DIGIT[n]
    tens, ones = divmod(n, 10)
    return ("" if tens == 1 else _CN_DIGIT[tens]) + "十" + (_CN_DIGIT[ones] if ones else "")


def format_number(level: int, n: int) -> str:
    return _LEVEL_FORM[level].format(int_to_cn(n) if level <= 2 else n)


def parse_number(text: str) -> tuple[int, int, int] | None:
    """(prefix level, number, prefix length) of a leading 层次序数, or None."""
    for level, pattern in _LEVEL_PATTERNS:
        m = pattern.match(text)
        if m:
            n = cn_to_int(m.group(1))
            if n:
                return level, n, m.end()
    return None


# ── finding model ────────────────────────────────────────────────────────
@dataclass
class Finding:
    code: str
    description: str
    anchor: str = ""
    precision: str = "none"          # segment | block | none
    section: str = "document"
    location_label: str = "全文"
    extra: dict = field(default_factory=dict)


@dataclass
class _Item:
    block: Block
    kind: str          # heading | paragraph | table | other
    level: int         # heading level 1..4, else 0
    text: str
    section: str
    label: str


def _items(draft: NoticeDraft) -> list[_Item]:
    items: list[_Item] = []
    label = "开头段"
    for block in draft.blocks:
        text = draft.block_text(block)
        if block.kind.startswith("heading"):
            level = int(block.kind[-1])
            if level == 1:
                label = text.strip() or label
            items.append(_Item(block, "heading", level, text, block.section or "body", label))
        elif block.kind == "paragraph":
            items.append(_Item(block, "paragraph", 0, text, block.section or "body", label))
        elif block.kind == "table":
            items.append(_Item(block, "table", 0, "", block.section or "body", block.table.caption or label))
        else:
            items.append(_Item(block, "other", 0, text, block.section, label))
    return items


def _segment_anchor(draft: NoticeDraft, field_name: str, fallback_kind: str) -> tuple[str, str, str]:
    for block in draft.blocks:
        for seg in block.segments:
            if isinstance(seg, FieldSegment) and seg.field == field_name:
                return seg.id, "segment", block.section or fallback_kind
    for block in draft.blocks:
        if block.kind == fallback_kind:
            return block.id, "block", block.section or fallback_kind
    return "", "none", "head" if fallback_kind == "recipient" else "sign"


def _signature_anchor(draft: NoticeDraft) -> tuple[str, str]:
    for block in draft.blocks:
        if block.kind == "signature":
            return block.id, "block"
    return "", "none"


# 版心 156 mm ÷ 二号字 22 pt（约 7.76 mm）≈ 20 字
TITLE_CHARS_PER_LINE = 20


# ── 1 应有公文要素 ────────────────────────────────────────────────────────
def check_elements(draft: NoticeDraft) -> list[Finding]:
    out: list[Finding] = []
    title = draft.title.strip()
    if not title:
        out.append(Finding("ELEM_TITLE", "公文标题为空。通知的标题应写明发文机关、事由和文种。",
                           section="head", location_label="标题"))
    elif not title.endswith("通知"):
        out.append(Finding("TITLE_DOC_TYPE", f"标题「{title[:30]}」未以文种「通知」结尾。",
                           section="head", location_label="标题"))
    if len(title) > TITLE_CHARS_PER_LINE and not draft.titleLines:
        out.append(Finding("TITLE_LINE_BREAK",
                           f"标题 {len(title)} 字，超过一行（二号字约 {TITLE_CHARS_PER_LINE} 字），未指定回行位置，"
                           "Word 会按宽度断行。GB/T 9704 7.3.1 要求回行时词意完整，请在 titleLines 中按意群分行。",
                           section="head", location_label="标题"))

    if not draft.fields.issuer.strip():
        anchor, precision, section = _segment_anchor(draft, "issuer", "signature")
        out.append(Finding("ELEM_ISSUER", "发文机关为空：版头的发文机关标志与落款署名都无法生成。",
                           anchor, precision, section, "落款"))
    if not draft.fields.recipient.strip():
        anchor, precision, section = _segment_anchor(draft, "recipient", "recipient")
        out.append(Finding("ELEM_RECIPIENT", "通知须写明主送机关，当前为空。",
                           anchor, precision, section, "主送机关"))
    undertaker_refs = [s for b in draft.blocks for s in b.segments
                       if isinstance(s, FieldSegment) and s.field == "undertaker"]
    if undertaker_refs and not draft.fields.undertaker.strip():
        anchor, precision, section = _segment_anchor(draft, "undertaker", "paragraph")
        out.append(Finding("ELEM_UNDERTAKER", "正文引用了承办部门，但该字段为空。",
                           anchor, precision, section, "承办部门"))

    doc_no = draft.docNumber
    if doc_no is None or not doc_no.text.strip():
        out.append(Finding("ELEM_DOCNO", "发文字号为空（格式应为「机关代字〔年份〕序号号」）。",
                           doc_no.id if doc_no else "", "segment" if doc_no else "none", "head", "发文字号"))

    body = [b for b in draft.blocks if b.kind in ("paragraph", "table")
            or (b.kind.startswith("heading") and draft.block_text(b).strip())]
    if not any(b.kind == "table" or draft.block_text(b).strip() for b in body):
        out.append(Finding("ELEM_BODY", "没有正文内容。", section="body", location_label="正文"))

    sign_anchor, sign_precision = _signature_anchor(draft)
    if not draft.signDate.strip():
        out.append(Finding("ELEM_SIGN_DATE", "成文日期为空。", sign_anchor, sign_precision, "sign", "成文日期"))
    else:
        out.extend(_check_date(draft.signDate, "SIGN_DATE_FORMAT", "SIGN_DATE_INVALID", "成文日期",
                               sign_anchor, sign_precision, "sign"))

    banji = draft.banji
    missing = [] if banji else ["印发机关", "印发日期"]
    if banji:
        missing = [name for name, value in (("印发机关", banji.printer), ("印发日期", banji.printDate))
                   if not value.strip()]
    if missing:
        out.append(Finding("ELEM_BANJI", f"版记缺少{'、'.join(missing)}（GB/T 9704 7.4）。",
                           section="banji", location_label="版记"))
    if banji and banji.printDate.strip():
        out.extend(f for f in _check_date(banji.printDate, "BANJI_DATE_FORMAT", "BANJI_DATE_FORMAT",
                                          "印发日期", "", "none", "banji"))
    return out


# 年月日都要有；阿拉伯数字或〇式汉字都算「能识别」，写法问题（虚位、汉字）交给 gongwen-kit。
_DATE_RE = re.compile(
    r"^\s*(\d{4}|[〇零一二三四五六七八九]{4})\s*年\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*月"
    r"\s*(\d{1,2}|[一二三四五六七八九十]{1,4})\s*日\s*$")


def _check_date(value: str, format_code: str, invalid_code: str, label: str,
                anchor: str, precision: str, section: str) -> list[Finding]:
    m = _DATE_RE.match(value)
    if not m:
        return [Finding(format_code, f"{label}「{value}」不是完整的「×年×月×日」写法"
                        "（GB/T 9704 7.3.5.3：用阿拉伯数字将年、月、日标全）。",
                        anchor, precision, section, label)]
    year_text = m.group(1)
    year = int(year_text) if year_text.isdigit() else int("".join(str(_CN[c]) for c in year_text))
    month, day = cn_to_int(m.group(2)), cn_to_int(m.group(3))
    if not month or not day or not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(year, month)[1]:
        return [Finding(invalid_code, f"{label}「{value}」不是有效日期。", anchor, precision, section, label)]
    return []


# ── 2 层次序号连续 ────────────────────────────────────────────────────────
_INLINE_MARK = re.compile(r"(?:^|[，。；：、\s])([一二三四五六七八九十]{1,2})是")


def check_numbering(draft: NoticeDraft) -> list[Finding]:
    out: list[Finding] = []
    counters = [0, 0, 0, 0, 0]              # structural heading counters by level
    para_seq: dict[tuple[str, int], int] = {}  # (parent heading id, marker level) -> last number
    parent = ""
    for item in _items(draft):
        block = item.block
        if item.kind == "heading":
            level = item.level
            counters[level] += 1
            for deeper in range(level + 1, 5):
                counters[deeper] = 0
            parent = block.id
            para_seq = {}   # paragraph markers restart under each heading
            parsed = parse_number(item.text)
            if not parsed:
                continue
            p_level, n, _ = parsed
            if p_level != level:
                out.append(Finding("NUMBERING_LEVEL",
                                   f"「{item.text[:20]}」用的是第 {p_level} 层序数「{format_number(p_level, n)}」，"
                                   f"但处在第 {level} 层标题位置（第 {level} 层应为「{format_number(level, counters[level])}」）。",
                                   block.id, "block", item.section, item.label))
                continue
            if n != counters[level]:
                out.append(Finding("NUMBERING_GAP",
                                   f"「{item.text[:20]}」序号不连续：此处应为「{format_number(level, counters[level])}」，"
                                   f"实为「{format_number(level, n)}」。正式生成时层次序号按结构自动编排。",
                                   block.id, "block", item.section, item.label,
                                   {"expected": counters[level], "actual": n}))
                counters[level] = n   # resync so only the gap point is reported
        elif item.kind == "paragraph":
            parsed = parse_number(item.text)
            if parsed:
                p_level, n, _ = parsed
                key = (parent, p_level)
                expected = para_seq.get(key, 0) + 1
                if n != expected:
                    out.append(Finding("NUMBERING_GAP",
                                       f"段首序号不连续：此处应为「{format_number(p_level, expected)}」，"
                                       f"实为「{format_number(p_level, n)}」。",
                                       block.id, "block", item.section, item.label,
                                       {"expected": expected, "actual": n}))
                para_seq[key] = n
                for deeper in range(p_level + 1, 5):
                    para_seq.pop((parent, deeper), None)
            marks = [cn_to_int(m.group(1)) for m in _INLINE_MARK.finditer(item.text)]
            if len(marks) >= 2 and marks[0] == 1:
                for i, n in enumerate(marks[1:], start=2):
                    if n != i:
                        out.append(Finding("NUMBERING_GAP",
                                           f"段内「一是、二是」式列举不连续：第 {i} 处应为「{int_to_cn(i)}是」，"
                                           f"实为「{int_to_cn(n)}是」。",
                                           block.id, "block", item.section, item.label))
                        break
    return out


# ── 3 「共 N 项」与实际列项 ───────────────────────────────────────────────
_COUNT_RE = re.compile(
    r"(共计?|以下|如下|下列|包括)\s*([一二两三四五六七八九十]{1,3}|\d{1,2})\s*"
    r"(个方面|个问题|项工作|项任务|方面|项|条|点|类|件|个)")


def check_counts(draft: NoticeDraft) -> list[Finding]:
    out: list[Finding] = []
    items = _items(draft)
    context_level = 0
    for idx, item in enumerate(items):
        if item.kind == "heading":
            context_level = item.level
            continue
        if item.kind != "paragraph":
            continue
        for m in _COUNT_RE.finditer(item.text):
            want = cn_to_int(m.group(2))
            rest = item.text[m.end():]
            colon = re.match(r"[^。；;]*?[：:]", rest)
            if not want or not (colon or m.group(1) in ("以下", "如下", "下列")):
                continue   # 「共 3 项任务已完成」之类不是列举引导句
            phrase = m.group(0).replace(" ", "")
            tail = rest[colon.end():].strip().rstrip("。") if colon else ""
            got, code, how = _count_inline(tail) if tail else _count_following(items, idx, context_level)
            if got is not None and got != want:
                out.append(Finding(code, f"「{phrase}」与{how} {got} 项不一致。",
                                   item.block.id, "block", item.section, item.label,
                                   {"stated": want, "listed": got}))
    return out


def _count_inline(tail: str) -> tuple[int | None, str, str]:
    marks = [cn_to_int(m.group(1)) for m in _INLINE_MARK.finditer(tail)]
    if len(marks) >= 2 and marks[0] == 1:
        return len(marks), "COUNT_MISMATCH", "其后「一是、二是」列出的"
    enum = [m for m in re.finditer(r"[（(]([一二三四五六七八九十]{1,3}|\d{1,2})[）)]", tail)]
    if len(enum) >= 2:
        return len(enum), "COUNT_MISMATCH", "其后序号列出的"
    parts = [p for p in re.split(r"[；;]", tail) if p.strip()]
    if len(parts) >= 2:
        return len(parts), "COUNT_MISMATCH_INLINE", "其后分号分隔的"
    return None, "", ""


def _count_following(items: list[_Item], idx: int, context_level: int) -> tuple[int | None, str, str]:
    following = items[idx + 1:]
    if not following:
        return None, "", ""
    first = following[0]
    if first.kind == "heading" and first.level > context_level:
        level = first.level
        n = 0
        for it in following:
            if it.kind == "heading" and it.level < level:
                break
            if it.kind == "heading" and it.level == level:
                n += 1
        return n, "COUNT_MISMATCH", f"其后列出的第 {level} 层标题"
    first_num = parse_number(first.text) if first.kind == "paragraph" else None
    if first_num:
        marker_level = first_num[0]
        n = 0
        for it in following:
            if it.kind == "heading" or it.kind == "table":
                break
            parsed = parse_number(it.text) if it.kind == "paragraph" else None
            if parsed and parsed[0] == marker_level:
                n += 1
            elif parsed and parsed[0] < marker_level:
                break
        return n, "COUNT_MISMATCH", "其后带序号列出的"
    return None, "", ""


# ── 4 政策引用 ────────────────────────────────────────────────────────────
_CITE_RE = re.compile(r"《([^《》]{2,80})》")


def _norm(title: str) -> str:
    return re.sub(r"\s+", "", title)


def check_policy_refs(draft: NoticeDraft) -> tuple[list[Finding], dict]:
    """Existence/linking only. Validity is left to the policy library (not connected)."""
    out: list[Finding] = []
    refs = {_norm(r.title): r for r in draft.policyRefs}
    cited: dict[str, tuple[str, str, str, str]] = {}
    for item in _items(draft):
        block = item.block
        for seg in block.segments:
            if not isinstance(seg, TextSegment):
                continue
            for m in _CITE_RE.finditer(seg.text):
                name = _norm(m.group(1))
                anchor, precision = (seg.id, "segment") if seg.id else (block.id, "block")
                cited.setdefault(name, (anchor, precision, item.section, item.label))
    linked = set()
    for name, (anchor, precision, section, label) in cited.items():
        match = next((k for k in refs if k == name or k in name or name in k), None)
        if match is None:
            out.append(Finding("POLICY_REF_UNLINKED",
                               f"正文引用《{name}》，未在政策依据中关联，无法核验其是否现行有效。",
                               anchor, precision, section, label))
        else:
            linked.add(match)
    for key, ref in refs.items():
        if key not in linked:
            out.append(Finding("POLICY_REF_UNCITED", f"政策依据《{ref.title}》未在正文中引用。",
                               section="policy", location_label="政策依据", extra={"refId": ref.id}))
    verification = {
        "status": "not_available",
        "message": "政策库尚未接入，政策有效性（现行/废止）未经后端核验；前端提供的状态不作为核验结果。",
        "refs": [{"id": r.id, "title": r.title, "verified": False} for r in draft.policyRefs],
        "citedTitles": sorted(cited),
    }
    if draft.policyRefs or cited:
        anchor, precision, section, label = next(iter(cited.values()), ("", "none", "policy", "政策依据"))
        count = len(set(refs) | set(cited))
        out.append(Finding("POLICY_REF_UNVERIFIED",
                           f"本文涉及 {count} 项政策依据，政策库尚未接入，其有效性未经核验。",
                           anchor, precision, section, label))
    return out, verification


def run_all(draft: NoticeDraft) -> tuple[list[Finding], dict]:
    findings = check_elements(draft) + check_numbering(draft) + check_counts(draft)
    policy_findings, verification = check_policy_refs(draft)
    return findings + policy_findings, verification
