"""Local small model service wrapper for the board-side Qwen3 0.6B model.

This module provides a safe, config-driven wrapper around the board-side
Qwen3 0.6B model (port 8090). It is intended ONLY for short text tasks:
voice transcript cleanup, intent normalization, tool-argument polishing.

All failures are swallowed and returned as fallback dicts — this service
must never block or crash the main OpenClaw workflow.
"""
from __future__ import annotations

import logging
import re
import time

import requests

from app.config import get_config

logger = logging.getLogger("app.local_small_model")

VALID_MODES: set[str] = {
    "general",
    "voice_refine",
    "intent_normalize",
    "tool_args_refine",
}

MODE_PROMPTS: dict[str, str] = {
    "voice_refine": (
        "整理语音文本，只输出结果：\n{prompt}"
    ),
    "intent_normalize": (
        "请用一句话概括：{prompt}"
    ),
    "tool_args_refine": (
        "整理为简短工具参数，只输出结果：\n{prompt}"
    ),
    "general": "{prompt}",
}

_DEFAULT_MAX_PROMPT_CHARS = 2000
_DEFAULT_MAX_OUTPUT_CHARS = 1000
_DEFAULT_TIMEOUT = 12
_DEFAULT_MODEL_NAME = "Qwen3-0.6B-Q4_K_M.gguf"
_LEGACY_MODEL_NAME = "deepseek-r1-1.5b-rk3588"


