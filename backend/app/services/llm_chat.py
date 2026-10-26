"""公文起草、政策问答与文稿初稿生成共用的云端模型客户端。

架构：本项目不使用本地 NPU 推理。模型一律经既有的云端（OpenAI 兼容）政务 API 调用，
地址、模型名、密钥与超时取自 model_config.get_35b_config() —— 与设置页「外部模型」
同一份配置（EXTERNAL_MODEL_BASE_URL / EXTERNAL_MODEL_NAME / EXTERNAL_MODEL_API_KEY，
或 DEEPSEEK_API_KEY；可写在环境变量或后端 .env）。本模块不启动、不切换任何本地模型。

与 llm_client 分开，是因为后者的考试题 / 算术 / 创作兜底会污染公文与政策文本。

出口策略：同步与流式两条路在发请求前都经过 model_policy.guard_model_url。云端地址只在
model.mode=cloud_allowed 时放行；offline / intranet 下拒绝，抛 ModelPolicyError，不发请求。
未配置密钥时同样不发请求，抛 ModelNotConfigured。调用方按各自规则降级（起草退回骨架稿、
问答退回原文摘录、文稿初稿生成返回 503），不会退回本地模型。
"""
from __future__ import annotations

import json
from typing import Any

import requests

from app.services.model_policy import guard_model_url

DEFAULT_MAX_TOKENS = 1600
DEFAULT_TEMPERATURE = 0.3
#: 交互请求的超时上限（秒）；配置里的外部模型超时可能长达 600 秒
MAX_TIMEOUT = 180


class ModelNotConfigured(RuntimeError):
    """云端模型 API 未配置（缺密钥），请求未发出。"""


def _endpoint(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    return base if base.endswith("/chat/completions") else base + "/chat/completions"


def _conf() -> dict[str, Any]:
    from app.services.model_config import get_35b_config

    cfg = get_35b_config()
    return {
        "url": _endpoint(cfg["base_url"]),
        "model": cfg["model"],
        "timeout": min(int(cfg["timeout_seconds"]), MAX_TIMEOUT),
        "max_tokens": DEFAULT_MAX_TOKENS,
        "api_key": cfg["api_key"],
    }


def settings() -> dict[str, Any]:
    """当前云端模型设置（不含密钥），供调用方记录模型名。"""
    return {k: v for k, v in _conf().items() if k != "api_key"}


def _post(payload: dict, *, purpose: str, timeout: int | None, stream: bool = False):
    conf = _conf()
    url = guard_model_url(conf["url"], purpose=purpose)
    if not conf["api_key"]:
        raise ModelNotConfigured("云端模型 API 未配置密钥（EXTERNAL_MODEL_API_KEY 或 DEEPSEEK_API_KEY），未发送请求")
    body = {"model": conf["model"], **payload}
    body["max_tokens"] = body.get("max_tokens") or conf["max_tokens"]
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {conf['api_key']}"}
    return requests.post(url, json=body, headers=headers, timeout=timeout or conf["timeout"], stream=stream)


def chat(
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: int | None = None,
) -> str:
    """同步调用，返回纯文本；异常直接抛出，由调用方决定降级策略。"""
    resp = _post({"messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": False},
                 purpose="llm_chat", timeout=timeout)
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

    上游不支持 SSE 时不报错，而是整体取回后一次性 yield —— 前端照旧按流式渲染。
    """
    resp = _post({"messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": True},
                 purpose="llm_chat_stream", timeout=timeout, stream=True)
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
    finally:
        resp.close()
