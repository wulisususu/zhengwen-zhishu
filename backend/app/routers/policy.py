"""Read-only policy retrieval API (plus an admin-only sync). Contract: docs/policy-api.md."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.deps import get_current_user, require_admin
from app.errors import ERR_NOT_FOUND, ERR_PARAM, ERR_POLICY, fail, ok
from app.models import User
from app.services.policy import errors as policy_errors
from app.services.policy.service import PolicyRetrievalService, get_policy_service

router = APIRouter(prefix="/policy", tags=["policy"])


class SyncRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=100)
    pages: int = Field(3, ge=1, le=20)
    per_page: int = Field(20, ge=1, le=50)


def _error_response(error: dict, data: dict):
    code = ERR_PARAM if error.get("code") == policy_errors.INVALID_QUERY else ERR_POLICY
    return fail(code, error.get("message", "政策检索失败"), data=data)


@router.get("/search")
def search_policies(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=50),
    _user: User = Depends(get_current_user),
    service: PolicyRetrievalService = Depends(get_policy_service),
):
    result = service.search(q, limit=limit).to_dict()
    error = result.get("error")
    # A degraded search (remote failed or not permitted) still returns local hits with code 0;
    # data.error explains why. Only an unusable query or an internal failure is a failed request.
    if error and error.get("code") in (policy_errors.INVALID_QUERY, policy_errors.INTERNAL_ERROR):
        return _error_response(error, result)
    return ok(data=result)


@router.get("/documents")
def list_policy_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    _user: User = Depends(get_current_user),
    service: PolicyRetrievalService = Depends(get_policy_service),
):
    data = service.list_documents(page=page, page_size=page_size)
    if data.get("error"):
        return _error_response(data["error"], data)
    return ok(data=data)


@router.get("/documents/{doc_id}")
def get_policy_document(
    doc_id: int,
    _user: User = Depends(get_current_user),
    service: PolicyRetrievalService = Depends(get_policy_service),
):
    doc, error = service.get_document(doc_id)
    if error:
        return _error_response(error, {"id": doc_id})
    if doc is None:
        return fail(ERR_NOT_FOUND, "政策文件不存在", data={"id": doc_id})
    return ok(data=doc)


@router.post("/sync")
def sync_policies(
    body: SyncRequest,
    _admin: User = Depends(require_admin),
    service: PolicyRetrievalService = Depends(get_policy_service),
):
    result = service.sync_topic(body.topic, pages=body.pages, per_page=body.per_page).to_dict()
    if result.get("error"):
        return _error_response(result["error"], result)
    return ok(data=result)
