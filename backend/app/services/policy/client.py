"""HTTP client for the gov.cn policy library search.

Network rules (T1):
- timeout from settings (default 15s);
- at most ``retry`` (<= 2) retries, only on timeout or HTTP 5xx;
- at least ``min_interval_seconds`` (>= 1s) between requests, one at a time;
- identical (query, page, per_page) served from memory for ``cache_ttl_seconds``;
- the egress mode from app.services.model_policy is checked before every
  request: only ``cloud_allowed`` may reach gov.cn.
Logs carry query, page, elapsed ms, count and error type only, never bodies.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import requests

from app.services.policy import errors
from app.services.policy.errors import PolicyError
from app.services.policy.parser import PolicyParseError, PolicyRecord, has_next_page, parse_search_response
from app.services.policy.settings import MAX_PER_PAGE, PolicySettings

logger = logging.getLogger("app.policy.client")

SEARCH_TYPE = "zhengcelibrary"
USER_AGENT = "InNetBox-PolicyRetrieval/1.0 (low-frequency, cached)"


def egress_mode() -> str:
    """Current egress mode; an invalid configuration counts as blocked."""
    try:
        from app.services.model_policy import get_mode

        return get_mode()
    except Exception as exc:
        logger.warning("egress mode unreadable, treating as offline: %s", type(exc).__name__)
        return "offline"


def remote_allowed(mode: str) -> bool:
    return mode == "cloud_allowed"


@dataclass
class PageResult:
    query: str
    page: int
    per_page: int
    records: list[PolicyRecord] = field(default_factory=list)
    raw_count: int = 0
    has_next: bool = False
    from_cache: bool = False
    elapsed_ms: int = 0


class PolicyClient:
    def __init__(
        self,
        settings: PolicySettings,
        *,
        http_get: Callable | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        mode_provider: Callable[[], str] = egress_mode,
    ):
        self.settings = settings
        # Resolved at call time so tests can monkeypatch requests.get.
        self._http_get = http_get
        self._sleep = sleep
        self._clock = clock
        self._mode_provider = mode_provider
        self._lock = threading.Lock()
        self._last_request_at: float | None = None
        self._cache: dict[tuple[str, int, int], tuple[float, PageResult]] = {}

    @staticmethod
    def normalize_page(page) -> int:
        """p is 1-based; p=0 makes the server ignore n, so never send it."""
        try:
            return max(1, int(page))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def normalize_per_page(per_page) -> int:
        try:
            return max(1, min(MAX_PER_PAGE, int(per_page)))
        except (TypeError, ValueError):
            return 20

    def _get(self, url, params):
        getter = self._http_get or requests.get
        return getter(url, params=params, timeout=self.settings.timeout_seconds, headers={"User-Agent": USER_AGENT})

    def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        wait = self.settings.min_interval_seconds - (self._clock() - self._last_request_at)
        if wait > 0:
            self._sleep(wait)

    def _cached(self, key) -> PageResult | None:
        hit = self._cache.get(key)
        if not hit:
            return None
        stored_at, result = hit
        if self._clock() - stored_at > self.settings.cache_ttl_seconds:
            self._cache.pop(key, None)
            return None
        return PageResult(**{**result.__dict__, "from_cache": True, "elapsed_ms": 0})

    def search_page(self, query: str, page=1, per_page=20) -> PageResult:
        """Fetch one page. Raises PolicyError with an explicit code on failure."""
        query = (query or "").strip()
        page = self.normalize_page(page)
        per_page = self.normalize_per_page(per_page)
        if not self.settings.remote_configured:
            raise PolicyError(errors.NOT_CONFIGURED, "未配置政策检索数据源（config.yaml policy.enabled / policy.base_url）。")
        mode = self._mode_provider()
        if not remote_allowed(mode):
            raise PolicyError(errors.EGRESS_BLOCKED, f"当前出口模式为 {mode}，不允许访问外部政策数据源。")

        key = (query, page, per_page)
        with self._lock:
            cached = self._cached(key)
            if cached:
                logger.info("policy search cache hit q=%r p=%d n=%d count=%d", query, page, per_page, len(cached.records))
                return cached
            result = self._fetch(query, page, per_page)
            self._cache[key] = (self._clock(), result)
            return result

    def _fetch(self, query: str, page: int, per_page: int) -> PageResult:
        params = {"t": SEARCH_TYPE, "q": query, "p": page, "n": per_page}
        attempts = 1 + self.settings.retry
        started = self._clock()
        last_error: PolicyError | None = None
        for attempt in range(1, attempts + 1):
            self._throttle()
            self._last_request_at = self._clock()
            try:
                response = self._get(self.settings.base_url, params)
            except requests.Timeout:
                last_error = PolicyError(errors.REMOTE_TIMEOUT, "政策数据源响应超时。")
                logger.warning("policy search timeout q=%r p=%d attempt=%d", query, page, attempt)
                continue
            except requests.RequestException as exc:
                logger.warning("policy search request failed q=%r p=%d error=%s", query, page, type(exc).__name__)
                raise PolicyError(errors.REMOTE_UNAVAILABLE, "无法连接政策数据源。") from None

            status = getattr(response, "status_code", 0)
            if status >= 500:
                last_error = PolicyError(errors.REMOTE_HTTP_ERROR, f"政策数据源返回 HTTP {status}。")
                logger.warning("policy search http %d q=%r p=%d attempt=%d", status, query, page, attempt)
                continue
            if status != 200:
                logger.warning("policy search http %d q=%r p=%d", status, query, page)
                raise PolicyError(errors.REMOTE_HTTP_ERROR, f"政策数据源返回 HTTP {status}。")
            try:
                parsed = parse_search_response(response.json())
            except (ValueError, PolicyParseError) as exc:
                logger.warning("policy search bad response q=%r p=%d error=%s", query, page, type(exc).__name__)
                raise PolicyError(errors.REMOTE_BAD_RESPONSE, "政策数据源返回了无法识别的数据。") from None

            elapsed_ms = int((self._clock() - started) * 1000)
            logger.info(
                "policy search ok q=%r p=%d n=%d elapsed_ms=%d count=%d raw=%d",
                query, page, per_page, elapsed_ms, len(parsed.records), parsed.raw_count,
            )
            return PageResult(
                query=query,
                page=page,
                per_page=per_page,
                records=parsed.records,
                raw_count=parsed.raw_count,
                has_next=has_next_page(parsed.raw_count, per_page),
                elapsed_ms=elapsed_ms,
            )
        assert last_error is not None
        raise last_error
