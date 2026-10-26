"""按 GB/T 9704-2012《党政机关公文格式》渲染 DOCX。

版式全部由代码控制，不依赖模型：
    页面 A4 / 上 37mm 下 35mm 左 28mm 右 26mm
    发文机关标志（红头）：小标宋、红色
    发文字号：3 号仿宋、居中；上行文右侧标注签发人
    红色分隔线：与版心等宽
    标题：2 号小标宋、居中
    主送机关：3 号仿宋、左侧顶格
    正文：3 号仿宋、首行缩进 2 字符、固定行距 28.8 磅
    一级标题「一、」黑体；二级「（一）」楷体；三级「1.」仿宋
    署名右空 2 字、成文日期右空 4 字
    版记：4 号仿宋，抄送 / 印发机关 / 印发日期
    页码：4 号宋体，单页右空 1 字、双页左空 1 字
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from .schema import (
    FONT_BODY,
    FONT_DISPLAY,
    FONT_H1,
    FONT_H2,
    FONT_PAGE_NO,
    LINE_SPACING_PT,
    MARGIN_BOTTOM_MM,
    MARGIN_LEFT_MM,
    MARGIN_RIGHT_MM,
    MARGIN_TOP_MM,
    PAGE_HEIGHT_MM,
    PAGE_WIDTH_MM,
    SIZE_ER,
    SIZE_SAN,
    SIZE_SI,
    GongwenDoc,
    is_attachment_line,
)

RED = RGBColor(0xE6, 0x00, 0x00)
BLACK = RGBColor(0x00, 0x00, 0x00)

#: 版心宽度 156mm，用于制表位
TEXT_WIDTH_MM = PAGE_WIDTH_MM - MARGIN_LEFT_MM - MARGIN_RIGHT_MM


# ---------------------------------------------------------------- 底层工具

def _set_run_font(run, font_name: str, size_pt: float, bold: bool = False,
                  color: RGBColor | None = None) -> None:
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    run.font.name = font_name
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rFonts.set(qn(attr), font_name)


def _set_indent_chars(paragraph, first=None, left=None, right=None) -> None:
    """按「字符」设置缩进（Word 的 *Chars 属性），同时写入磅值兜底。"""
    pPr = paragraph._p.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        pPr.insert_element_before(
            ind, "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap",
            "w:jc", "w:textDirection", "w:textAlignment", "w:outlineLvl", "w:rPr",
        )
    if first is not None:
        ind.set(qn("w:firstLineChars"), str(int(first * 100)))
        ind.set(qn("w:firstLine"), str(int(first * SIZE_SAN * 20)))
    if left is not None:
        ind.set(qn("w:leftChars"), str(int(left * 100)))
        ind.set(qn("w:left"), str(int(left * SIZE_SAN * 20)))
    if right is not None:
        ind.set(qn("w:rightChars"), str(int(right * 100)))
        ind.set(qn("w:right"), str(int(right * SIZE_SAN * 20)))


def _add_paragraph(doc, text: str = "", *, font: str = FONT_BODY, size: float = SIZE_SAN,
                   bold: bool = False, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                   color: RGBColor | None = None,
                   first_line_indent: float = 0, left_indent: float = 0,
                   right_indent: float = 0,
                   space_before: float = 0, space_after: float = 0,
                   line_spacing: float = LINE_SPACING_PT):
    p = doc.add_paragraph()
    p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(line_spacing)
    if first_line_indent or left_indent or right_indent:
        _set_indent_chars(p, first=first_line_indent or None,
                          left=left_indent or None, right=right_indent or None)
    if text:
        run = p.add_run(text)
        _set_run_font(run, font, size, bold=bold, color=color)
    else:
        run = p.add_run("")
        _set_run_font(run, font, 1, color=color)
    return p


def _add_border(paragraph, edge: str = "bottom", sz: int = 12,
                color: str = "E60000", space: int = 1) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = pPr.find(qn("w:pBdr"))
    if pBdr is None:
        pBdr = OxmlElement("w:pBdr")
        pPr.insert_element_before(
            pBdr, "w:shd", "w:tabs", "w:spacing", "w:ind", "w:jc", "w:rPr",
        )
    el = OxmlElement(f"w:{edge}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(sz))
    el.set(qn("w:space"), str(space))
    el.set(qn("w:color"), color)
    pBdr.append(el)


def _add_page_field(paragraph, font: str = FONT_PAGE_NO, size: float = SIZE_SI) -> None:
    run = paragraph.add_run()
    _set_run_font(run, font, size)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for node in (begin, instr, sep, text, end):
        run._r.append(node)


def _fill_footer(footer, align, indent_chars: float, side: str) -> None:
    para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    para.alignment = align
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.space_after = Pt(0)
    _set_indent_chars(para, **{side: indent_chars})
    run = para.add_run("— ")
    _set_run_font(run, FONT_PAGE_NO, SIZE_SI)
    _add_page_field(para)
    run2 = para.add_run(" —")
    _set_run_font(run2, FONT_PAGE_NO, SIZE_SI)


# ---------------------------------------------------------------- 文档骨架

def _setup_section(doc) -> None:
    sec = doc.sections[0]
    sec.page_width = Mm(PAGE_WIDTH_MM)
    sec.page_height = Mm(PAGE_HEIGHT_MM)
    sec.top_margin = Mm(MARGIN_TOP_MM)
    sec.bottom_margin = Mm(MARGIN_BOTTOM_MM)
    sec.left_margin = Mm(MARGIN_LEFT_MM)
    sec.right_margin = Mm(MARGIN_RIGHT_MM)
    sec.header_distance = Mm(15)
    sec.footer_distance = Mm(17.5)


def _setup_default_style(doc) -> None:
    style = doc.styles["Normal"]
    style.font.size = Pt(SIZE_SAN)
    style.font.name = FONT_BODY
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rFonts.set(qn(attr), FONT_BODY)
    pf = style.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(LINE_SPACING_PT)


def _setup_page_numbers(doc) -> None:
    try:
        doc.settings.odd_and_even_pages_header_footer = True
    except Exception:
        pass
    sec = doc.sections[0]
    _fill_footer(sec.footer, WD_ALIGN_PARAGRAPH.RIGHT, 1, "right")
    try:
        _fill_footer(sec.even_page_footer, WD_ALIGN_PARAGRAPH.LEFT, 1, "left")
    except Exception:
        pass


# ---------------------------------------------------------------- 各版式区块

def _add_head(doc, gw: GongwenDoc) -> None:
    """份号 / 密级 / 紧急程度 / 红头 / 发文字号 / 红色分隔线。"""
    top_space = 0
    if gw.copy_no:
        p = _add_paragraph(doc, gw.copy_no, font=FONT_H1, size=SIZE_SAN,
                           align=WD_ALIGN_PARAGRAPH.LEFT)
        _set_indent_chars(p, left=0)
        top_space = 0

    if gw.secret_level:
        _add_paragraph(doc, gw.secret_level, font=FONT_H1, size=SIZE_SAN,
                       align=WD_ALIGN_PARAGRAPH.LEFT)

    if gw.urgency and gw.urgency != "普通":
        _add_paragraph(doc, gw.urgency, font=FONT_H1, size=SIZE_SAN,
                       align=WD_ALIGN_PARAGRAPH.LEFT)

    if gw.issuer_org:
        if gw.doc_type == "纪要":
            display = gw.issuer_org if gw.issuer_org.endswith(("纪要", "文件")) else gw.issuer_org + "纪要"
        else:
            display = gw.issuer_org if gw.issuer_org.endswith("文件") else gw.issuer_org + "文件"
        _add_paragraph(doc, display, font=FONT_DISPLAY, size=26,
                       align=WD_ALIGN_PARAGRAPH.CENTER, color=RED,
                       space_before=36 if not top_space else 24,
                       space_after=6, line_spacing=36)

    if gw.doc_number or (gw.signer_name and gw.doc_type in ("请示", "报告")):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pf = p.paragraph_format
        pf.space_before = Pt(6)
        pf.space_after = Pt(6)
        pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        pf.line_spacing = Pt(LINE_SPACING_PT)
        if gw.signer_name:
            # 上行文：发文字号居左空一字，签发人居右空一字
            pf.tab_stops.add_tab_stop(Mm(TEXT_WIDTH_MM), WD_TAB_ALIGNMENT.RIGHT)
            run = p.add_run(gw.doc_number or "")
            _set_run_font(run, FONT_BODY, SIZE_SAN)
            run = p.add_run("\t签发人：" + gw.signer_name)
            _set_run_font(run, FONT_BODY, SIZE_SAN)
            _set_indent_chars(p, left=1)
        else:
            run = p.add_run(gw.doc_number)
            _set_run_font(run, FONT_BODY, SIZE_SAN)

    # 红色分隔线
    line = doc.add_paragraph()
    line.paragraph_format.space_before = Pt(2)
    line.paragraph_format.space_after = Pt(0)
    line.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    line.paragraph_format.line_spacing = Pt(1)
    _add_border(line, "bottom", sz=12, color="E60000", space=1)


def _add_title(doc, gw: GongwenDoc) -> None:
    if not gw.title:
        return
    _add_paragraph(doc, gw.title, font=FONT_DISPLAY, size=SIZE_ER,
                   align=WD_ALIGN_PARAGRAPH.CENTER,
                   space_before=LINE_SPACING_PT * 2, space_after=0,
                   line_spacing=LINE_SPACING_PT * 1.35)


def _add_recipients(doc, gw: GongwenDoc) -> None:
    if not gw.recipients:
        return
    text = "、".join(gw.recipients) + "："
    _add_paragraph(doc, text, font=FONT_BODY, size=SIZE_SAN,
                   align=WD_ALIGN_PARAGRAPH.LEFT,
                   space_before=LINE_SPACING_PT)


def _add_body(doc, gw: GongwenDoc) -> None:
    for para in gw.body:
        if para.level == 1:
            _add_paragraph(doc, para.text, font=FONT_H1, size=SIZE_SAN,
                           first_line_indent=2)
        elif para.level == 2:
            _add_paragraph(doc, para.text, font=FONT_H2, size=SIZE_SAN,
                           first_line_indent=2)
        else:
            _add_paragraph(doc, para.text, font=FONT_BODY, size=SIZE_SAN,
                           first_line_indent=2)


def _add_attachments(doc, gw: GongwenDoc) -> None:
    if not gw.attachments:
        return
    if any(is_attachment_line(p.text) for p in gw.body):
        return  # 正文里已经写了附件说明，避免重复
    names = gw.attachments
    if len(names) == 1:
        _add_paragraph(doc, "附件：" + names[0], font=FONT_BODY, size=SIZE_SAN,
                       align=WD_ALIGN_PARAGRAPH.LEFT, left_indent=2,
                       space_before=LINE_SPACING_PT)
        return
    for idx, name in enumerate(names):
        prefix = "附件：" if idx == 0 else ""
        text = f"{prefix}{idx + 1}. {name}"
        _add_paragraph(doc, text, font=FONT_BODY, size=SIZE_SAN,
                       align=WD_ALIGN_PARAGRAPH.LEFT,
                       left_indent=2 if idx == 0 else 7,
                       space_before=LINE_SPACING_PT if idx == 0 else 0)


def _add_signature(doc, gw: GongwenDoc) -> None:
    if gw.signer_org:
        _add_paragraph(doc, gw.signer_org, font=FONT_BODY, size=SIZE_SAN,
                       align=WD_ALIGN_PARAGRAPH.RIGHT, right_indent=2,
                       space_before=LINE_SPACING_PT)
    if gw.sign_date:
        _add_paragraph(doc, gw.sign_date, font=FONT_BODY, size=SIZE_SAN,
                       align=WD_ALIGN_PARAGRAPH.RIGHT, right_indent=4)


def _add_note(doc, gw: GongwenDoc) -> None:
    if not gw.note:
        return
    text = gw.note if gw.note.startswith("（") else f"（{gw.note}）"
    _add_paragraph(doc, text, font=FONT_BODY, size=SIZE_SAN,
                   align=WD_ALIGN_PARAGRAPH.LEFT, left_indent=2,
                   space_before=LINE_SPACING_PT)


def _add_record(doc, gw: GongwenDoc) -> None:
    """版记：抄送机关 / 印发机关和印发日期。"""
    if not gw.cc and not (gw.print_org or gw.print_date):
        return

    sep = doc.add_paragraph()
    sep.paragraph_format.space_before = Pt(LINE_SPACING_PT * 2)
    sep.paragraph_format.space_after = Pt(0)
    sep.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    sep.paragraph_format.line_spacing = Pt(1)
    _add_border(sep, "bottom", sz=12, color="000000", space=1)

    if gw.cc:
        _add_paragraph(doc, "抄送：" + "、".join(gw.cc) + "。", font=FONT_BODY,
                       size=SIZE_SI, align=WD_ALIGN_PARAGRAPH.LEFT, left_indent=1,
                       line_spacing=SIZE_SI * 1.6)

    if gw.print_org or gw.print_date:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        pf = p.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        pf.line_spacing = Pt(SIZE_SI * 1.6)
        pf.tab_stops.add_tab_stop(Mm(TEXT_WIDTH_MM), WD_TAB_ALIGNMENT.RIGHT)
        _set_indent_chars(p, left=1, right=1)
        run = p.add_run(gw.print_org or "")
        _set_run_font(run, FONT_BODY, SIZE_SI)
        run = p.add_run("\t" + (gw.print_date or ""))
        _set_run_font(run, FONT_BODY, SIZE_SI)

    tail = doc.add_paragraph()
    tail.paragraph_format.space_before = Pt(0)
    tail.paragraph_format.space_after = Pt(0)
    tail.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    tail.paragraph_format.line_spacing = Pt(1)
    _add_border(tail, "bottom", sz=12, color="000000", space=1)


# ---------------------------------------------------------------- 对外入口

def render(gw: GongwenDoc, output_path: str | Path) -> Path:
    """把 IR 渲染成符合 GB/T 9704-2012 版式的 .docx。"""
    doc = Document()
    _setup_section(doc)
    _setup_default_style(doc)
    _setup_page_numbers(doc)

    _add_head(doc, gw)
    _add_title(doc, gw)
    _add_recipients(doc, gw)
    _add_body(doc, gw)
    _add_attachments(doc, gw)
    _add_signature(doc, gw)
    _add_note(doc, gw)
    _add_record(doc, gw)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


def render_bytes(gw: GongwenDoc) -> bytes:
    """渲染到内存，供 HTTP 直接返回。"""
    import io

    doc = Document()
    _setup_section(doc)
    _setup_default_style(doc)
    _setup_page_numbers(doc)
    _add_head(doc, gw)
    _add_title(doc, gw)
    _add_recipients(doc, gw)
    _add_body(doc, gw)
    _add_attachments(doc, gw)
    _add_signature(doc, gw)
    _add_note(doc, gw)
    _add_record(doc, gw)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
