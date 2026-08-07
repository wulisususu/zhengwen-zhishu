"""Document Agent 客户端."""
from __future__ import annotations

import json
import logging
import re
from typing import AsyncGenerator

import httpx

from app.services.pi_agent_client.base_client import PiAgentClient, _clean_delta, AgentUnavailable
def _strip_cot_commentary(full_text: str) -> str:
    """Return only the final Markdown document body.

    The document agent is a text-only writer. Any planning or tool narration is
    internal noise and must never be sent to the frontend or DOCX renderer.
    """
    if not full_text:
        return full_text

    body = full_text.strip()
    heading = re.search(r"(?m)^#\s+\S.*$", body)
    if heading:
        body = body[heading.start():]
    else:
        # Legacy model replies sometimes use a plain title followed by “一、…”.
        # Recover that body boundary without forwarding the preceding narration.
        lines = body.splitlines()
        chapter_re = re.compile(r"^(?:[一二三四五六七八九十]+、|\d+(?:\.\d+)*[、.])")
        for index in range(len(lines) - 1):
            title = lines[index].strip()
            if title and len(title) <= 80:
                next_line = next((line.strip() for line in lines[index + 1:] if line.strip()), "")
                if chapter_re.match(next_line):
                    body = "# " + title + "\n" + "\n".join(lines[index + 1:]).strip()
                    break

    tail_re = re.compile(
        r"^(?:现在|接下来|然后|让我|我先|根据.*AGENTS|当前我已|请提供|"
        r"I(?:'ll| will)|Let me|Now let me).*"
        r"(?:调用|工具|渲染|DOCX|下载|任务|确认|call|tool|render|download)",
        re.IGNORECASE,
    )
    kept: list[str] = []
    for line in body.splitlines():
        if tail_re.search(line.strip()):
            break
        kept.append(line.rstrip())

    result = "\n".join(kept).strip()
    return result or body


logger = logging.getLogger(__name__)
MIN_BUFFERED_DOCUMENT_CHARS = 240


def _clean_document_body(raw_parts: list[str]) -> str:
    full = "".join(raw_parts)
    has_structured = bool(
        re.search(r"(^|\n)#{1,3} ", full) and re.search(r"[\u4e00-\u9fff]", full)
    )
    return _strip_cot_commentary(full) if has_structured else full.strip()


def _is_renderable_buffered_document(text: str) -> bool:
    if len(text) < MIN_BUFFERED_DOCUMENT_CHARS:
        return False
    if not re.match(r"^#\s+\S", text):
        return False
    return bool(
        re.search(r"(?m)^##\s+\S", text)
        or re.search(r"(?m)^(?:[一二三四五六七八九十]+、|\d+(?:\.\d+)*[、.])", text)
    )


def _chunk_document(text: str) -> AsyncGenerator[str, None]:
    # Kept as a generator helper so every successful path emits identical chunks.
    for index in range(0, len(text), 12):
        yield text[index:index + 12]


DOC_AGENT_URL = "http://127.0.0.1:18791"
DOC_AGENT_STREAM_TIMEOUT = 900


