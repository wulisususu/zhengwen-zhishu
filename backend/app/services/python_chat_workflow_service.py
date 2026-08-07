"""
Python Chat Workflow — 独立于 OpenClaw 的聊天工作流。
通过 config.yaml 的 python_chat_workflow.enabled 开关控制。
"""
from __future__ import annotations

import json
import logging
import re
import time
import requests
from typing import Any

from app.config import get_config
from app.schemas import ConversationOut

logger = logging.getLogger("app.python_chat_workflow")

_LLM_BACKENDS = [
    {"url": "http://127.0.0.1:8091", "model": "MiniCPM-V-4_6-Q4_K_M.gguf", "max_tokens": 800, "name": "MiniCPM-V4.6"},
    {"url": "http://127.0.0.1:8002/v1/chat/completions", "model": "Qwen3-0.6B-Q4_K_M.gguf", "max_tokens": 512, "name": "0.6B-llama"},
    {"url": "http://127.0.0.1:8002", "model": "Qwen3-0.6B-Q4_K_M",         "max_tokens": 800, "name": "0.6B-llama.cpp"},
]
_LLM_TIMEOUT = 120
_BACKEND_BASE_URL = "http://127.0.0.1:8000"
_SERVICE_TOKEN = "change-me-internal-service-token"
_HISTORY_LIMIT = 4
_HISTORY_CHAR_LIMIT = 500
_ATTACHMENT_CONTEXT_LIMIT = 1500


def _pcw_cfg() -> dict:
    cfg = get_config()
    return (cfg.get("python_chat_workflow") or {}) if isinstance(cfg, dict) else {}


def is_python_chat_workflow_enabled() -> bool:
    return bool(_pcw_cfg().get("enabled"))


# --- Intent detection ---

_TTS_RE = re.compile(r"读出来|念出来|读给我听|念给我听|朗读|播报|播放.*语音|生成.*语音|\bTTS\b", re.IGNORECASE)
_ASR_RE = re.compile(r"转写|识别.*音频|识别.*语音|听写|字幕|音频.*转成文字|语音.*转成文字|录音.*转成文字", re.IGNORECASE)


def _detect_intent(content: str, audio_ids: list[int]) -> str:
    text = (content or "").strip()
    if not text:
        return "chat"
    if _TTS_RE.search(text):
        return "tts"
    if _ASR_RE.search(text) and audio_ids:
        return "asr"
    return "chat"


