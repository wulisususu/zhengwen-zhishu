"""Document generation endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.errors import ok, fail, ERR_INTERNAL, ERR_NOT_FOUND
from app.models import Conversation, User
from app.services.document_service import classify_document, validate_document_route
from app.services.document_tasks import cancel_task, create_document_task, get_task, list_tasks

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/generate")
def generate_document(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prompt = body.get("prompt") or body.get("content") or body.get("text") or ""
    route = body.get("route")
    if route is None and any(key in body for key in ("doc_type", "engine", "template_id")):
        route = {"doc_type": body.get("doc_type"), "engine": body.get("engine"), "template_id": body.get("template_id")}
    if route is None:
        route = classify_document(
            prompt,
            attachment_context=body.get("attachment_context") or "",
            force_output_format="docx",
        )
    else:
        route = classify_document(
            prompt,
            attachment_context=body.get("attachment_context") or "",
            force_output_format="docx",
        ) | dict(route or {})
        route.setdefault("output_spec", {})["format"] = "docx"
    content_schema = body.get("content_schema")
    if not prompt and content_schema is None:
        return fail(ERR_INTERNAL, "prompt or content_schema is required")
    try:
        validation = validate_document_route(route, attachment_context=body.get("attachment_context") or "")
        if validation.get("status") == "failed":
            return fail(ERR_INTERNAL, validation.get("message") or "document route validation failed")
        task = create_document_task(
            prompt,
            user.id,
            route=route,
            content_schema=content_schema,
            conversation_id=body.get("conversation_id"),
            message_id=body.get("message_id"),
            workflow_type=body.get("workflow_type") or "document",
        )
        return ok(data={"task": task, "routing_json": route, "validation": validation})
    except Exception as exc:
        return fail(ERR_INTERNAL, str(exc))


@router.get("/tasks/{task_id}")
def document_task_status(task_id: str, user: User = Depends(get_current_user)):
    task = get_task(task_id, user.id)
    if not task:
        return fail(ERR_NOT_FOUND, "task not found")
    return ok(data=task)


@router.post("/tasks/{task_id}/cancel")
def cancel_document_task(task_id: str, user: User = Depends(get_current_user)):
    task = cancel_task(task_id, user.id)
    if not task:
        return fail(ERR_NOT_FOUND, "task not found")
    return ok(data=task)


@router.get("/tasks")
def document_task_list(
    conversation_id: int | None = None,
    workflow_type: str | None = "document",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if conversation_id is not None:
        conv = db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user.id).first()
        if not conv:
            return fail(ERR_NOT_FOUND, "conversation not found")
    return ok(data=list_tasks(user.id, conversation_id=conversation_id, workflow_type=workflow_type))
