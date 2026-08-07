"""
独立 Chat Python 工作流 — 1.5B 模型 + TTS/ASR 工具
监听 0.0.0.0:8099，前端可直接切换调用，与 OpenClaw 完全隔离。
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# LLM backends: try in order, first success wins
LLM_BACKENDS = [
    {"url": "http://127.0.0.1:8088", "model": "Qwen2.5-1.5B-Instruct", "max_tokens": 512, "name": "1.5B-RKLLM"},
    {"url": "http://127.0.0.1:8002", "model": "Qwen3-0.6B-Q4_K_M",    "max_tokens": 800, "name": "0.6B-llama.cpp"},
]
LLM_TIMEOUT = 120

# Optional: pause MiniCPM-V on 8091 to free NPU for 1.5B RKLLM
MINICPM_PAUSE_URL = "http://127.0.0.1:8091/admin/pause"
MINICPM_RESUME_URL = "http://127.0.0.1:8091/admin/resume"

BACKEND_BASE_URL = "http://127.0.0.1:8000"
BACKEND_SERVICE_TOKEN = "change-me-internal-service-token"

HISTORY_LIMIT = 4
HISTORY_CHAR_LIMIT = 500
ATTACHMENT_CONTEXT_LIMIT = 1500
PORT = 8099

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("python_chat_workflow")

app = FastAPI(title="Python Chat Workflow")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    content: str
    conversation_id: int = 0
    user_id: int = 0
    attachment_ids: list[int] | None = None
    audio_attachment_ids: list[int] | None = None
    history: list[dict[str, str]] | None = None
    attachment_context: str | None = None


# ---------------------------------------------------------------------------
# Intent detection (pure regex, no model call)
# ---------------------------------------------------------------------------

_TTS_PATTERNS = re.compile(
    r"读出来|念出来|读给我听|念给我听|朗读|播报|播放.*语音|生成.*语音|\bTTS\b",
    re.IGNORECASE,
)

_ASR_PATTERNS = re.compile(
    r"转写|识别.*音频|识别.*语音|听写|字幕|音频.*转成文字|语音.*转成文字|录音.*转成文字",
    re.IGNORECASE,
)


def detect_intent(content: str, audio_attachment_ids: list[int]) -> str:
    text = (content or "").strip()
    if not text:
        return "chat"
    if _TTS_PATTERNS.search(text):
        return "tts"
    if _ASR_PATTERNS.search(text) and audio_attachment_ids:
        return "asr"
    return "chat"


def extract_tts_text(content: str) -> str:
    """Extract the text to be spoken from user message."""
    text = (content or "").strip()
    # Try quoted content after colon/quote
    m = re.search(r"[：:](.+)", text)
    if m:
        return m.group(1).strip()
    # Remove trigger words
    cleaned = re.sub(r"(?:请|帮我|给我)?(?:读出来|念出来|朗读|播报|读给我听|念给我听)", "", text)
    cleaned = re.sub(r"(?:生成|播放).*语音", "", cleaned)
    cleaned = re.sub(r"\bTTS\b", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned or text


# ---------------------------------------------------------------------------
# Tool calls: TTS & ASR
# ---------------------------------------------------------------------------


def call_tts(text: str) -> dict:
    """Call backend internal TTS endpoint."""
    try:
        resp = requests.post(
            f"{BACKEND_BASE_URL}/api/v1/internal/tts",
            json={"text": text},
            headers={"Authorization": f"Bearer {BACKEND_SERVICE_TOKEN}"},
            timeout=60,
        )
        if resp.status_code >= 400:
            return {"error": f"TTS failed: HTTP {resp.status_code}"}
        data = resp.json()
        return data.get("data") or data
    except Exception as exc:
        return {"error": f"TTS call failed: {exc}"}


def call_asr(file_id: int, conversation_id: int, user_id: int) -> dict:
    """Call backend internal ASR endpoint."""
    try:
        resp = requests.post(
            f"{BACKEND_BASE_URL}/api/v1/internal/asr",
            json={
                "file_id": file_id,
                "conversation_id": conversation_id,
                "user_id": user_id,
            },
            headers={"Authorization": f"Bearer {BACKEND_SERVICE_TOKEN}"},
            timeout=120,
        )
        if resp.status_code >= 400:
            return {"error": f"ASR failed: HTTP {resp.status_code}"}
        data = resp.json()
        return data.get("data") or data
    except Exception as exc:
        return {"error": f"ASR call failed: {exc}"}


# ---------------------------------------------------------------------------
# LLM call (non-streaming, RKLLM doesn't support SSE)
# ---------------------------------------------------------------------------


def build_messages(
    content: str,
    history: list[dict[str, str]] | None,
    attachment_context: str | None,
) -> list[dict[str, str]]:
    system = "你是一个中文助手。直接回答用户问题，不输出思考过程。回答要具体、有用。"
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]

    for item in (history or [])[-HISTORY_LIMIT:]:
        role = str(item.get("role") or "user").strip()
        msg_text = str(item.get("content") or "").strip()
        if msg_text:
            messages.append({"role": role, "content": msg_text[:HISTORY_CHAR_LIMIT]})

    user_content = content.strip()
    ctx = str(attachment_context or "").strip()
    if ctx:
        user_content = f"附件内容：\n{ctx[:ATTACHMENT_CONTEXT_LIMIT]}\n\n用户问题：{user_content}"
    messages.append({"role": "user", "content": user_content})
    return messages


def _try_llm_backend(backend: dict, messages: list[dict[str, str]]) -> str | None:
    """Try a single LLM backend. Returns response text or None on failure."""
    url = backend["url"]
    model = backend["model"]
    max_tokens = backend["max_tokens"]
    name = backend["name"]
    try:
        resp = requests.post(
            f"{url}/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=LLM_TIMEOUT,
        )
        if resp.status_code >= 400:
            logger.warning("[%s] HTTP %s: %s", name, resp.status_code, resp.text[:100])
            return None
        data = resp.json()
        choices = data.get("choices") or []
        if choices:
            text = (choices[0].get("message") or {}).get("content") or ""
            if text.strip():
                logger.info("[%s] OK, %d chars", name, len(text))
                return text
        return None
    except Exception as exc:
        logger.warning("[%s] failed: %s", name, exc)
        return None


def call_llm(messages: list[dict[str, str]]) -> str:
    """Call LLM with fallback chain. Returns full response text."""
    for backend in LLM_BACKENDS:
        text = _try_llm_backend(backend, messages)
        if text is not None:
            return text
    return "[LLM] 所有模型均不可用，请检查 8088/8002 端口。"


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

NL = "\n\n"


def sse_data(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + NL


def sse_done() -> str:
    return "data: [DONE]" + NL


def workflow_wrap(payload: dict, workflow: str = "chat", intent_type: str = "conversation") -> dict:
    return {"workflow": workflow, "intent_type": intent_type, **payload}


# ---------------------------------------------------------------------------
# Streaming generator
# ---------------------------------------------------------------------------


def stream_chat(req: ChatRequest):
    """Main SSE generator — produces events identical to OpenClaw format."""
    content = (req.content or "").strip()
    audio_ids = req.audio_attachment_ids or []
    intent = detect_intent(content, audio_ids)

    # --- TTS intent ---
    if intent == "tts":
        tts_text = extract_tts_text(content)
        task_id = f"tts-{int(time.time())}"
        yield sse_data(workflow_wrap({"type": "audio_start", "capability": "tts", "task_id": task_id, "status": "running"}))

        result = call_tts(tts_text)
        if result.get("error"):
            yield sse_data(workflow_wrap({"type": "token", "content": result["error"]}))
            full_text = result["error"]
        else:
            audio_url = result.get("audio_url") or ""
            mime_type = result.get("mime_type") or "audio/wav"
            result_task_id = result.get("task_id") or task_id
            yield sse_data(workflow_wrap({
                "type": "audio_done",
                "capability": "tts",
                "task_id": result_task_id,
                "status": "completed",
                "audio_url": audio_url,
                "mime_type": mime_type,
            }))
            full_text = "语音已生成，请点击播放。"
            yield sse_data(workflow_wrap({"type": "token", "content": full_text}))

        yield sse_data(workflow_wrap({
            "type": "done", "id": 0, "content": full_text,
            "status": "done",
        }))
        yield sse_done()
        return

    # --- ASR intent ---
    if intent == "asr" and audio_ids:
        file_id = audio_ids[-1]  # use last audio file
        task_id = f"asr-{int(time.time())}"
        yield sse_data(workflow_wrap({"type": "audio_start", "capability": "asr", "task_id": task_id, "status": "running"}))

        result = call_asr(file_id, req.conversation_id, req.user_id)
        if result.get("error"):
            yield sse_data(workflow_wrap({"type": "token", "content": result["error"]}))
            full_text = result["error"]
        else:
            transcript = result.get("transcript") or result.get("text") or ""
            result_task_id = result.get("task_id") or task_id
            yield sse_data(workflow_wrap({
                "type": "audio_done",
                "capability": "asr",
                "task_id": result_task_id,
                "status": "completed",
                "transcript": transcript,
                "raw_transcript": result.get("raw_transcript") or transcript,
                "mode": result.get("mode") or "",
                "backend": result.get("backend") or "",
            }))
            full_text = transcript
            yield sse_data(workflow_wrap({"type": "token", "content": full_text}))

        yield sse_data(workflow_wrap({
            "type": "done", "id": 0, "content": full_text,
            "status": "done",
        }))
        yield sse_done()
        return

    # --- Normal chat ---
    messages = build_messages(content, req.history, req.attachment_context)

    # Status: analyzing
    yield sse_data(workflow_wrap({"type": "status", "stage": "analyzing", "content": "正在分析需求..."}))

    # Call 1.5B (non-streaming)
    yield sse_data(workflow_wrap({"type": "status", "stage": "generating", "content": "正在生成内容..."}))
    full_text = call_llm(messages)

    # Simulate streaming: emit in small chunks
    yield sse_data(workflow_wrap({"type": "status", "stage": "answering", "content": "正在回答..."}))
    chunk_size = 4  # characters per chunk
    for i in range(0, len(full_text), chunk_size):
        chunk = full_text[i : i + chunk_size]
        yield sse_data(workflow_wrap({"type": "token", "content": chunk}))
        time.sleep(0.02)  # small delay to simulate streaming

    # Done
    yield sse_data(workflow_wrap({
        "type": "done",
        "id": 0,
        "content": full_text,
        "status": "done",
    }))
    yield sse_done()


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@app.post("/api/v1/chat/stream")
async def chat_stream(req: ChatRequest):
    return StreamingResponse(
        stream_chat(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    backend_status = []
    for b in LLM_BACKENDS:
        try:
            r = requests.get(f"{b['url']}/health", timeout=2)
            backend_status.append({"name": b["name"], "url": b["url"], "status": "ok" if r.status_code < 400 else "error"})
        except Exception:
            backend_status.append({"name": b["name"], "url": b["url"], "status": "unreachable"})
    return {"status": "ok", "service": "python-chat-workflow", "port": PORT, "backends": backend_status}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Python Chat Workflow on port %d", PORT)
    for b in LLM_BACKENDS:
        logger.info("  LLM backend: %s @ %s (max_tokens=%d)", b["name"], b["url"], b["max_tokens"])
    logger.info("Backend TTS/ASR: %s", BACKEND_BASE_URL)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
