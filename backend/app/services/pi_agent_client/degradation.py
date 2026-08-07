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
    prompt_text = str(prompt or "").strip()

    # 1. 先尝试从书名号中提取标题
    quoted = re.search(r'[《"“]([^》”"]{2,40})[》”"]', prompt_text)
    if quoted:
        title = quoted.group(1).strip()
        return f"我会为你生成《{title}》，并在完成正文后生成可下载文档。"

    # Keep preface creation deterministic. Loading 0.6B before the primary
    # writer both violates document routing priority and competes for the NPU.
    # The document agent/pipeline performs the actual title polishing.
    # 2. Fallback: strip common request prefixes.
    prefix_patterns = [
        r"^写一篇\d{0,6}字的",
        r"^生成一份\d{0,6}字的",
        r"^生成一份",
        r"^写一篇",
        r"^请写",
        r"^请生成",
        r"^帮我写",
        r"^帮我生成",
        r"^请帮我写",
        r"^请帮我生成",
    ]
    cleaned = prompt_text
    for pat in prefix_patterns:
        cleaned = re.sub(pat, "", cleaned, count=1).strip()

    if cleaned:
        if len(cleaned) > 18:
            cut = re.search(r'[,，。；;的：:  ]', cleaned)
            if cut and cut.start() > 4:
                title = cleaned[:cut.start()].strip()
            else:
                title = cleaned[:18].strip()
        else:
            title = cleaned
    else:
        title = "正式文档"

    return f"我会为你生成《{title}》，并在完成正文后生成可下载文档。"


def _pipeline_section_count(prompt: str) -> int:
    """Keep degraded documents proportional to the requested length."""
    match = re.search(r"(\d{2,6})\s*字", str(prompt or ""))
    target = int(match.group(1)) if match else 1800
    return 3 if target <= 800 else (4 if target <= 1800 else 6)