def clean_local_small_output(text: str) -> str:
    """Strip <think> tags and collapse excessive newlines."""
    cleaned = str(text or "")
    if re.search(r"</think>", cleaned, flags=re.I) and not re.search(r"<think>", cleaned, flags=re.I):
        cleaned = re.sub(r"^.*?</think>", "", cleaned, flags=re.S | re.I)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.S | re.I)
    cleaned = cleaned.replace("<think>", "").replace("</think>", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _llm_config() -> dict:
    cfg = get_config()
    return cfg.get("llm") or {}


def _model_name(llm: dict) -> str:
    configured = str(llm.get("local_small_model_name") or "").strip()
    if configured:
        return configured
    if str(llm.get("local_small_model_api_url") or "").strip():
        return _DEFAULT_MODEL_NAME
    return _LEGACY_MODEL_NAME


def _chat_completion_body(prompt: str, model_name: str, max_tokens: int | None, max_output_chars: int) -> dict:
    return {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": int(max_tokens or min(256, max_output_chars)),
        "temperature": 0.2,
    }


def generate(
    prompt: str,
    mode: str = "general",
    max_tokens: int | None = None,
) -> dict:
    """Call the local small model and return a normalized result dict.

    Returns:
        {
            "text": str,
            "model": "Qwen3-0.6B-Q4_K_M.gguf",
            "source": "local-small",
            "mode": str,
            "fallback": bool,
            "error": str | None,
        }

    Never raises — all exceptions are caught and returned as fallback.
    """
    original = (prompt or "").strip()

    llm = _llm_config()
    enabled = llm.get("local_small_model_enabled", True)
    base_url = str(llm.get("prompt_model_url") or "").rstrip("/")
    api_url = str(llm.get("local_small_model_api_url") or "").strip()
    model_name = _model_name(llm)
    timeout = float(llm.get("prompt_timeout_seconds") or _DEFAULT_TIMEOUT)
    max_prompt_chars = int(llm.get("local_small_model_max_prompt_chars") or _DEFAULT_MAX_PROMPT_CHARS)
    max_output_chars = int(llm.get("local_small_model_max_output_chars") or _DEFAULT_MAX_OUTPUT_CHARS)

    def _fallback(error_msg: str) -> dict:
        return {
            "text": original,
            "model": model_name,
            "source": "local-small",
            "mode": mode,
            "fallback": True,
            "error": error_msg,
        }

    if not enabled:
        return _fallback("local small model disabled")

    if not api_url and not base_url:
        return _fallback("local small model url not configured")

    if mode not in VALID_MODES:
        # Caller should validate mode before calling, but guard here too
        return _fallback(f"invalid mode: {mode}")

    # Truncate input
    truncated = original[:max_prompt_chars]

    # Build prompt from mode template
    template = MODE_PROMPTS.get(mode, MODE_PROMPTS["general"])
    final_prompt = template.format(prompt=truncated)

    try:
        if api_url:
            resp = requests.post(
                api_url,
                json=_chat_completion_body(final_prompt, model_name, max_tokens, max_output_chars),
                timeout=timeout,
            )
        else:
            resp = requests.post(
                f"{base_url}/v1/completions",
                json={"prompt": final_prompt, "stream": False},
                timeout=timeout,
            )
        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
    except requests.exceptions.Timeout:
        logger.warning("local small model timeout after %ss", timeout)
        return _fallback("local small model timeout")
    except requests.exceptions.ConnectionError:
        logger.warning("local small model connection failed: %s", base_url)
        return _fallback("local small model unavailable")
    except Exception as exc:
        logger.warning("local small model error: %s", exc)
        return _fallback(f"local small model error: {exc}")

    raw_text = _extract_completion_text(payload).strip()
    if not raw_text:
        logger.warning("local small model returned empty text")
        return _fallback("local small model returned empty output")

    cleaned = clean_local_small_output(raw_text)
    if not cleaned:
        return _fallback("local small model output was only think tags")

    # Truncate output
    final_text = cleaned[:max_output_chars]

    return {
        "text": final_text,
        "model": model_name,
        "source": "local-small",
        "mode": mode,
        "fallback": False,
        "error": None,
    }

_CHAT_DEFAULT_SUMMARY = "我会先提取你的核心问题，并尽量给出结构化、可执行的回答。"
_CHAT_FAILURE_COUNT = 0
_CHAT_CIRCUIT_OPEN_UNTIL = 0.0


def _bool_setting(cfg: dict, name: str, default: bool) -> bool:
    raw = cfg.get(name, default)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _int_setting(cfg: dict, name: str, default: int) -> int:
    try:
        return int(cfg.get(name, default))
    except Exception:
        return default


def _extract_completion_text(payload) -> str:
    if isinstance(payload, dict):
        text = payload.get("text") or payload.get("content") or payload.get("response")
        if isinstance(text, str):
            return text
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            choice_text = first.get("text")
            if isinstance(choice_text, str):
                return choice_text
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
    return ""


def _chat_fallback(original: str, error: str, latency_ms: int = 0, summary: str | None = _CHAT_DEFAULT_SUMMARY) -> dict:
    return {
        "summary": summary or "",
        "refined_prompt": original,
        "original_input": original,
        "fallback": True,
        "error": error,
        "latency_ms": latency_ms,
    }


def _short_summary(text: str, limit: int = 120) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if not compact:
        return _CHAT_DEFAULT_SUMMARY
    sentence = re.split(r"(?<=[。！？!?])", compact, maxsplit=1)[0].strip()
    return (sentence or compact)[:limit]


def _record_chat_failure(cfg: dict) -> None:
    global _CHAT_FAILURE_COUNT, _CHAT_CIRCUIT_OPEN_UNTIL
    _CHAT_FAILURE_COUNT += 1
    if not _bool_setting(cfg, "chat_preflight_circuit_breaker", True):
        return
    threshold = max(1, _int_setting(cfg, "chat_preflight_circuit_breaker_failures", 5))
    cooldown = max(1, _int_setting(cfg, "chat_preflight_circuit_breaker_seconds", 60))
    if _CHAT_FAILURE_COUNT >= threshold:
        _CHAT_CIRCUIT_OPEN_UNTIL = time.time() + cooldown


def _record_chat_success() -> None:
    global _CHAT_FAILURE_COUNT, _CHAT_CIRCUIT_OPEN_UNTIL
    _CHAT_FAILURE_COUNT = 0
    _CHAT_CIRCUIT_OPEN_UNTIL = 0.0


def is_chat_preflight_enabled() -> bool:
    return _bool_setting(_llm_config(), "chat_preflight_enabled", True)


def is_chat_status_stream_enabled() -> bool:
    return _bool_setting(_llm_config(), "chat_status_stream_enabled", True)


def run_chat_preflight(content: str, history_messages: list[dict[str, str]] | None = None, attachment_context: str = "") -> dict:
    cfg = _llm_config()
    original = str(content or "").strip()
    started = time.monotonic()

    if not is_chat_preflight_enabled():
        return _chat_fallback(original, "chat preflight disabled", 0, summary="")
    if _bool_setting(cfg, "chat_preflight_circuit_breaker", True) and time.time() < _CHAT_CIRCUIT_OPEN_UNTIL:
        return _chat_fallback(original, "local small model circuit breaker open", 0)

    max_prompt_chars = max(200, _int_setting(cfg, "local_small_model_max_prompt_chars", _DEFAULT_MAX_PROMPT_CHARS))
    max_output_chars = max(100, _int_setting(cfg, "local_small_model_max_output_chars", _DEFAULT_MAX_OUTPUT_CHARS))
    timeout_ms = max(100, _int_setting(cfg, "chat_preflight_timeout_ms", 2500))
    summary_enabled = _bool_setting(cfg, "chat_preflight_summary_enabled", True)
    base_url = str(cfg.get("prompt_model_url") or "http://127.0.0.1:8001").rstrip("/")
    api_url = str(cfg.get("local_small_model_api_url") or "").strip()
    model_name = _model_name(cfg)

    history_lines = []
    for item in history_messages or []:
        role = str(item.get("role") or "").strip() or "user"
        msg_text = str(item.get("content") or "").strip()
        if msg_text:
            history_lines.append(f"{role}: {msg_text[:300]}")
    prompt = (
        "请把下面聊天请求整理成给主模型参考的任务理解和回答策略。"
        "只输出简短结果，不要输出思考过程，不要生成最终答案。\n\n"
        f"最近对话：\n{chr(10).join(history_lines[-6:])}\n\n"
        f"附件摘要：\n{str(attachment_context or '').strip()[:800]}\n\n"
        f"用户原始输入：\n{original}"
    )[:max_prompt_chars]

    try:
        if api_url:
            response = requests.post(
                api_url,
                json=_chat_completion_body(prompt, model_name, min(256, max_output_chars), max_output_chars),
                timeout=timeout_ms / 1000,
            )
        else:
            response = requests.post(
                f"{base_url}/v1/completions",
                json={"prompt": prompt, "stream": False, "max_tokens": min(256, max_output_chars)},
                timeout=timeout_ms / 1000,
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        if getattr(response, "status_code", 500) >= 400:
            _record_chat_failure(cfg)
            return _chat_fallback(original, f"local small model http {response.status_code}", latency_ms)
        payload = response.json() if getattr(response, "content", None) else {}
        refined = clean_local_small_output(_extract_completion_text(payload))[:max_output_chars]
        if not refined:
            _record_chat_failure(cfg)
            return _chat_fallback(original, "local small model empty output", latency_ms)
        _record_chat_success()
        return {
            "summary": _short_summary(refined) if summary_enabled else "",
            "refined_prompt": refined,
            "original_input": original,
            "fallback": False,
            "error": "",
            "latency_ms": latency_ms,
        }
    except requests.exceptions.Timeout:
        latency_ms = int((time.monotonic() - started) * 1000)
        _record_chat_failure(cfg)
        return _chat_fallback(original, "timeout", latency_ms)
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        _record_chat_failure(cfg)
        error_text = str(exc) or exc.__class__.__name__
        logger.info("chat preflight fallback: %s", error_text)
        return _chat_fallback(original, error_text, latency_ms)
