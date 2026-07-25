"""PI Agent 基础客户端：HTTP/SSE 通信、健康检查、超时重试."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import AsyncGenerator, Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300
HEALTH_CHECK_TIMEOUT = 3.0
HEALTH_CHECK_CACHE_TTL = 30.0
DEFAULT_AUTH_TOKEN = os.getenv("PI_AGENT_TOKEN", "pi-agent-local-token")


class AgentUnavailable(Exception):
    """Agent 不可用时抛出."""


class AgentTimeout(Exception):
    """Agent 请求超时."""


def _clean_delta(text: str) -> str:
    """Clean 35B model output to prevent code/JSON leaking to frontend."""
    if not text:
        return text
    import re
    import logging
    logger = logging.getLogger(__name__)
    text = text.replace('<|endoftext|>', '').replace('<|im_start|>', '').replace('<|im_end|>', '')
    text = text.replace('[[FINAL]]', '')
    text = re.sub(r'</?think>', '', text, flags=re.IGNORECASE)
    stripped = text.strip()
    if stripped.startswith('{') and ('function' in stripped or 'arguments' in stripped or 'toolCall' in stripped):
        logger.warning('_clean_delta: blocked JSON tool-call fragment: %.80s', stripped)
        return ''
    text = re.sub(r'MEDIA:\S+', '', text)
    text = re.sub(r'\[embed.*?\]', '', text)
    return text


async def health_check(url: str, timeout: float = HEALTH_CHECK_TIMEOUT) -> bool:
    """检测 agent 是否存活."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=timeout)
            return resp.status_code < 500
    except Exception:
        return False


class PiAgentClient:
    """PI Agent HTTP/SSE 客户端基类."""

    def __init__(self, base_url: str, timeout: float = DEFAULT_TIMEOUT,
                 auth_token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.auth_token = auth_token or DEFAULT_AUTH_TOKEN
        self._healthy: bool | None = None
        self._last_health_check: float = 0.0

    def _headers(self) -> dict:
        """构建请求头，含 Authorization."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.auth_token}",
        }

    async def is_healthy(self) -> bool:
        """带缓存的健康检查."""
        now = asyncio.get_event_loop().time()
        if self._healthy is not None and (now - self._last_health_check) < HEALTH_CHECK_CACHE_TTL:
            return self._healthy
        self._healthy = await health_check(f"{self.base_url}/health")
        self._last_health_check = now
        return self._healthy

    async def post_json(self, path: str, payload: dict) -> dict:
        """POST JSON 请求，返回解析后的 JSON."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def post_sse_stream(
        self, path: str, payload: dict
    ) -> AsyncGenerator[str, None]:
        """POST SSE 流式请求，逐帧 yield."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}{path}",
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        yield line
