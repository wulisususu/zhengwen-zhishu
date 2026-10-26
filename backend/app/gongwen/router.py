"""公文起草与版式导出接口。

POST /api/v1/gongwen/draft   表单 → IR + 校核结果
POST /api/v1/gongwen/check   已有 IR → 重新校核
POST /api/v1/gongwen/render  IR → GB/T 9704 版式 DOCX
GET  /api/v1/gongwen/meta    文种与字段元信息
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Body, Depends
from fastapi.responses import Response

from app.deps import get_current_user
from app.errors import ok
from app.models import User

from . import service
from .checker import check, stats
from .schema import (
    DOC_TYPES,
    SECRET_LEVELS,
    URGENCY_LEVELS,
    summarize,
)

router = APIRouter(prefix="/gongwen", tags=["gongwen"])

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get("/meta")
def gongwen_meta(user: User = Depends(get_current_user)):
    return ok(data={
        "doc_types": list(DOC_TYPES),
        "secret_levels": list(SECRET_LEVELS),
        "urgency_levels": list(URGENCY_LEVELS),
        "fields": [
            {"key": "doc_type", "label": "文种", "required": True},
            {"key": "subject", "label": "事由", "required": True,
             "hint": "填写「加强窗口作风建设」即可，前缀「关于」和文种由系统补全"},
            {"key": "recipients", "label": "主送机关", "required": False,
             "hint": "多个机关用顿号分隔；请示只能有一个"},
            {"key": "issuer_org", "label": "发文机关", "required": False},
            {"key": "sign_date", "label": "成文日期", "required": False},
            {"key": "doc_number", "label": "发文字号", "required": False,
             "hint": "如 X政服发〔2026〕12号"},
        ],
    })


@router.post("/draft")
def gongwen_draft(payload: dict = Body(...), user: User = Depends(get_current_user)):
    return ok(data=service.draft(payload))


@router.post("/check")
def gongwen_check(payload: dict = Body(...), user: User = Depends(get_current_user)):
    doc = service.ir_from_payload(payload)
    issues = check(doc)
    return ok(data={
        "issues": [i.to_dict() for i in issues],
        "stats": stats(issues),
        "summary": summarize(doc),
    })


@router.post("/render")
def gongwen_render(payload: dict = Body(...), user: User = Depends(get_current_user)):
    data, filename = service.render_docx(payload)
    return Response(
        content=data,
        media_type=DOCX_MIME,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "X-Filename": quote(filename),
            "Cache-Control": "no-store",
        },
    )
