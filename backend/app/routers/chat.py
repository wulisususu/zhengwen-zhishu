from fastapi import APIRouter, Depends
from app.deps import get_current_user
from app.models import User
from app.errors import ok, fail, ERR_INTERNAL, ERR_PARAM
from app.services.security import pre_check, post_check, check_identity

router = APIRouter(prefix="/chat", tags=["chat"])

BLOCKED_REPLY = "您的输入包含不允许的内容，请重新提问。"

@router.post("")
def chat(body: dict, user: User = Depends(get_current_user)):
    content = body.get("content", "")
    if not content:
        return fail(ERR_INTERNAL, "content is required")

    # Identity question → canned response
    identity_reply = check_identity(content)
    if identity_reply:
        return ok(data={"role": "assistant", "content": identity_reply})

    # Layer 1: input filter
    check = pre_check(content)
    if not check.allowed:
        return ok(data={"role": "assistant", "content": check.block_reason})

    from app.services.llm_client import generate
    prompt = "User: " + content + chr(10) + "Assistant:"
    result = generate(prompt)
    if "error" in result:
        return ok(data={"role": "assistant", "content": "[LLM] " + result["error"]})

    # Layer 3: output audit
    raw_text = result.get("text", "")
    safe_text = post_check(raw_text)
    return ok(data={"role": "assistant", "content": safe_text})