def _parse_response_chunk(line: str) -> str | None:
    """解析 /v1/responses SSE chunk，提取 output_text delta.
    增强: 错误事件标记 + 工具调用屏蔽 + 输出清洗."""
    import logging
    logger = logging.getLogger(__name__)
    if not line.startswith("data: "):
        return None
    data_str = line[6:]
    if data_str == "[DONE]":
        return "__DONE__"
    try:
        obj = json.loads(data_str)
        evt = obj.get("type", "")
        if evt in ("response.error", "error", "response.failed"):
            err = obj.get("message", "") or obj.get("error", {}).get("message", "")
            logger.warning("PI Agent SSE error event: %s", err)
            return "__ERROR__"
        if evt == "response.output_item.added":
            item = obj.get("item", {})
            if item.get("type") == "function_call":
                return None
        if evt == "response.output_text.delta":
            return _clean_delta(obj.get("delta", ""))
        if evt == "response.output_text.done":
            # OpenClaw may send no incremental assistant delta and place the
            # complete document only in this terminal event. Preserve it before
            # declaring the stream complete.
            final_text = _clean_delta(obj.get("text", ""))
            return "__FINAL__" + final_text if final_text else "__DONE__"
        if evt == "response.completed":
            # Compatibility fallback for gateways that omit output_text.done.
            output = obj.get("response", {}).get("output", [])
            final_text = ""
            for item in output if isinstance(output, list) else []:
                for part in item.get("content", []) if isinstance(item, dict) else []:
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        final_text += str(part.get("text", ""))
            final_text = _clean_delta(final_text)
            return "__FINAL__" + final_text if final_text else "__DONE__"
    except (json.JSONDecodeError, KeyError):
        pass
    return None


async def call_doc_agent(
    content: str,
    user_id: int,
    conversation_id: int,
    message_id: int,
    attachment_ids: list[int] | None = None,
    attachment_context: str = "",
) -> AsyncGenerator[str, None]:
    """Generate a document and preserve a valid body if SSE closing fails."""
    client = PiAgentClient(DOC_AGENT_URL, timeout=DOC_AGENT_STREAM_TIMEOUT)
    input_text = content
    if attachment_context:
        input_text = "附件内容:\n" + attachment_context + "\n\n用户需求:\n" + content

    raw_parts: list[str] = []
    emitted_body = ""

    def _new_safe_body() -> str:
        """Return only the stable suffix that is safe to send over SSE."""
        nonlocal emitted_body
        clean = _clean_document_body(raw_parts)
        if not _is_renderable_buffered_document(clean):
            return ""
        if not emitted_body:
            emitted_body = clean
            return clean
        if clean.startswith(emitted_body):
            suffix = clean[len(emitted_body):]
            emitted_body = clean
            return suffix
        # A late cleanup rewrite must never duplicate or replace text already
        # shown in the browser. The final DOCX gate still receives full clean.
        logger.warning("Doc Agent normalized body changed after SSE emission; holding rewrite for final render")
        return ""

    try:
        async for sse_line in client.post_sse_stream(
            "/v1/responses",
            {"model": "openclaw/doc", "input": input_text, "stream": True},
        ):
            text = _parse_response_chunk(sse_line)
            if text == "__DONE__":
                break
            if text and text.startswith("__FINAL__"):
                final_text = text[len("__FINAL__"):]
                if final_text:
                    raw_parts.append(final_text)
                    safe_suffix = _new_safe_body()
                    for chunk in _chunk_document(safe_suffix):
                        yield chunk
                break
            if text == "__ERROR__":
                raise AgentUnavailable("PI Agent returned error event from model")
            if text:
                raw_parts.append(text)
                # Do not expose planning/thinking. Once a valid Markdown title
                # and section exist, progressively push only the safe body.
                safe_suffix = _new_safe_body()
                for chunk in _chunk_document(safe_suffix):
                    yield chunk
    except (httpx.TimeoutException, AgentUnavailable) as exc:
        clean = _clean_document_body(raw_parts)
        if _is_renderable_buffered_document(clean):
            logger.warning(
                "Doc Agent stream ended without completion; preserving streamed body "
                "(chars=%d, reason=%s)", len(clean), type(exc).__name__,
            )
            if not emitted_body:
                for chunk in _chunk_document(clean):
                    yield chunk
            elif clean.startswith(emitted_body):
                for chunk in _chunk_document(clean[len(emitted_body):]):
                    yield chunk
            return
        raise

    clean = _clean_document_body(raw_parts)
    if not emitted_body:
        for chunk in _chunk_document(clean):
            yield chunk
    elif clean.startswith(emitted_body):
        for chunk in _chunk_document(clean[len(emitted_body):]):
            yield chunk
