"""Internal draft export; this module does not grant formal issuing rights."""
from io import BytesIO
from docx import Document
from docx.shared import Mm, Pt


def internal_docx(payload: dict) -> bytes:
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin, section.bottom_margin = Mm(37), Mm(35)
    section.left_margin, section.right_margin = Mm(28), Mm(26)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "仿宋", Pt(16)
    section.header.paragraphs[0].text = "未审核 · 内部草稿"
    section.footer.paragraphs[0].text = "仅供内部流转，不作正式发文"
    doc.add_heading(payload["title"], level=0)
    fields = payload.get("fields", {})
    if fields.get("recipient"):
        doc.add_paragraph(fields["recipient"] + "：")
    for line in payload.get("body", "").splitlines():
        if line.strip():
            doc.add_paragraph(line)
    if fields.get("issuer"):
        doc.add_paragraph(fields["issuer"])
    if payload.get("signDate"):
        doc.add_paragraph(payload["signDate"])
    if fields.get("undertaker"):
        doc.add_paragraph("承办：" + fields["undertaker"])
    out = BytesIO()
    doc.save(out)
    return out.getvalue()
