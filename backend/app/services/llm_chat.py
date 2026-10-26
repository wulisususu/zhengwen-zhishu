"""OpenAI 兼容的最小 chat 客户端。

公文起草与政策解读都需要「直接调模型、不经过闲聊兜底」，因此单独抽这一层：
llm_client 里的考试题/算术/创作兜底会污染正式文本，不适合法律与公文场景。

出口策略：同步与流式两条路在发请求前都经过 model_policy.guard_model_url，
offline 只允许本机、intranet 只允许内网；被拒绝时抛 ModelPolicyError，
不发出任何请求，由调用方按各自规则降级（起草退回骨架稿、问答退回原文摘录）。
"""
from __future__ import annotations

import json
from typing import Any

import requests

from app.services.model_policy import guard_model_url

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_TIMEOUT = 180
DEFAULT_MAX_TOKENS = 1600
DEFAULT_TEMPERATURE = 0.3


def _cfg() -> dict:
    try:
        from app.config import get_config

        return (get_config() or {}).get("llm", {}) or {}
    except Exception:
        return {}


def build_endpoint(base_url: str) -> str:
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    if "/v1/" in base:
        return base
    return base + "/v1/chat/completions"


def settings() -> dict[str, Any]:
    cfg = _cfg()
    return {
        "url": build_endpoint(str(cfg.get("ollama_base_url") or DEFAULT_BASE_URL)),
        "model": str(cfg.get("ollama_model") or DEFAULT_MODEL),
        "timeout": int(cfg.get("ollama_timeout_seconds") or DEFAULT_TIMEOUT),
        "max_tokens": int(cfg.get("ollama_max_tokens") or DEFAULT_MAX_TOKENS),
    }


def chat(
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: int | None = None,
) -> str:
    """同步调用，返回纯文本；异常直接抛出，由调用方决定降级策略。"""
    conf = settings()
    payload = {
        "model": conf["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens or conf["max_tokens"],
        "stream": False,
    }
    url = guard_model_url(conf["url"], purpose="llm_chat")
    resp = requests.post(url, json=payload, timeout=timeout or conf["timeout"])
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("模型未返回 choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if content is None:
        content = choices[0].get("text") or ""
    return str(content)


def stream(
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: int | None = None,
):
    """流式调用，逐块 yield 文本增量。

    上游不支持 SSE（部分端侧服务把 stream 参数忽略掉）时不报错，
    而是整体取回后一次性 yield —— 前端照旧按流式渲染，
    只是「逐字出现」会退化成「一次性出现」，不会中断链路。
    """
    conf = settings()
    payload = {
        "model": conf["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens or conf["max_tokens"],
        "stream": True,
    }
    url = guard_model_url(conf["url"], purpose="llm_chat_stream")
    resp = requests.post(url, json=payload, timeout=timeout or conf["timeout"], stream=True)
    resp.raise_for_status()

    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "event-stream" not in ctype:
        data = resp.json()
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            text = message.get("content")
            if text is None:
                text = choices[0].get("text") or ""
            if text:
                yield str(text)
        resp.close()
        return

    try:
        for raw in resp.iter_lines(decode_unicode=False):
            if not raw:
                continue
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            if not chunk:
                continue
            try:
                obj = json.loads(chunk)
            except Exception:
                continue
            choices = obj.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                text = delta.get("content")
                if text:
                    yield str(text)
                continue
            # 兼容端侧服务的简化帧：{"text": "..."} / {"done": true}
            simple = obj.get("text")
            if simple:
                yield str(simple)
    finally:
        resp.close()