def _extract_tts_text(content: str) -> str:
    text = (content or "").strip()
    m = re.search(r"[：:](.+)", text)
    if m:
        return m.group(1).strip()
    cleaned = re.sub(r"(?:请|帮我|给我)?(?:读出来|念出来|朗读|播报|读给我听|念给我听)", "", text)
    cleaned = re.sub(r"(?:生成|播放).*语音", "", cleaned)
    cleaned = re.sub(r"\bTTS\b", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned or text


# --- Tool calls ---

def _call_tts(text: str) -> dict:
    try:
        resp = requests.post(
            f"{_BACKEND_BASE_URL}/api/v1/internal/tts",
            json={"text": text},
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
            timeout=60,
        )
        if resp.status_code >= 400:
            return {"error": f"TTS failed: HTTP {resp.status_code}"}
        return resp.json().get("data") or resp.json()
    except Exception as exc:
        return {"error": f"TTS call failed: {exc}"}


def _call_asr(file_id: int, conversation_id: int, user_id: int) -> dict:
    try:
        resp = requests.post(
            f"{_BACKEND_BASE_URL}/api/v1/internal/asr",
            json={"file_id": file_id, "conversation_id": conversation_id, "user_id": user_id},
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
            timeout=120,
        )
        if resp.status_code >= 400:
            return {"error": f"ASR failed: HTTP {resp.status_code}"}
        return resp.json().get("data") or resp.json()
    except Exception as exc:
        return {"error": f"ASR call failed: {exc}"}


# --- LLM ---

def _build_messages(content: str, history: list[dict[str, str]] | None, attachment_context: str) -> list[dict[str, str]]:
    system = "你是一个中文助手。直接回答用户问题，不输出思考过程。回答要具体、有用。"
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for item in (history or [])[-_HISTORY_LIMIT:]:
        role = str(item.get("role") or "user").strip()
        msg_text = str(item.get("content") or "").strip()
        if msg_text:
            messages.append({"role": role, "content": msg_text[:_HISTORY_CHAR_LIMIT]})
    user_content = content.strip()
    ctx = str(attachment_context or "").strip()
    if ctx:
        user_content = f"附件内容：\n{ctx[:_ATTACHMENT_CONTEXT_LIMIT]}\n\n用户问题：{user_content}"
    messages.append({"role": "user", "content": user_content})
    return messages


def _try_llm_backend(backend: dict, messages: list[dict[str, str]]) -> str | None:
    url, model, max_tokens, name = backend["url"], backend["model"], backend["max_tokens"], backend["name"]
    try:
        print(f"[LLM] trying {name} @ {url}", flush=True)
        resp = requests.post(
            f"{url}/v1/chat/completions",
            json={"model": model, "messages": messages, "stream": False, "max_tokens": max_tokens, "temperature": 0.3},
            timeout=_LLM_TIMEOUT,
        )
        if resp.status_code >= 400:
            print(f"[LLM] [{name}] HTTP {resp.status_code}: {resp.text[:100]}", flush=True)
            return None
        choices = resp.json().get("choices") or []
        if choices:
            text = (choices[0].get("message") or {}).get("content") or ""
            if text.strip():
                print(f"[LLM] [{name}] OK, {len(text)} chars", flush=True)
                return text
        return None
    except Exception as exc:
        print(f"[LLM] [{name}] failed: {type(exc).__name__}: {exc}", flush=True)
        return None


def _call_llm(messages: list[dict[str, str]]) -> str:
    for backend in _LLM_BACKENDS:
        text = _try_llm_backend(backend, messages)
        if text is not None:
            return text
    return "[LLM] 所有模型均不可用"


# --- Streaming generator ---

def stream_python_chat(
    *,
    content: str,
    conversation_id: int,
    user_id: int,
    history_messages: list[dict[str, str]] | None,
    attachment_context: str,
    attachment_ids: list[int],
    audio_attachment_ids: list[int],
    workflow_type: str,
    intent_type: str,
    json_module,
    nl: str,
    workflow_event_fn,
    save_reply_fn,
    conv_data: dict,
    msg,
    msg_attachments,
):
    audio_ids = audio_attachment_ids or []
    intent = _detect_intent(content, audio_ids)

    def _wrap(payload: dict) -> str:
        return "data: " + json_module.dumps(workflow_event_fn(workflow_type, intent_type, payload), ensure_ascii=False) + nl

    # --- TTS ---
    if intent == "tts":
        tts_text = _extract_tts_text(content)
        task_id = f"tts-{int(time.time())}"
        yield _wrap({"type": "audio_start", "capability": "tts", "task_id": task_id, "status": "running"})
        result = _call_tts(tts_text)
        if result.get("error"):
            yield _wrap({"type": "token", "content": result["error"]})
            full_text = result["error"]
        else:
            yield _wrap({
                "type": "audio_done", "capability": "tts",
                "task_id": result.get("task_id") or task_id,
                "status": "completed",
                "audio_url": result.get("audio_url") or "",
                "mime_type": result.get("mime_type") or "audio/wav",
            })
            full_text = "语音已生成，请点击播放。"
            yield _wrap({"type": "token", "content": full_text})
        reply = save_reply_fn(full_text, intent_type=intent_type)
        yield _wrap({"type": "done", "id": reply.id, "content": full_text,
                      "created_at": reply.created_at.isoformat() if reply.created_at else None,
                      "status": "done", "conversation": conv_data})
        return

    # --- ASR ---
    if intent == "asr" and audio_ids:
        file_id = audio_ids[-1]
        task_id = f"asr-{int(time.time())}"
        yield _wrap({"type": "audio_start", "capability": "asr", "task_id": task_id, "status": "running"})
        result = _call_asr(file_id, conversation_id, user_id)
        if result.get("error"):
            yield _wrap({"type": "token", "content": result["error"]})
            full_text = result["error"]
        else:
            transcript = result.get("transcript") or result.get("text") or ""
            yield _wrap({
                "type": "audio_done", "capability": "asr",
                "task_id": result.get("task_id") or task_id,
                "status": "completed",
                "transcript": transcript,
                "raw_transcript": result.get("raw_transcript") or transcript,
                "mode": result.get("mode") or "",
                "backend": result.get("backend") or "",
            })
            full_text = transcript
            yield _wrap({"type": "token", "content": full_text})
        reply = save_reply_fn(full_text, intent_type=intent_type)
        yield _wrap({"type": "done", "id": reply.id, "content": full_text,
                      "created_at": reply.created_at.isoformat() if reply.created_at else None,
                      "status": "done", "conversation": conv_data})
        return

    # --- Normal chat ---
    has_attachments = bool(attachment_ids)

    # Show thinking status
    yield _wrap({"type": "status", "stage": "thinking", "message": "正在思考..."})

    # If attachments exist, show parsing status
    if has_attachments:
        time.sleep(0.3)
        yield _wrap({"type": "status", "stage": "parsing", "message": "正在解析图片..."})
        time.sleep(0.5)
        yield _wrap({"type": "status", "stage": "analyzing", "message": "正在分析..."})
        time.sleep(0.3)

    messages = _build_messages(content, history_messages, attachment_context)

    yield _wrap({"type": "status", "stage": "generating", "message": "正在生成回答..."})
    full_text = _call_llm(messages)

    chunk_size = 4
    for i in range(0, len(full_text), chunk_size):
        yield _wrap({"type": "token", "content": full_text[i:i + chunk_size]})
        time.sleep(0.02)

    reply = save_reply_fn(full_text, intent_type=intent_type)
    yield _wrap({"type": "done", "id": reply.id, "content": full_text,
                  "created_at": reply.created_at.isoformat() if reply.created_at else None,
                  "status": "done", "conversation": conv_data})
