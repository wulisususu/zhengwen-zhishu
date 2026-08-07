"""重试与降级工具 — docs_pipeline v3.

子进程隔离架构下：
- Worker crash (HTTP 500) → 服务器存活，直接重试
- Connection refused (HTTP conn error) → 服务器挂了，需重启再重试
- 指数退避: 2s → 4s → 8s → 16s → 32s
"""
import asyncio
import logging
import time
from typing import Callable, Awaitable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ── 退避参数 ──
BASE_DELAY = 2.0
MAX_DELAY = 60.0
BACKOFF_MULTIPLIER = 2.0

# 需要重启服务器的错误（连接级别）
RESTART_NEEDED_ERRORS = (
    ConnectionRefusedError,
    ConnectionResetError,
    BrokenPipeError,
    OSError,
)

try:
    import requests as _requests
    RESTART_NEEDED_ERRORS = RESTART_NEEDED_ERRORS + (
        _requests.exceptions.ConnectionError,
    )
except ImportError:
    pass


def backoff_delay(attempt: int) -> float:
    """计算第 attempt 次重试的等待秒数（指数退避）."""
    d = BASE_DELAY * (BACKOFF_MULTIPLIER ** attempt)
    return min(d, MAX_DELAY)


def is_restart_needed(error: Exception) -> bool:
    """连接级别错误→需要重启服务器；应用级错误→只需重试."""
    if isinstance(error, RESTART_NEEDED_ERRORS):
        return True
    error_str = str(error).lower()
    conn_keywords = ("connection refused", "connection reset",
                     "remote end closed", "broken pipe",
                     "no route to host", "connection aborted")
    return any(kw in error_str for kw in conn_keywords)


async def async_retry_with_restart(
    fn: Callable[[], Awaitable[T]],
    max_retries: int = 10,
    restart_fn=None,
    label: str = "",
    on_retry: Callable[[int, int, Exception], Awaitable[None]] | None = None,
) -> tuple[T | None, int, bool]:
    """异步重试，连接错误时重启 3B 服务器，应用错误直接重试.

    Returns:
        (result, retries_used, success)
    """
    if restart_fn is None:
        from app.docs_pipeline.core import _restart_3b
        restart_fn = _restart_3b

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            result = await fn()
            if attempt > 0:
                logger.info("%s 第 %d 次重试成功", label, attempt)
            return result, attempt, True
        except RESTART_NEEDED_ERRORS as e:
            last_error = e
            if attempt < max_retries:
                delay = backoff_delay(attempt)
                logger.warning(
                    "%s 连接失败 (attempt %d/%d): %s — 重启服务器后 %.1fs 重试",
                    label, attempt + 1, max_retries + 1, e, delay)
                if on_retry is not None:
                    await on_retry(attempt + 1, max_retries + 1, e)
                await asyncio.to_thread(restart_fn)
                await asyncio.sleep(delay)
            else:
                logger.error("%s 所有 %d 次尝试均连接失败: %s",
                             label, max_retries + 1, e)
        except Exception as e:
            last_error = e
            error_str = str(e)[:200]
            if attempt < max_retries:
                delay = backoff_delay(attempt)
                logger.warning(
                    "%s 请求失败 (attempt %d/%d): %s — %.1fs 后重试（不重启）",
                    label, attempt + 1, max_retries + 1, error_str, delay)
                if on_retry is not None:
                    await on_retry(attempt + 1, max_retries + 1, e)
                await asyncio.sleep(delay)
            else:
                logger.error("%s 所有 %d 次尝试均失败: %s",
                             label, max_retries + 1, error_str)

    return None, max_retries, False


async def retry_render(
    render_fn: Callable[[], Awaitable[bool]],
    max_retries: int = 2,
) -> tuple[bool, int]:
    """DOCX 渲染重试（不重启模型）."""
    for attempt in range(max_retries + 1):
        try:
            ok = await render_fn()
            if ok:
                return True, attempt
        except Exception as e:
            logger.warning("Render attempt %d failed: %s", attempt + 1, e)
        if attempt < max_retries:
            await asyncio.sleep(1)
    return False, max_retries
