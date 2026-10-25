"""Public policy library API for the gov-office frontend. Contract: docs/policy-api.md.

POST /gov/policies/import        admin   URL or uploaded file, synchronous
GET  /gov/policies               login   filter by keyword / doc_number / issuer / status
POST /gov/policies/search        login   clause search (default status=current)
POST /gov/citations/batch        login   ids[] -> Citation[] (GovOfficeAdapter.getCitations)
POST /gov/policies/{id}/verify   admin   human verification of status and metadata
"""
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.deps import get_current_user, require_admin
from app.errors import ERR_NOT_FOUND, ERR_PARAM, ERR_POLICY, fail, ok
from app.models import User
from app.services.policy import errors as policy_errors
from app.services.policy.library import ImportRequest, PolicyLibraryService, get_policy_library
from app.services.policy.settings import MAX_FETCH_BYTES_LIMIT

router = APIRouter(prefix="/gov", tags=["gov-policy"])

Status = Literal["current", "abolished", "unverified"]
_PARAM_ERRORS = {policy_errors.INVALID_QUERY, policy_errors.INVALID_STATUS, policy_errors.UNSUPPORTED_FILE, policy_errors.FETCH_BAD_URL}


def _respond(data: dict):
    error = data.get("error")
    if not error:
        return ok(data=data)
    if error.get("code") == policy_errors.NOT_FOUND:
        return fail(ERR_NOT_FOUND, error["message"], data=data)
    return fail(ERR_PARAM if error.get("code") in _PARAM_ERRORS else ERR_POLICY, error.get("message", "操作失败"), data=data)


@router.post("/policies/import")
async def import_policy(
    url: str | None = Form(None, max_length=2000),
    source_url: str | None = Form(None, max_length=2000),
    title: str | None = Form(None, max_length=300),
    doc_number: str | None = Form(None, max_length=100),
    issuer: str | None = Form(None, max_length=200),
    publish_date: str | None = Form(None, max_length=20),
    file: UploadFile | None = File(None),
    _admin: User = Depends(require_admin),
    library: PolicyLibraryService = Depends(get_policy_library),
):
    data = None
    filename = None
    if file is not None:
        data = await file.read(MAX_FETCH_BYTES_LIMIT + 1)
        filename = file.filename
    req = ImportRequest(url=url, filename=filename, data=data, source_url=source_url, title=title,
                        doc_number=doc_number, issuer=issuer, publish_date=publish_date)
    return _respond(await run_in_threadpool(library.import_policy, req))


@router.get("/policies")
def list_policies(
    keyword: str = Query("", max_length=100),
    doc_number: str = Query("", max_length=100),
    issuer: str = Query("", max_length=200),
    status: list[Status] = Query(default=[]),
    include_history: bool = Query(False),
    url: str = Query("", max_length=2000),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    _user: User = Depends(get_current_user),
    library: PolicyLibraryService = Depends(get_policy_library),
):
    return _respond(library.list_policies(
        keyword=keyword, doc_number=doc_number, issuer=issuer, statuses=tuple(status),
        include_history=include_history, url=url, page=page, page_size=page_size,
    ))


class ClauseSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=100)
    statuses: list[Status] | None = Field(None, description="默认只检索 current；包含其他状态须显式传入")
    limit: int = Field(10, ge=1, le=50)
    include_history: bool = False


@router.post("/policies/search")
def search_clauses(
    body: ClauseSearchRequest,
    _user: User = Depends(get_current_user),
    library: PolicyLibraryService = Depends(get_policy_library),
):
    return _respond(library.search(body.query, statuses=body.statuses, limit=body.limit, include_history=body.include_history))


class CitationBatchRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=50)


@router.post("/citations/batch")
def citations_batch(
    body: CitationBatchRequest,
    _user: User = Depends(get_current_user),
    library: PolicyLibraryService = Depends(get_policy_library),
):
    return _respond(library.citations(body.ids))


class VerifyRequest(BaseModel):
    status: Status
    status_note: str | None = Field(None, max_length=500)
    title: str | None = Field(None, max_length=300)
    doc_number: str | None = Field(None, max_length=100)
    issuer: str | None = Field(None, max_length=200)
    publish_date: str | None = Field(None, max_length=10)
    effective_date: str | None = Field(None, max_length=10)
    expire_date: str | None = Field(None, max_length=10)


@router.post("/policies/{policy_id}/verify")
def verify_policy(
    policy_id: int,
    body: VerifyRequest,
    admin: User = Depends(require_admin),
    library: PolicyLibraryService = Depends(get_policy_library),
):
    fields = body.model_dump(exclude={"status", "status_note"}, exclude_none=True)
    return _respond(library.verify(policy_id, status=body.status, note=body.status_note, fields=fields,
                                   verifier=getattr(admin, "username", "admin")))
