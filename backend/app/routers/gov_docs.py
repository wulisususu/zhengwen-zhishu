"""公文 generation and review API (gongwen-kit + own rules). Contract: docs/gongwen-api.md.

POST /gov/notices/review   login   structured 通知 → two-layer review + backend gate
POST /gov/notices/export   login   internal_draft → DOCX marked 未审核 (always allowed)
                                   formal → backend re-review + permission + approval; refused until
                                            the approval workflow exists in the backend
POST /gov/docx/check       login   uploaded .docx → format check + numbering/count rules
POST /gov/docx/fix         login   uploaded .docx → layout-fixed COPY (optional; not a compliance claim)

Uploads are written to a private temp dir under a fixed name, never modified, and
deleted afterwards. Logs carry file name, size, duration and counts only.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.deps import get_current_user
from app.errors import ERR_PARAM, fail, ok
from app.models import User
from app.services.gongwen import catalog
from app.services.gongwen.checker import validate_docx_path
from app.services.gongwen.fixer import fix_copy
from app.services.gongwen.review import render_notice, review_external_docx, review_notice
from app.services.gongwen.runner import GongwenToolError
from app.services.gongwen.schema import ExportRequest, NoticeDraft
from app.services.gongwen.settings import GongwenSettings, load_settings

logger = logging.getLogger("app.gongwen")
router = APIRouter(prefix="/gov", tags=["gov-docs"])

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_INPUT_ERRORS = {catalog.TOOL_INVALID_INPUT, catalog.TOOL_RENDER_REJECTED}


def get_gongwen_settings() -> GongwenSettings:
    return load_settings()


def can_formal_issue(user: User) -> bool:
    """Formal-issue permission. The backend only has admin/user roles today; admin stands in."""
    return bool(getattr(user, "is_admin", False))


def _tool_fail(exc: GongwenToolError) -> dict:
    code = ERR_PARAM if exc.code in _INPUT_ERRORS else catalog.ERR_GONGWEN_TOOL
    return fail(code, exc.message, data={"error": exc.to_dict()})


def _safe_name(name: str | None) -> str:
    base = Path(name or "").name
    return re.sub(r"[\x00-\x1f]", "", base)[:120] or "document.docx"


def _download_name(title: str, suffix: str) -> str:
    stem = re.sub(r'[\\/:*?"<>|\s]+', "", title)[:40] or "通知"
    return f"{stem}{suffix}.docx"


def _docx_response(content: bytes, filename: str, headers: dict | None = None) -> Response:
    disposition = f"attachment; filename=\"document.docx\"; filename*=UTF-8''{quote(filename)}"
    return Response(content=content, media_type=DOCX_MIME,
                    headers={"Content-Disposition": disposition, **(headers or {})})


# ── structured 通知 ──────────────────────────────────────────────────────
@router.post("/notices/review")
async def review(draft: NoticeDraft, user: User = Depends(get_current_user),
                 settings: GongwenSettings = Depends(get_gongwen_settings)):
    return ok(data=await run_in_threadpool(review_notice, draft, settings))


@router.post("/notices/export")
async def export(req: ExportRequest, user: User = Depends(get_current_user),
                 settings: GongwenSettings = Depends(get_gongwen_settings)):
    if req.kind == "formal":
        if not can_formal_issue(user):
            raise HTTPException(status_code=403, detail="需要正式发文权限")
        result = await run_in_threadpool(review_notice, req.draft, settings)
        gate = result["gate"]
        # Formal export needs a recorded approval; approvals are not persisted in the backend
        # yet, so gate.canExportFormal is always False and this branch always refuses. Do not
        # fall through to the draft renderer below.
        if gate["blockingIssueIds"] or not gate["canApprove"]:
            message = "存在未解决的严重问题或格式机检未完成，不能正式导出"
        else:
            message = "后端审批流程尚未接入，不能正式导出"
        return fail(catalog.ERR_GATE, message, data={"gate": gate, "summary": result["summary"],
                                                     "formatCheck": result["formatCheck"]})

    def _render() -> bytes:
        with tempfile.TemporaryDirectory(prefix="gongwen-export-") as tmp:
            out = Path(tmp) / "notice.docx"
            render_notice(req.draft, out, settings, internal_draft=True)
            return out.read_bytes()

    start = time.monotonic()
    try:
        content = await run_in_threadpool(_render)
    except GongwenToolError as exc:
        return _tool_fail(exc)
    logger.info("gongwen export kind=internal_draft bytes=%d seconds=%.3f", len(content), time.monotonic() - start)
    return _docx_response(content, _download_name(req.draft.title, "-内部草稿"),
                          {"X-Gongwen-Export-Kind": "internal_draft", "X-Gongwen-Reviewed": "false"})


# ── uploaded Word files ──────────────────────────────────────────────────
async def _read_upload(file: UploadFile, settings: GongwenSettings) -> tuple[bytes, str] | dict:
    name = _safe_name(file.filename)
    if not name.lower().endswith(".docx"):
        return fail(ERR_PARAM, "只接受 .docx 文件")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        return fail(ERR_PARAM, f"文件超过 {settings.max_upload_bytes // (1024 * 1024)} MB")
    if not data.startswith(b"PK\x03\x04"):
        return fail(ERR_PARAM, "文件不是 DOCX（ZIP）格式")
    return data, name


@router.post("/docx/check")
async def check_upload(file: UploadFile = File(...), user: User = Depends(get_current_user),
                       settings: GongwenSettings = Depends(get_gongwen_settings)):
    read = await _read_upload(file, settings)
    if isinstance(read, dict):
        return read
    data, name = read

    def _run() -> dict:
        with tempfile.TemporaryDirectory(prefix="gongwen-check-") as tmp:
            src = Path(tmp) / "upload.docx"
            src.write_bytes(data)
            result = review_external_docx(validate_docx_path(src), settings)
            result["file"] = {"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                              "unchanged": src.read_bytes() == data}
            return result

    start = time.monotonic()
    try:
        result = await run_in_threadpool(_run)
    except GongwenToolError as exc:
        return _tool_fail(exc)
    logger.info("gongwen upload check file=%s bytes=%d seconds=%.3f critical=%d hint=%d", name, len(data),
                time.monotonic() - start, result["summary"]["critical"], result["summary"]["hint"])
    return ok(data=result)


@router.post("/docx/fix")
async def fix_upload(file: UploadFile = File(...), user: User = Depends(get_current_user),
                     settings: GongwenSettings = Depends(get_gongwen_settings)):
    read = await _read_upload(file, settings)
    if isinstance(read, dict):
        return read
    data, name = read

    def _run() -> dict:
        with tempfile.TemporaryDirectory(prefix="gongwen-fix-") as tmp:
            src, out = Path(tmp) / "upload.docx", Path(tmp) / "fixed.docx"
            src.write_bytes(data)
            fixed = fix_copy(src, out, settings)
            post = review_external_docx(out, settings)
            return {
                "filename": _download_name(Path(name).stem, "-修订"),
                "docxBase64": base64.b64encode(out.read_bytes()).decode("ascii"),
                "report": fixed["report"],
                "original": {"name": name, "sha256": hashlib.sha256(data).hexdigest(),
                             "unchanged": src.read_bytes() == data},
                "postReview": post,
                "complianceClaim": False,
                "complianceNote": catalog.COMPLIANCE_NOTE_FIX,
            }

    start = time.monotonic()
    try:
        result = await run_in_threadpool(_run)
    except GongwenToolError as exc:
        return _tool_fail(exc)
    logger.info("gongwen upload fix file=%s bytes=%d seconds=%.3f", name, len(data), time.monotonic() - start)
    return ok(data=result)
