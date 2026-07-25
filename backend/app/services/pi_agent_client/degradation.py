"""PI Agent 降级决策：agent 不可用时自动切换到下一级路径."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import AsyncGenerator
import asyncio
import requests

from app.services.pi_agent_client.base_client import (
    PiAgentClient,
    health_check,
)
from app.services.openclaw_gateway import compact_document_filename
from app.services.llm_client import set_35b_reachable

logger = logging.getLogger(__name__)

CHAT_AGENT_URL = "http://127.0.0.1:18790"
DOC_AGENT_URL = "http://127.0.0.1:18791"
PCW_URL = "http://127.0.0.1:8099"


def _sse_frame(payload):
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return "data: " + body + "\n\n"


def _wrap(workflow, intent, payload):
    return {"workflow": workflow, "intent_type": intent, **payload}


def _build_document_preface(prompt):
    prompt_text = str(prompt or "")
    quoted = re.search(r'[《"“]([^》”"]{2,40})[》”"]', prompt_text)
    quoted_title = quoted.group(1).strip() if quoted else ""
    title = quoted_title or compact_document_filename(prompt, max_chars=18) or "正式文档"
    return f"我会为你生成《{title}》，并在完成正文后生成可下载文档。"


def _emit_text_chunks(text, chunk_size=6):
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]


async def _stream_pi_chat(content, user_id, conversation_id, workflow, intent, attachment_context=""):
    from app.services.pi_agent_client.chat_client import call_chat_agent
    async for text in call_chat_agent(
        content=content, user_id=user_id,
        conversation_id=conversation_id, attachment_context=attachment_context,
    ):
        yield _sse_frame(_wrap(workflow, intent, {"type": "token", "content": text}))


async def _stream_pi_doc(content, user_id, conversation_id, message_id, workflow, intent, attachment_ids=None, attachment_context=""):
    from app.services.pi_agent_client.doc_client import call_doc_agent
    async for text in call_doc_agent(
        content=content, user_id=user_id,
        conversation_id=conversation_id, message_id=message_id,
        attachment_ids=attachment_ids, attachment_context=attachment_context,
    ):
        yield _sse_frame(_wrap(workflow, intent, {"type": "token", "content": text}))


async def chat_with_degradation(
    content, user_id, conversation_id, message_id,
    attachment_context="", conversation_data=None, msg_attachments=None,
    msg_knowledge_docs=None,
):
    """Chat: PI Agent (18790) with 30s timeout → direct local model fallback.

    When 35B is unreachable, OpenClaw wraps prompts with tools/system messages
    that blow up the 0.6B context window. This path skips OpenClaw entirely
    and sends a clean prompt directly to the local model via _local_small_generate().
    """
    workflow = "chat"
    intent = "chat"
    conv = conversation_data or {}
    attachments = msg_attachments or []
    knowledge_docs = msg_knowledge_docs or []

    # emit user event
    yield _sse_frame(_wrap(workflow, intent, {
        "type": "user", "id": message_id, "role": "user",
        "content": content, "msg_type": "text",
        "attachments": attachments, "knowledge_docs": knowledge_docs, "conversation": conv,
    }))

    # ── Path 1: PI Agent (18790) with 30s timeout ──
    if await health_check(f"{CHAT_AGENT_URL}/health"):
        try:
            yield _sse_frame(_wrap(workflow, intent, {
                "type": "message_start", "role": "assistant",
            }))
            full_text = ""
            _stream = _stream_pi_chat(
                content, user_id, conversation_id, workflow, intent, attachment_context,
            )
            _iter = _stream.__aiter__()
            _start = time.monotonic()
            while True:
                try:
                    frame = await asyncio.wait_for(_iter.__anext__(), timeout=5)
                except asyncio.TimeoutError:
                    elapsed = time.monotonic() - _start
                    if elapsed >= 10:
                        logger.warning("PI Agent timed out after %.1fs, falling back to local model", elapsed)
                        raise
                    yield _sse_frame(_wrap(workflow, intent, {
                        "type": "status", "stage": "thinking",
                        "message": "模型正在思考…",
                    }))
                    continue
                try:
                    payload_str = frame[6:].strip()
                    obj = json.loads(payload_str)
                    if obj.get("type") == "token":
                        full_text += obj.get("content", "")
                except Exception:
                    pass
                yield frame
            # If we get here, the stream ended naturally
            yield _sse_frame(_wrap(workflow, intent, {
                "type": "done",
                "content": full_text,
                "conversation": conv,
            }))
            yield _sse_frame("[DONE]")
            return
        except (StopAsyncIteration, GeneratorExit):
            logger.warning("PI Agent stream ended early, falling back to local model")
            # Fall through to Path 2
        except Exception as exc:
            logger.warning("PI Agent failed: %s, falling back to local model", exc)

    # ── Path 2: Direct local model (bypass OpenClaw, clean prompt) ──
    yield _sse_frame(_wrap(workflow, intent, {
        "type": "status", "stage": "degraded",
        "message": "主模型暂时不可用，已切换至本地轻量服务。",
    }))

    try:
        from app.services.llm_client import _local_small_generate
        safe_content = (content or "").strip()
        if attachment_context:
            att_ctx = attachment_context.strip()[:3000]
            if attachment_context.strip() != att_ctx:
                att_ctx += "..."
            safe_content = "附件信息:\\n" + att_ctx + "\\n---\\n用户问题: " + safe_content
        if len(safe_content) > 3500:
            safe_content = safe_content[:3500]
        result = await asyncio.to_thread(_local_small_generate, safe_content, 512)
        text = result.get("text", "") if isinstance(result, dict) else ""
        if not text and isinstance(result, dict) and "error" in result:
            text = "[错误] " + str(result["error"])
    except Exception as exc:
        logger.warning("Local small model also failed: %s", exc)
        text = "[错误] 本地模型调用失败: " + str(exc)

    if not text:
        text = "[错误] 未能获取有效回复"

    # Stream text as token chunks (simulating SSE for frontend)
    chunk_size = 6
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        yield _sse_frame(_wrap(workflow, intent, {"type": "token", "content": chunk}))
        await asyncio.sleep(0.02)

    yield _sse_frame(_wrap(workflow, intent, {
        "type": "done",
        "content": text,
        "conversation": conv,
    }))
    yield _sse_frame("[DONE]")






async def doc_with_degradation(
    content, user_id, conversation_id, message_id,
    attachment_ids=None, attachment_context="", attachment_files=None,
    conversation_data=None, msg_attachments=None,
):
    """Document: PI Agent doc -> docs_pipeline -> create_document_task.

    SSE event sequence matching Pipeline 1:
    user -> message_start -> preface tokens -> status:analyzing
    -> PI Agent content generation (tokens)
    -> create_document_task -> status:rendering_docx -> doc_task -> done -> [DONE]
    """
    workflow = "document"
    intent = "document"
    conv = conversation_data or {}
    attachments = msg_attachments or []
    full_content = ""

    preface_text = _build_document_preface(content)

    # --- PI Agent doc (primary path) ---
    if await health_check(f"{DOC_AGENT_URL}/health"):
        try:
            # 1. user event
            yield _sse_frame(_wrap(workflow, intent, {
                "type": "user", "id": message_id, "role": "user",
                "content": content, "msg_type": "text",
                "attachments": attachments, "conversation": conv,
            }))

            # 2. message_start
            yield _sse_frame(_wrap(workflow, intent, {
                "type": "message_start", "role": "assistant",
            }))

            # 3. preface token stream
            if preface_text:
                for chunk in _emit_text_chunks(preface_text, chunk_size=6):
                    full_content += chunk
                    yield _sse_frame(_wrap(workflow, intent, {"type": "token", "content": chunk}))
                    time.sleep(0.02)

            # 4. status: analyzing
            yield _sse_frame(_wrap(workflow, intent, {
                "type": "status", "stage": "analyzing", "message": "正在分析你的文档需求…",
            }))

            # 5. PI Agent content generation (with timeout guard against session deadlock)
            agent_text = ""
            _doc_stream = _stream_pi_doc(
                content, user_id, conversation_id, message_id,
                workflow, intent, attachment_ids, attachment_context,
            )
            _doc_iter = _doc_stream.__aiter__()
            _is_first_frame = True
            _doc_start = time.time()
            _last_hb = 0
            while True:
                try:
                    _timeout = 900 if _is_first_frame else 120
                    # Use shorter internal timeout for heartbeat opportunities
                    _inner_timeout = min(_timeout, 10)
                    frame = await asyncio.wait_for(_doc_iter.__anext__(), timeout=_inner_timeout)
                    _is_first_frame = False
                    yield frame
                    try:
                        payload_str = frame[6:].strip()
                        obj = json.loads(payload_str)
                        if obj.get("type") == "token":
                            t = obj.get("content", "")
                            agent_text += t
                            full_content += t
                    except Exception:
                        pass
                except asyncio.TimeoutError:
                    # Send heartbeat if doc generation is still running
                    _now = time.time()
                    if _now - _last_hb >= 10:
                        _last_hb = _now
                        yield _sse_frame(_wrap(workflow, intent, {
                            "type": "status", "stage": "generating",
                            "message": f"正在生成文档内容…({int(_now - _doc_start)}s)",
                        }))
                    continue
                except StopAsyncIteration:
                    break

            # 6. Render markdown directly to DOCX (bypass docs_pipeline)
            from app.services.document_agent import classify_workflow
            from app.services.openclaw_gateway import (
                invoke_backend_document_render_docx,
                extract_document_task_payload,
                compact_document_filename,
            )

            route = classify_workflow(content)
            filename = compact_document_filename(content, max_chars=40) + ".docx"
            render_args = {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "instruction": content,
                "content": agent_text if agent_text else content,
                "content_type": "markdown",
                "filename": filename,
                "attachments": attachment_ids or [],
            }

            # 7. status: rendering_docx
            yield _sse_frame(_wrap(workflow, intent, {
                "type": "status", "stage": "rendering_docx", "message": "正在生成可下载文档…",
            }))

            render_result = invoke_backend_document_render_docx(render_args, timeout_seconds=60)
            render_data = render_result.get("data") or render_result
            task = extract_document_task_payload(render_data) or {
                "task_id": render_data.get("task_id", ""),
                "title": filename,
                "status": "queued",
            }

            # 8. doc_task event
            yield _sse_frame(_wrap(workflow, intent, {
                "type": "doc_task",
                "task": {
                    "task_id": task.get("task_id", ""),
                    "title": task.get("title", filename),
                    "status": task.get("status", "queued"),
                    "progress": 100 if task.get("status") == "done" else 6,
                    "engine": route.get("engine", "python-docx"),
                    "doc_type": route.get("doc_type", "report"),
                    "template_id": route.get("template_id", "simple_v1"),
                },
            }))

            # 9. done event (id assigned by caller after DB save)
            yield _sse_frame(_wrap(workflow, intent, {
                "type": "done",
                "content": full_content,
                "conversation": conv,
            }))

            # 10. [DONE]
            yield _sse_frame("[DONE]")
            return

        except Exception as exc:
            logger.warning("PI Agent doc failed, degrading to docs_pipeline: %s", exc)

    # --- docs_pipeline (degradation) ---
    try:
        from app.docs_pipeline.runner import run_pipeline_stream
        async for frame in run_pipeline_stream(content, user_id, conversation_id):
            yield frame
        return
    except Exception as exc:
        logger.warning("docs_pipeline failed, degrading to create_document_task: %s", exc)

    yield _sse_frame(_wrap(workflow, intent, {
        "type": "error", "content": "文档生成服务当前不可用，请稍后重试。",
    }))
    yield _sse_frame("[DONE]")


def _use_pi_agent_chat():
    import os
    env = os.getenv("PI_AGENT_CHAT", "").lower()
    if env in {"1", "true"}:
        return True
    if env in {"0", "false"}:
        return False
    return False


def _use_pi_agent_doc():
    import os
    env = os.getenv("PI_AGENT_DOC", "").lower()
    if env in {"1", "true"}:
        return True
    if env in {"0", "false"}:
        return False
    return False
