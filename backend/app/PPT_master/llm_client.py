"""GLM-5.2 API client: direct httpx + SSE streaming."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import AsyncGenerator

import httpx

logger = logging.getLogger(__name__)

GLM_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
GLM_API_KEY = os.getenv("GLM5_API_KEY", "")

DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 8192
RETRY_DELAYS = [5, 10, 15]  # seconds, exponential backoff


class GLMApiError(Exception):
    """Raised when GLM API returns an error after all retries."""


def _parse_sse_chunk(line: str) -> str | None:
    """Parse a single SSE line from GLM chat/completions.
    Returns delta text content, '__DONE__', or None.
    Handles both 'content' and 'reasoning_content' delta fields.
    """
    if not line.startswith("data: "):
        return None
    data_str = line[6:]
    if data_str == "[DONE]":
        return "__DONE__"
    try:
        obj = json.loads(data_str)
        choices = obj.get("choices", [])
        if not choices:
            return None
        delta = choices[0].get("delta", {})
        # GLM-5.2 may output reasoning_content before content
        # We collect content only (skip reasoning), but also check reasoning_content as fallback
        content = delta.get("content", "")
        if content:
            return content
        # If thinking is disabled, reasoning_content won't appear.
        # If it somehow appears, skip it — we want the final answer.
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return None


async def call_glm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = 3,
) -> AsyncGenerator[str, None]:
    """Call GLM-5.2 chat/completions with SSE streaming.

    Retries on failure with exponential backoff: 5s, 10s, 15s.
    Yields incremental text delta strings.
    Raises GLMApiError if all retries exhausted.

    Note: thinking/reasoning is DISABLED to get direct output.
    """
    if not GLM_API_KEY:
        raise GLMApiError("GLM5_API_KEY not set in environment")

    # 模型出口策略：intranet / offline 下禁止直连云端 GLM，明确报错而不是静默失败
    from app.services.model_policy import ModelPolicyError, guard_model_url

    try:
        guard_model_url(GLM_API_URL, purpose="ppt_glm")
    except ModelPolicyError as exc:
        logger.warning("PPT 规划被模型出口策略拒绝：%s", exc)
        raise GLMApiError(str(exc)) from exc

    payload = {
        "model": "glm-5.2",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
    }
    headers = {
        "Authorization": f"Bearer {GLM_API_KEY}",
        "Content-Type": "application/json",
    }

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=900) as client:
                async with client.stream(
                    "POST", GLM_API_URL, json=payload, headers=headers
                ) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        raise GLMApiError(
                            f"GLM API HTTP {resp.status_code}: {body.decode()[:500]}"
                        )
                    got_content = False
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        text = _parse_sse_chunk(line)
                        if text == "__DONE__":
                            return
                        if text:
                            got_content = True
                            yield text
                    if not got_content:
                        raise GLMApiError(
                            "GLM returned empty response (no content delta). "
                            "The model may have spent all tokens on reasoning."
                        )
                    return
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError,
                httpx.ReadTimeout, httpx.ConnectTimeout, GLMApiError) as e:
            last_error = e
            if attempt < max_retries:
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    "GLM API call failed (attempt %d/%d), retrying in %ds: %s",
                    attempt + 1, max_retries, delay, str(e)[:200]
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "GLM API exhausted %d retries: %s", max_retries, str(e)[:200]
                )

    raise GLMApiError(
        f"GLM API call failed after {max_retries} retries: {str(last_error)[:300]}"
    )