def _extract_title_with_06b(prompt_text):
    """用本地 Qwen3-0.6B 提取文档标题。失败/超时返回 None。"""
    import time as _time
    import requests as _requests
    try:
        resp = _requests.post(
            "http://127.0.0.1:8002/v1/chat/completions",
            json={
                "model": "Qwen3-0.6B-Q4_K_M.gguf",
                "messages": [{
                    "role": "user",
                    "content": (
                        "提取文档主题作为标题，只输出标题本身（不超过15字），"
                        "不要输出任何解释、标点或换行。输入：" + prompt_text
                    ),
                }],
                "max_tokens": 30,
                "temperature": 0.1,
                "stop": ["\n", "。", "，", "：", "（", "("],
            },
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        title = resp.json()["choices"][0]["message"]["content"].strip()
        # 过滤掉明显是输入回显的结果
        if len(title) < 2 or len(title) > 20:
            return None
        if title == prompt_text or title.startswith("写一篇") or title.startswith("生成"):
            return None
        return title
    except Exception:
        return None

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
    from app.services.pi_agent_client.base_client import AgentUnavailable

    max_retries = 3
    last_exc = None
    for attempt in range(max_retries):
        try:
            async for text in call_doc_agent(
                content=content, user_id=user_id,
                conversation_id=conversation_id, message_id=message_id,
                attachment_ids=attachment_ids, attachment_context=attachment_context,
            ):
                yield _sse_frame(_wrap(workflow, intent, {"type": "token", "content": text}))
            return  # success — exit retry loop
        except (AgentUnavailable, Exception) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = 2 * (attempt + 1)
                logger.warning("PI Agent stream attempt %d/%d failed (%s), retrying in %ds…",
                               attempt + 1, max_retries, exc, delay)
                yield _sse_frame(_wrap(workflow, intent, {
                    "type": "status", "stage": "retrying",
                    "message": f"模型暂时无响应，正在重试第 {attempt + 1}/{max_retries} 次…",
                }))
                await asyncio.sleep(delay)
            else:
                raise
    raise last_exc


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

    # ── Path 1: external model through PI Agent ──
    # External OpenAI-compatible endpoints can occasionally reset a stream
    # before producing the first visible token. Retry that transient failure
    # on the same primary model before taking the local 0.6B degradation path.
    primary_attempts = 3
    primary_retry_delays = (1, 3)
    if await health_check(f"{CHAT_AGENT_URL}/health"):
        yield _sse_frame(_wrap(workflow, intent, {
            "type": "message_start", "role": "assistant",
        }))
        for attempt in range(primary_attempts):
            full_text = ""
            stream = _stream_pi_chat(
                content, user_id, conversation_id, workflow, intent, attachment_context,
            )
            iterator = stream.__aiter__()
            try:
                while True:
                    try:
                        # The external model may need several seconds to issue
                        # its first visible token after a cold/queued request.
                        frame = await asyncio.wait_for(iterator.__anext__(), timeout=15)
                    except StopAsyncIteration:
                        if full_text.strip():
                            yield _sse_frame(_wrap(workflow, intent, {
                                "type": "done",
                                "content": full_text,
                                "conversation": conv,
                            }))
                            yield _sse_frame("[DONE]")
                            return
                        raise RuntimeError("PI Agent stream ended without visible output")
                    except asyncio.TimeoutError as exc:
                        raise RuntimeError("PI Agent produced no visible output within 15 seconds") from exc

                    try:
                        payload_str = frame[6:].strip()
                        obj = json.loads(payload_str)
                        if obj.get("type") == "token":
                            full_text += obj.get("content", "")
                    except Exception:
                        pass
                    yield frame
            except GeneratorExit:
                raise
            except Exception as exc:
                # Retrying after visible text would duplicate an answer in the
                # browser, so reserve retries for pre-output transport failures.
                can_retry = not full_text.strip() and attempt < primary_attempts - 1
                if can_retry:
                    delay = primary_retry_delays[attempt]
                    logger.warning(
                        "PI Agent primary attempt %d/%d failed before output (%s); retrying in %ds",
                        attempt + 1, primary_attempts, exc, delay,
                    )
                    yield _sse_frame(_wrap(workflow, intent, {
                        "type": "status",
                        "stage": "retrying_primary",
                        "message": f"主模型连接波动，正在重试（{attempt + 2}/{primary_attempts}）…",
                    }))
                    await asyncio.sleep(delay)
                    continue
                logger.warning(
                    "PI Agent primary exhausted after %d attempt(s), falling back to local model: %s",
                    attempt + 1, exc,
                )
                break
            finally:
                await stream.aclose()

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

    v2 节点状态（每步语义明确）:
    1. user                — 用户消息回显
    2. message_start       — 助手开始回复
    3. status:preparing    — "正在准备文档生成…"
    4. token (preface)     — "我会为你生成《xxx》..."
    5. status:generating   — "正在生成文档内容…"（紧接在 preface 之后、agent 输出之前）
    6. token (agent)       — 正文（已过滤 CoT）
    7. status:rendering    — "正在渲染可下载文档…"
    8. doc_task (done)     — 含 status=done + file.download_url
    9. done                — 完成
    10. [DONE]
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

            # 3. status: preparing (before any content)
            yield _sse_frame(_wrap(workflow, intent, {
                "type": "status", "stage": "preparing", "message": "正在准备文档生成…",
            }))

            # 4. preface token stream
            if preface_text:
                for chunk in _emit_text_chunks(preface_text, chunk_size=6):
                    full_content += chunk
                    yield _sse_frame(_wrap(workflow, intent, {"type": "token", "content": chunk}))
                    await asyncio.sleep(0.02)

            # 5. status: generating (immediately after preface, before agent output)
            yield _sse_frame(_wrap(workflow, intent, {
                "type": "status", "stage": "generating", "message": "正在生成文档内容…",
            }))

            # 6. Producer/queue scheduling makes terminal delivery explicit.
            agent_text = ""
            _doc_start = time.monotonic()
            _last_hb = 0.0
            _frame_queue: asyncio.Queue = asyncio.Queue()

            async def _pump_doc_stream() -> None:
                try:
                    async for _frame in _stream_pi_doc(content, user_id, conversation_id, message_id, workflow, intent, attachment_ids, attachment_context):
                        await _frame_queue.put(("frame", _frame))
                except Exception as _exc:
                    await _frame_queue.put(("error", _exc))
                finally:
                    await _frame_queue.put(("end", None))

            _pump_task = asyncio.create_task(_pump_doc_stream())
            try:
                while True:
                    try:
                        _kind, _value = await asyncio.wait_for(_frame_queue.get(), timeout=10.0)
                    except asyncio.TimeoutError:
                        _now = time.monotonic()
                        if _now - _doc_start >= 900:
                            raise TimeoutError("Doc Agent exceeded 900s without a terminal event")
                        if _now - _last_hb >= 10:
                            _last_hb = _now
                            yield _sse_frame(_wrap(workflow, intent, {"type": "status", "stage": "generating", "message": f"正在生成文档内容…({int(_now - _doc_start)}s)"}))
                        continue
                    if _kind == "error":
                        raise _value
                    if _kind == "end":
                        break
                    frame = str(_value)
                    yield frame
                    try:
                        obj = json.loads(frame[6:].strip())
                        if obj.get("type") == "token":
                            text = obj.get("content", "")
                            agent_text += text
                            full_content += text
                    except Exception:
                        pass
            finally:
                if not _pump_task.done():
                    _pump_task.cancel()
                try:
                    await _pump_task
                except asyncio.CancelledError:
                    pass

            # 7. Render markdown directly to DOCX
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

            # status: rendering_docx
            yield _sse_frame(_wrap(workflow, intent, {
                "type": "status", "stage": "rendering_docx", "message": "正在生成可下载文档…",
            }))

            render_result = await asyncio.to_thread(
                invoke_backend_document_render_docx, render_args, timeout_seconds=60,
            )
            render_data = render_result.get("data") or render_result
            task = extract_document_task_payload(render_data) or {
                "task_id": render_data.get("task_id", ""),
                "title": filename,
                "status": "queued",
            }

            # ── 获取 file.download_url ──
            download_url = ""
            try:
                file_info = task.get("file") or render_data.get("file") or {}
                if isinstance(file_info, dict) and file_info.get("download_url"):
                    download_url = file_info["download_url"]
                elif isinstance(file_info, int):
                    # file_id → 尝试从 files 表查
                    import sqlite3, os
                    db_path = "data/app.db"
                    c = sqlite3.connect(db_path)
                    cur = c.cursor()
                    cur.execute("SELECT filepath FROM files WHERE id=?", (file_info,))
                    row = cur.fetchone()
                    c.close()
                    if row:
                        download_url = f"/api/v1/files/download/{file_info}"
                elif task.get("task_id"):
                    download_url = f"/api/v1/document-tasks/{task['task_id']}/download"
            except Exception:
                pass

            # 8. doc_task event — with done status and download_url
            yield _sse_frame(_wrap(workflow, intent, {
                "type": "doc_task",
                "task": {
                    "task_id": task.get("task_id", ""),
                    "title": task.get("title", filename),
                    "status": "done",
                    "progress": 100,
                    "engine": route.get("engine", "python-docx"),
                    "doc_type": route.get("doc_type", "report"),
                    "template_id": route.get("template_id", "simple_v1"),
                    "file": {
                        "download_url": download_url,
                    } if download_url else None,
                },
            }))

            # 9. done event
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

    # --- docs_pipeline (3B-only degradation) ---
    try:
        from app.docs_pipeline.runner import run_pipeline_stream
        pipeline_text = full_content
        pipeline_task_id = f"doc-{conversation_id}"
        async for frame in run_pipeline_stream(
            content,
            section_count=_pipeline_section_count(content),
            task_id=pipeline_task_id,
            user_id=user_id,
        ):
            # docs_pipeline uses event: names. Adapt its richer internal
            # events to the single frontend SSE protocol used by ChatMode.
            event_name = ""
            payload = {}
            for raw_line in frame.splitlines():
                if raw_line.startswith("event:"):
                    event_name = raw_line[6:].strip()
                elif raw_line.startswith("data:"):
                    try:
                        payload = json.loads(raw_line[5:].strip())
                    except json.JSONDecodeError:
                        payload = {}

            if event_name == "status":
                yield _sse_frame(_wrap(workflow, intent, {
                    "type": "status",
                    "stage": payload.get("phase", "generating"),
                    "message": payload.get("message", "正在生成文档内容…"),
                }))
            elif event_name == "chapter":
                heading = str(payload.get("heading", "")).strip()
                chapter = str(payload.get("content", "")).strip()
                rendered = (f"## {heading}\n\n" if heading else "") + chapter
                if rendered:
                    rendered += "\n\n"
                    pipeline_text += rendered
                    for chunk in _emit_text_chunks(rendered, chunk_size=12):
                        yield _sse_frame(_wrap(workflow, intent, {"type": "token", "content": chunk}))
            elif event_name == "done":
                download_url = str(payload.get("download_url", "")).strip()
                filename = str(payload.get("filename", filename if 'filename' in locals() else "document.docx"))
                yield _sse_frame(_wrap(workflow, intent, {
                    "type": "doc_task",
                    "task": {
                        "task_id": pipeline_task_id,
                        "title": filename,
                        "status": "done",
                        "progress": 100,
                        "engine": "python-docx",
                        "doc_type": "report",
                        "template_id": "simple_v1",
                        "file": {"download_url": download_url} if download_url else None,
                    },
                }))
                yield _sse_frame(_wrap(workflow, intent, {
                    "type": "done", "content": pipeline_text, "conversation": conv,
                }))
                yield _sse_frame("[DONE]")
                return
            elif event_name == "fallback":
                raise RuntimeError(payload.get("message") or "docs_pipeline failed")
        raise RuntimeError("docs_pipeline ended without a terminal event")
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
