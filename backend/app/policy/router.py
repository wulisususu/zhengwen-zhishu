"""政策问答接口（条款级检索 + 有依据才作答）。

POST   /policy/search               条款级检索（返回候选与分数，不生成结论）
POST   /policy/qa                   政策问答（有依据才作答，结论带 [n] 引用）
POST   /policy/qa/stream            同上，SSE 流式（先给证据，再逐块吐字）
GET    /policy/qa/logs              问答留痕：审核人可看全部，其他人只看自己的

政策资料只读既有政策库（T1）。导入（含 PDF 逐页解析与 OCR）、列表、详情、统计、
元数据补录与人工核验一律走 /gov/policies（导入与核验仅审核人），本模块不提供
另一套写入、修改或删除接口。引用 citation_id 与 /gov/citations/batch 同一格式。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.errors import fail, ok
from app.models import User
from app.services.policy.library import PolicyLibraryService, get_policy_library

from . import corpus, qa, retrieval
from .models import PolicyQaLog

router = APIRouter(prefix="/policy", tags=["policy-qa"])


def _options(payload: dict) -> dict:
    ids = payload.get("policy_ids") or None
    return {
        "scope": str(payload.get("scope") or "current"),
        "policy_ids": [int(i) for i in ids] if ids else None,
        "include_deprecated": bool(payload.get("include_deprecated")),
        "threshold": float(payload.get("threshold") or retrieval.DEFAULT_THRESHOLD),
        "top_k": int(payload.get("top_k") or 12),
    }


@router.post("/search")
def search_clauses(payload: dict = Body(...), user: User = Depends(get_current_user),
                   library: PolicyLibraryService = Depends(get_policy_library)):
    question = str(payload.get("query") or payload.get("question") or "").strip()
    if not question:
        return fail(400, "检索内容不能为空")
    opts = _options(payload)
    rows = corpus.load(library.store, scope=opts["scope"], policy_ids=opts["policy_ids"])
    candidates = retrieval.search(rows, question, top_k=opts["top_k"])
    return ok(data={
        "items": [
            {**c.to_dict(index=i + 1),
             "below_threshold": c.score < opts["threshold"],
             "excerpt": retrieval.build_excerpt(c.clause.content, c.matched_terms)}
            for i, c in enumerate(candidates)
        ],
        "threshold": opts["threshold"],
        "scope": opts["scope"],
    })


@router.post("/qa")
def policy_qa(payload: dict = Body(...), db: Session = Depends(get_db),
              user: User = Depends(get_current_user),
              library: PolicyLibraryService = Depends(get_policy_library)):
    question = str(payload.get("question") or payload.get("query") or "").strip()
    if not question:
        return fail(400, "问题不能为空")
    result = qa.answer(db, question, store=library.store, user_id=getattr(user, "id", None), **_options(payload))
    return ok(data=result)


def _sse(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


@router.post("/qa/stream")
def policy_qa_stream(payload: dict = Body(...), user: User = Depends(get_current_user),
                     library: PolicyLibraryService = Depends(get_policy_library)):
    """流式问答。用独立会话写留痕，避免请求级 session 在流式响应期间被回收。"""
    question = str(payload.get("question") or payload.get("query") or "").strip()
    if not question:
        return fail(400, "问题不能为空")
    kwargs = {**_options(payload), "store": library.store, "user_id": getattr(user, "id", None)}

    def event_stream():
        db = SessionLocal()
        try:
            for event in qa.answer_stream(db, question, **kwargs):
                yield _sse(event)
        except GeneratorExit:  # 客户端断开
            raise
        except Exception as exc:
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            db.close()
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/qa/logs")
def qa_logs(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    from app.gov.service import is_reviewer

    query = db.query(PolicyQaLog)
    if not is_reviewer(user):
        query = query.filter(PolicyQaLog.user_id == user.id)
    items = []
    for row in query.order_by(PolicyQaLog.id.desc()).limit(limit).all():
        item = row.to_dict()
        try:
            item["citations"] = json.loads(row.citations_json or "[]")
        except Exception:
            item["citations"] = []
        items.append(item)
    return ok(data={"items": items})
