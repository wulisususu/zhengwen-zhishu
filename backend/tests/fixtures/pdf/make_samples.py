"""Generate synthetic policy-style PDFs for the OpenDataLoader spike.

These are NOT gov.cn originals: gov.cn was unreachable from the spike VPS
(egress proxy CONNECT 403). Text is fictional and marked 演示. Replace with
real gov.cn attachments when available (see docs/spike/opendataloader-pdf.md).

Requires reportlab + pillow (not project dependencies):
    python make_samples.py <out_dir> [--perf]

Produces:
    text_3p.pdf      text layer, 3 pages, chapters/articles (STSong-Light CID font)
    table_1p.pdf     one bordered table plus text
    scanned_1p.pdf   image-only page (no text layer), simulates a scan
    corrupt.pdf      truncated PDF bytes
    empty.pdf        0 bytes
    not_pdf.pdf      plain text with a .pdf name
    --perf adds text_10p.pdf, text_50p.pdf (timing samples)
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
TITLE = ParagraphStyle("t", fontName="STSong-Light", fontSize=18, leading=28, alignment=1, spaceAfter=12)
HEAD = ParagraphStyle("h", fontName="STSong-Light", fontSize=14, leading=24, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("b", fontName="STSong-Light", fontSize=12, leading=22, firstLineIndent=24)
CELL = ParagraphStyle("c", fontName="STSong-Light", fontSize=10.5, leading=16)
NOTO = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"

ARTICLE_TEXT = (
    "数据提供部门应当按照政务数据资源目录提供数据，保证数据真实、准确、完整，"
    "并在数据发生变化后及时更新。共享申请提出后，数据提供部门应当在十个工作日内予以答复；"
    "不予共享的，应当说明理由并提供相关依据。"
)
CN = "零一二三四五六七八九十"


def cn_number(n: int) -> str:
    if n >= 100:
        hundreds, rest = divmod(n, 100)
        if rest == 0:
            return CN[hundreds] + "百"
        tail = cn_number(rest)
        return CN[hundreds] + "百" + ("零" + tail if rest < 10 else ("一" + tail if rest < 20 else tail))
    if n <= 10:
        return CN[n] if n < 10 else "十"
    if n < 20:
        return "十" + CN[n - 10]
    tens, ones = divmod(n, 10)
    return CN[tens] + "十" + (CN[ones] if ones else "")


def policy_story(pages: int) -> list:
    story = [Paragraph("示例市政务数据共享管理办法（演示）", TITLE),
             Paragraph("（演示文本，非真实政策，仅用于解析测试）", CELL), Spacer(1, 6 * mm)]
    article = 1
    for page in range(pages):
        story.append(Paragraph(f"第{cn_number(page + 1)}章　第{page + 1}部分规定", HEAD))
        for _ in range(4):
            story.append(Paragraph(f"第{cn_number(article)}条　{ARTICLE_TEXT}", BODY))
            article += 1
        if page < pages - 1:
            story.append(PageBreak())
    return story


def build(path: Path, story: list) -> None:
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=28 * mm, rightMargin=26 * mm, topMargin=37 * mm, bottomMargin=35 * mm,
                      title="示例政策（演示）").build(story)


def table_story() -> list:
    rows = [["序号", "事项名称", "责任单位", "完成时限"],
            ["1", "编制政务数据资源目录", "示例市数据局（演示）", "2025年6月30日"],
            ["2", "完成共享平台安全加固", "示例市网信办（演示）", "2025年9月30日"],
            ["3", "开展数据质量专项检查", "各区政务服务管理部门（演示）", "2025年12月31日"]]
    table = Table([[Paragraph(c, CELL) for c in r] for r in rows], colWidths=[14 * mm, 56 * mm, 50 * mm, 34 * mm])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.8, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE"))]))
    return [Paragraph("关于印发重点任务分工的通知（演示）", TITLE),
            Paragraph("各有关单位：现将重点任务分工表印发给你们，请认真抓好落实。", BODY), Spacer(1, 4 * mm),
            Paragraph("附件：重点任务分工表", HEAD), table, Spacer(1, 6 * mm),
            Paragraph("示例市人民政府办公室（演示）", BODY)]


def scanned_pdf(path: Path) -> None:
    """Render text to a bitmap and embed only the image: no text layer at all."""
    width, height = 1240, 1754  # A4 at 150 dpi
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(NOTO, 44)
    body_font = ImageFont.truetype(NOTO, 30)
    draw.text((width // 2, 220), "示例市公共数据开放办法（演示扫描件）", font=title_font, fill=0, anchor="mm")
    y = 340
    for i in range(1, 7):
        line = f"第{cn_number(i)}条　公共数据开放应当遵循依法有序、安全可控的原则。"
        draw.text((160, y), line, font=body_font, fill=0)
        y += 70
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=70)
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawImage(ImageReader(io.BytesIO(buf.getvalue())), 0, 0, width=A4[0], height=A4[1])
    c.showPage()
    c.save()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--perf", action="store_true")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    build(out / "text_3p.pdf", policy_story(3))
    build(out / "table_1p.pdf", table_story())
    scanned_pdf(out / "scanned_1p.pdf")
    whole = (out / "text_3p.pdf").read_bytes()
    (out / "corrupt.pdf").write_bytes(whole[: len(whole) // 3])
    (out / "empty.pdf").write_bytes(b"")
    (out / "not_pdf.pdf").write_text("这不是 PDF 文件。\n", encoding="utf-8")
    if args.perf:
        build(out / "text_10p.pdf", policy_story(10))
        build(out / "text_50p.pdf", policy_story(50))
    for p in sorted(out.glob("*.pdf")):
        print(f"{p.name}\t{p.stat().st_size} bytes")


if __name__ == "__main__":
    main()
