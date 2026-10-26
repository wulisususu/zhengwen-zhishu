"""政策原文解析：逐页提取 → 条款切分 → 页码与字符区间 → 校验值。

为什么不用通用文档切片：
    政策解读需要「第X条」这一级的定位。切成一堆 500 字 chunk 后，
    既说不清引用的是哪一条，也回不到原文页码，更无法做原文高亮。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}

#: 「第X条」，X 支持汉字数字与阿拉伯数字
_RE_CLAUSE = re.compile(r"^[\s\u3000]*(第[〇零一二三四五六七八九十百千两\d]{1,8}条)")
#: 「第X章」/「第X节」
_RE_CHAPTER = re.compile(r"^[\s\u3000]*(第[〇零一二三四五六七八九十百千两\d]{1,8}[章节])[\s\u3000]*(\S.{0,40})?$")
#: 兜底：一、二、三、
_RE_CN_ITEM = re.compile(r"^[\s\u3000]*([一二三四五六七八九十]{1,3})[、.．]")
#: 规划/方案类文件在「一、」之下常用「（一）（二）」，需要细分才能精确引用
_RE_SUB_ITEM = re.compile(r"^[\s\u3000]*([（(][一二三四五六七八九十百\d]{1,4}[）)])")
#: 单独成行的页码（PDF 提取常见），会被误粘进条款正文
_RE_PAGE_NO = re.compile(r"^\s*[-—–\s]*\d{1,3}[-—–\s]*$")
#: 条款编号规范化用的中文数字
_CN_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


@dataclass
class Page:
    page_no: int
    text: str


@dataclass
class ClauseSpan:
    seq: int
    clause_no: str
    chapter: str
    heading: str
    content: str
    page: int
    char_start: int
    char_end: int
    checksum: str


@dataclass
class ParseResult:
    pages: list[Page]
    full_text: str
    clauses: list[ClauseSpan]
    page_count: int
    char_count: int
    checksum: str
    suggested_title: str = ""
    warnings: list[str] = field(default_factory=list)
    ocr_used: bool = False


# ---------------------------------------------------------------- 基础工具

def checksum(text: str) -> str:
    """原文校验值：去空白后取 sha256 前 32 位，用于判断原文是否被改动。"""
    normalized = re.sub(r"\s+", "", text or "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def normalize_search_text(text: str) -> str:
    """检索用归一化：去标点与空白，只保留中文、字母、数字。"""
    return re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", (text or "").lower())


def cn_to_int(token: str) -> int | None:
    """把「十六」「二十」「一百零三」转成整数，用于条款排序与连续性检查。"""
    token = (token or "").strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    total = 0
    section = 0
    number = 0
    for ch in token:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if number == 0:
                number = 1
            section += number * unit
            number = 0
        else:
            return None
    return section + number


# ---------------------------------------------------------------- OCR

#: OCR 渲染精度：200dpi 对 5 号字（约 10.5pt）识别率与速度较平衡
OCR_DPI = 200
#: 行内合并阈值：行距小于「中位行高 × 该系数」视为同一段落
PARA_GAP_RATIO = 1.55

_ocr_engine = None


def ocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine = RapidOCR()
    return _ocr_engine


def _ocr_lines(image_bytes: bytes) -> list[tuple[float, float, float, float, str]]:
    """对单页图像做 OCR，返回 (x0, y0, x1, y1, 文本) 的行列表。"""
    engine = _get_ocr_engine()
    result, _ = engine(image_bytes)
    lines: list[tuple[float, float, float, float, str]] = []
    for item in result or []:
        try:
            box, text = item[0], str(item[1] or "")
        except (IndexError, TypeError):
            continue
        text = text.strip()
        if not text:
            continue
        xs = [float(pt[0]) for pt in box]
        ys = [float(pt[1]) for pt in box]
        lines.append((min(xs), min(ys), max(xs), max(ys), text))
    return lines


def _looks_like_noise(text: str) -> bool:
    """页眉页脚类噪声：纯日期、纯时间、URL、页码、浏览器标题栏。"""
    t = text.strip()
    if len(t) <= 2:
        return True
    if re.fullmatch(r"[\d/.\-:\s]+", t):
        return True
    if t.lower().startswith(("http://", "https://", "www.")):
        return True
    if re.fullmatch(r"[-—\s]*\d+[-—\s]*", t):
        return True
    return False


def _lines_to_paragraphs(lines: list[tuple[float, float, float, float, str]]) -> str:
    """把 OCR 的「视觉行」合并成段落。

    政策原文的按条切分依赖「第X条」独占行首，若保留逐行换行，
    段落会被打碎成十几个碎片，条款正文也就读不通了。

    判断段落边界用三件事：行距明显大于正文行距、行首出现编号、
    左右不重叠（说明跨了栏或跨了侧边栏）。
    """
    rows = [ln for ln in lines if not _looks_like_noise(ln[4])]
    if not rows:
        return ""
    rows.sort(key=lambda r: (round(r[1], 1), r[0]))

    # 正文行距：取相邻行 y 差的众数中位数，比用行高更稳
    deltas = []
    for prev_row, row in zip(rows, rows[1:]):
        d = row[1] - prev_row[1]
        if 0 < d < 200:
            deltas.append(d)
    deltas.sort()
    pitch = deltas[len(deltas) // 2] if deltas else 0.0

    marker = re.compile(
        r"^(第[〇零一二三四五六七八九十百千两\d]{1,8}[条章节]"
        r"|[一二三四五六七八九十]{1,3}[、.．]"
        r"|[（(][一二三四五六七八九十\d]{1,3}[）)])"
    )

    paragraphs: list[str] = []
    buf: list[str] = []
    prev: tuple[float, float, float, float, str] | None = None

    for row in rows:
        x0, y0, x1, _, text = row
        if prev is None:
            buf = [text]
        else:
            dy = y0 - prev[1]
            overlap = min(x1, prev[2]) - max(x0, prev[0])
            width = min(x1 - x0, prev[2] - prev[0]) or 1.0
            same_column = overlap > width * 0.3
            new_para = (
                not same_column
                or bool(marker.match(text))
                or (pitch and dy > pitch * 1.55)
            )
            if new_para:
                paragraphs.append("".join(buf))
                buf = [text]
            else:
                buf.append(text)
        prev = row

    if buf:
        paragraphs.append("".join(buf))
    return "\n".join(p for p in paragraphs if p.strip())


def ocr_pdf(path: str | Path) -> tuple[list[Page], int]:
    """整本 PDF 逐页 OCR。返回 (pages, 成功率百分比)。"""
    import pymupdf

    with pymupdf.open(str(path)) as doc:
        pages: list[Page] = []
        for idx, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=OCR_DPI)
            text = _lines_to_paragraphs(_ocr_lines(pix.tobytes("png")))
            pages.append(Page(page_no=idx, text=text))
    covered = sum(1 for pg in pages if pg.text.strip())
    ratio = int(covered / len(pages) * 100) if pages else 0
    return pages, ratio


# ---------------------------------------------------------------- 文本提取

def extract_pages(path: str | Path, *, allow_ocr: bool = True) -> tuple[list[Page], dict]:
    """按页提取文本。PDF 保留真实页码；DOCX/TXT 无页概念，统一记为第 1 页。

    返回 (pages, meta)。meta 说明是否走了 OCR —— 走 OCR 的原文必须提示人工核对，
    因为条款编号、数字、日期这类字符最容易被识别错。
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"暂不支持的文件类型：{suffix}（支持 {', '.join(sorted(SUPPORTED_SUFFIXES))}）")

    if suffix == ".pdf":
        import pymupdf

        pages: list[Page] = []
        with pymupdf.open(str(p)) as doc:
            for idx, page in enumerate(doc, start=1):
                text = page.get_text("text") or ""
                pages.append(Page(page_no=idx, text=text))

        if any(pg.text.strip() for pg in pages):
            return pages, {"ocr_used": False}

        # 没有文字层：扫描件 / 网页截图打印件
        if not allow_ocr:
            raise ValueError("PDF 未提取到文字（扫描件），且已禁用 OCR")
        if not ocr_available():
            raise ValueError(
                "PDF 没有文字层（扫描件或截图打印），本机未安装 OCR 组件。"
                "请执行 pip install rapidocr-onnxruntime，或改用「粘贴正文」入库"
            )
        pages, ratio = ocr_pdf(p)
        if not any(pg.text.strip() for pg in pages):
            raise ValueError("PDF 无文字层，OCR 也未识别出内容；请改用「粘贴正文」入库")
        return pages, {"ocr_used": True, "ocr_page_ratio": ratio}

    if suffix == ".docx":
        from docx import Document

        doc = Document(str(p))
        blocks = [para.text for para in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    blocks.append(" | ".join(cells))
        return [Page(page_no=1, text="\n".join(blocks))], {"ocr_used": False}

    text = p.read_text(encoding="utf-8", errors="replace")
    return [Page(page_no=1, text=text)], {"ocr_used": False}


# ---------------------------------------------------------------- 条款切分

def _build_offset_map(pages: list[Page]) -> tuple[str, list[tuple[int, int]]]:
    """把多页拼成全文，同时记录「字符偏移 → 页码」的换算表。"""
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for page in pages:
        offsets.append((cursor, page.page_no))
        parts.append(page.text)
        cursor += len(page.text) + 1  # 页间补一个换行
    return "\n".join(parts), offsets


def _page_of(offset: int, offsets: list[tuple[int, int]]) -> int:
    page_no = 1
    for start, no in offsets:
        if offset >= start:
            page_no = no
        else:
            break
    return page_no


def _heading_of(content: str, clause_no: str) -> str:
    body = content
    if body.startswith(clause_no):
        body = body[len(clause_no):]
    body = body.strip(" 　:：、")
    first = re.split(r"[。；\n]", body, maxsplit=1)[0].strip()
    return first[:40]


def split_clauses(full_text: str, offsets: list[tuple[int, int]]) -> tuple[list[ClauseSpan], list[str]]:
    """按「第X条」切分；识别不到时退回章节/条目切分。"""
    warnings: list[str] = []
    lines = full_text.splitlines(keepends=True)

    # 计算每行起始偏移
    line_offsets: list[int] = []
    acc = 0
    for line in lines:
        line_offsets.append(acc)
        acc += len(line)

    marks: list[tuple[int, str, int]] = []   # (偏移, 条款标题, 行号)
    chapter = ""
    chapter_at: dict[int, str] = {}

    for idx, raw in enumerate(lines):
        line = raw.strip("\r\n")
        if not line.strip():
            continue
        m_ch = _RE_CHAPTER.match(line)
        if m_ch:
            chapter = (m_ch.group(1) + (m_ch.group(2) or "")).strip()
            chapter_at[idx] = chapter
            continue
        m = _RE_CLAUSE.match(line)
        if m:
            marks.append((line_offsets[idx], m.group(1), idx))

    item_fallback = False
    if len(marks) < 2:
        # 兜底：按「一、二、」条目切
        item_fallback = True
        marks = []
        chapter = ""
        for idx, raw in enumerate(lines):
            line = raw.strip("\r\n")
            if not line.strip():
                continue
            m_ch = _RE_CHAPTER.match(line)
            if m_ch:
                chapter = (m_ch.group(1) + (m_ch.group(2) or "")).strip()
                chapter_at[idx] = chapter
                continue
            m = _RE_CN_ITEM.match(line)
            if m:
                marks.append((line_offsets[idx], m.group(1) + "、", idx))
        if marks:
            warnings.append("未识别到「第X条」编号，已按「一、二、」条目切分")

    if not marks:
        # 最后兜底：按空行分块
        chunks = [c for c in re.split(r"\n\s*\n", full_text) if c.strip()]
        marks = []
        cursor = 0
        for i, chunk in enumerate(chunks, start=1):
            pos = full_text.find(chunk, cursor)
            if pos < 0:
                pos = cursor
            marks.append((pos, f"第{i}段", 0))
            cursor = pos + len(chunk)

    clauses: list[ClauseSpan] = []
    for seq, (start, clause_no, line_idx) in enumerate(marks):
        end = marks[seq + 1][0] if seq + 1 < len(marks) else len(full_text)
        raw_content = full_text[start:end]
        # 章节标题与页码行不属于条款正文，剔除后再作为条款原文
        kept = [ln for ln in raw_content.splitlines()
                if not _RE_CHAPTER.match(ln.strip()) and not _RE_PAGE_NO.match(ln.strip())]
        content = "\n".join(kept).strip()
        if not content:
            continue
        current_chapter = ""
        for idx in sorted(chapter_at):
            if idx <= line_idx:
                current_chapter = chapter_at[idx]
        clauses.append(ClauseSpan(
            seq=seq,
            clause_no=clause_no,
            chapter=current_chapter,
            heading=_heading_of(content, clause_no),
            content=content,
            page=_page_of(start, offsets),
            char_start=start,
            char_end=end,
            checksum=checksum(content),
        ))

    if item_fallback and clauses:
        clauses = _refine_sub_items(clauses, full_text, offsets)

    return clauses, warnings


def _guess_title(full_text: str, first_clause_at: int) -> str:
    """从原文首部推断标题。

    扫描件/截图件首部常混入日期、URL、站点名，直接取第一行会把「2026/10/26 10:12」
    当成标题。这里优先取包含公文文种词的那一行。
    """
    head = full_text[: (first_clause_at if first_clause_at > 0 else 400)]
    candidates = [ln.strip() for ln in head.splitlines() if ln.strip()]
    doc_kind = re.compile(r"(规划|办法|通知|意见|条例|规定|决定|方案|细则|公告|通报|批复|规则|纲要)")
    for line in candidates:
        if _looks_like_noise(line) or len(line) < 5:
            continue
        if doc_kind.search(line):
            return line[:120]
    for line in candidates:
        if not _looks_like_noise(line) and len(line) >= 5:
            return line[:120]
    return ""


def _refine_sub_items(clauses: list[ClauseSpan], full_text: str,
                      offsets: list[tuple[int, int]]) -> list[ClauseSpan]:
    """把「一、」这一级的大条，按「（一）（二）」拆成更小的引用单元。

    规划类文件没有「第X条」，一整节两千字。若按「一、」入库，问答引用就会
    连着一大段原文，既定位不准也无法高亮。拆到「（一）」后，
    引用可以写成「三、（一）」，与公文里的引用习惯一致。
    """
    refined: list[ClauseSpan] = []
    for clause in clauses:
        segment = full_text[clause.char_start:clause.char_end]
        marks: list[tuple[int, str]] = []
        cursor = 0
        for line in segment.splitlines(keepends=True):
            m = _RE_SUB_ITEM.match(line)
            if m:
                marks.append((clause.char_start + cursor, m.group(1)))
            cursor += len(line)

        if len(marks) < 2:
            refined.append(clause)
            continue

        # 第一个（一）之前的引导语（如「总体要求」的指导方针）单独成条
        lead = full_text[clause.char_start:marks[0][0]].strip()
        if len(lead) >= 20:
            refined.append(ClauseSpan(
                seq=len(refined), clause_no=clause.clause_no, chapter=clause.chapter,
                heading=_heading_of(lead, clause.clause_no), content=lead,
                page=clause.page, char_start=clause.char_start, char_end=marks[0][0],
                checksum=checksum(lead),
            ))

        for i, (start, label) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else clause.char_end
            raw = full_text[start:end]
            kept = [ln for ln in raw.splitlines()
                    if not _RE_CHAPTER.match(ln.strip()) and not _RE_PAGE_NO.match(ln.strip())]
            content = "\n".join(kept).strip()
            if not content:
                continue
            label_no = f"{clause.clause_no}{label}"
            refined.append(ClauseSpan(
                seq=len(refined),
                clause_no=label_no,
                chapter=clause.heading or clause.chapter,
                heading=_heading_of(content, label),
                content=content,
                page=_page_of(start, offsets),
                char_start=start,
                char_end=end,
                checksum=checksum(content),
            ))
    return refined


def parse_text(text: str) -> ParseResult:
    """直接解析粘贴进来的正文（不经过文件）。

    政务场景里很多政策只提供网页或扫描件，粘贴正文是最可靠的入库方式。
    """
    body = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not body.strip():
        raise ValueError("正文为空")
    pages = [Page(page_no=1, text=body)]
    full_text, offsets = _build_offset_map(pages)
    clauses, warnings = split_clauses(full_text, offsets)
    if not clauses:
        warnings.append("未切分出任何条款，请检查原文结构")
    return ParseResult(
        pages=pages,
        full_text=full_text,
        clauses=clauses,
        page_count=1,
        char_count=len(full_text),
        checksum=checksum(full_text),
        suggested_title=_guess_title(full_text, clauses[0].char_start if clauses else 0),
        warnings=warnings,
    )


def parse_policy(path: str | Path, *, allow_ocr: bool = True) -> ParseResult:
    """完整解析：提取 → 切分 → 汇总。"""
    pages, meta = extract_pages(path, allow_ocr=allow_ocr)
    full_text, offsets = _build_offset_map(pages)
    clauses, warnings = split_clauses(full_text, offsets)
    ocr_used = bool(meta.get("ocr_used"))

    if ocr_used:
        warnings.append(
            "原文无文字层，已自动 OCR 识别"
            + (f"（{meta.get('ocr_page_ratio')}% 页面有文字）" if meta.get("ocr_page_ratio") else "")
            + "；条款编号、金额、日期请人工核对后再作为正式依据"
        )
    if not clauses:
        warnings.append("未切分出任何条款，请检查原文结构")
    expected = [cn_to_int(c.clause_no.replace("第", "").replace("条", "")) for c in clauses]
    numbers = [n for n in expected if n]
    if len(numbers) >= 3 and len(set(numbers)) != len(numbers):
        warnings.append("条款编号存在重复，请核对原文")

    return ParseResult(
        pages=pages,
        full_text=full_text,
        clauses=clauses,
        page_count=len(pages),
        char_count=len(full_text),
        checksum=checksum(full_text),
        suggested_title=_guess_title(full_text, clauses[0].char_start if clauses else 0),
        warnings=warnings,
        ocr_used=ocr_used,
    )
