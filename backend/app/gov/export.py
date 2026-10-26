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
    if payload.get("urgency"):
        doc.add_paragraph(payload["urgency"])
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
    if payload.get("policyRefs"):
        doc.add_heading("政策依据（引用记录，须人工核验）", level=1)
        labels = {"current": "现行", "abolished": "已废止", "unverified": "未核验"}
        for ref in payload["policyRefs"]:
            doc.add_paragraph(f"《{ref['title']}》 {ref['clause']} · 第 {ref.get('version') or '未知'} 版 · {labels[ref['status']]}")
            if ref.get("statusNote"):
                doc.add_paragraph("核验提示：" + ref["statusNote"])
            if ref.get("excerpt"):
                doc.add_paragraph(ref["excerpt"])
            doc.add_paragraph("来源：" + ref["sourceUrl"])
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def notice_docx(draft, payload: dict) -> bytes:
    """Render the saved notice with the fixed kit bridge and provenance appendix."""
    import tempfile
    from pathlib import Path
    from fastapi import HTTPException
    from app.services.gongwen.review import render_notice
    from app.services.gongwen.settings import load_settings
    from app.services.gongwen.runner import GongwenToolError
    with tempfile.TemporaryDirectory(prefix="gov-notice-export-") as tmp:
        target = Path(tmp) / "draft.docx"
        try:
            render_notice(draft, target, load_settings(), internal_draft=True)
        except GongwenToolError as exc:
            raise HTTPException(503, "通知生成失败：" + exc.message) from None
        doc = Document(target)
    if payload.get("urgency"):
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        paragraph = doc.paragraphs[0].insert_paragraph_before()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        run = paragraph.add_run(payload["urgency"])
        run.font.name, run.font.size = "黑体", Pt(16)
    _append_policy_appendix(doc, payload.get("policyRefs"))
    # The visible header marks every page as an internal draft. Detailed review
    # findings stay in the workbench; a trailing audit paragraph pushes a short
    # notice onto an otherwise empty page after the bottom-anchored banji.
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def _append_policy_appendix(doc, refs) -> None:
    if not refs:
        return
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    appendix_start = len(doc.paragraphs)
    doc.add_page_break()
    doc.add_paragraph("政策依据与审校记录（内部附件）")
    labels = {"current": "现行", "abolished": "已废止", "unverified": "未核验"}
    for ref in refs:
        doc.add_paragraph(f"《{ref['title']}》 {ref['clause']} · 第 {ref.get('version') or '未知'} 版 · {labels[ref['status']]}")
        if ref.get("statusNote"):
            doc.add_paragraph("核验提示：" + ref["statusNote"])
        if ref.get("excerpt"):
            doc.add_paragraph(ref["excerpt"])
        if ref.get("pageNumber"):
            doc.add_paragraph(f"原文定位：PDF第 {ref['pageNumber']} 页")
        doc.add_paragraph("来源：" + ref.get("sourceUrl", ""))
    for paragraph in doc.paragraphs[appendix_start:]:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT


# 请示、报告、函、纪要：用 app.gongwen 的 GB/T 9704 版式渲染器，从后端保存的文稿生成内部草稿。
# 通知走上面的 notice_docx（gongwen-kit）；解读稿等仍用 internal_docx。
GONGWEN_DOC_TYPES = {"request": "请示", "report": "报告", "letter": "函", "minutes": "纪要"}
INTERNAL_MARK = "未审核 · 内部草稿 · 不得作为正式公文使用"


def gongwen_docx(payload: dict) -> bytes:
    """Render a saved non-notice draft; every page header carries the internal-draft mark."""
    from app.gongwen.renderer import render_bytes
    from app.gongwen.schema import GongwenDoc

    fields = payload.get("fields") or {}
    banji = payload.get("banji") or {}
    gw = GongwenDoc.from_dict({
        "doc_type": GONGWEN_DOC_TYPES[payload["docType"]],
        "title": payload.get("title", ""),
        "recipients": fields.get("recipient", ""),
        "issuer_org": fields.get("issuer", ""),
        "signer_org": fields.get("issuer", ""),
        "sign_date": payload.get("signDate", ""),
        "urgency": payload.get("urgency", ""),
        "body": payload.get("body", ""),
        "doc_number": (payload.get("docNumber") or {}).get("text", ""),
        "cc": banji.get("copyTo") or [],
        "print_org": banji.get("printer", ""),
        "print_date": banji.get("printDate", ""),
        "note": payload.get("note", ""),
    })
    doc = Document(BytesIO(render_bytes(gw)))
    for section in doc.sections:
        for header in (section.header, section.even_page_header):
            paragraph = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
            paragraph.text = INTERNAL_MARK
    _append_policy_appendix(doc, payload.get("policyRefs"))
    out = BytesIO()
    doc.save(out)
    return out.getvalue()
