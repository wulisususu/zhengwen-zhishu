"""Tunable settings for policy retrieval, read from config.yaml ``policy:``.

The search address is never hard-coded: without ``policy.base_url`` the
service runs local-only and reports POLICY_NOT_CONFIGURED for remote work.
The fetch allowlist defaults to the two gov.cn hosts named in the task; any
department site must be added explicitly via ``policy.fetch.extra_allowed_hosts``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("app.policy")

BACKEND_ROOT = Path(__file__).resolve().parents[3]

#: Hard ceilings regardless of configuration.
MAX_PAGES_LIMIT = 20
MAX_PER_PAGE = 50
MAX_FETCH_BYTES_LIMIT = 10 * 1024 * 1024
MAX_REDIRECTS_LIMIT = 2

DEFAULT_ALLOWED_HOSTS = ("sousuo.www.gov.cn", "www.gov.cn")


@dataclass(frozen=True)
class FetchSettings:
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS
    timeout_seconds: float = 15.0
    max_bytes: int = MAX_FETCH_BYTES_LIMIT
    max_redirects: int = MAX_REDIRECTS_LIMIT


@dataclass(frozen=True)
class PolicySettings:
    enabled: bool = False
    base_url: str = ""
    timeout_seconds: float = 15.0
    retry: int = 2
    min_interval_seconds: float = 1.0
    cache_ttl_seconds: float = 300.0
    max_pages: int = MAX_PAGES_LIMIT
    db_path: Path = BACKEND_ROOT / "data" / "policy.db"
    fetch: FetchSettings = field(default_factory=FetchSettings)

    @property
    def remote_configured(self) -> bool:
        return self.enabled and bool(self.base_url)


def _number(raw, default, cast, minimum, maximum):
    try:
        value = cast(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _hosts(raw) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(h).strip().lower().rstrip(".") for h in raw if str(h).strip())


def fetch_settings_from_mapping(section: dict | None) -> FetchSettings:
    s = section or {}
    base = _hosts(s.get("allowed_hosts")) or DEFAULT_ALLOWED_HOSTS
    extra = _hosts(s.get("extra_allowed_hosts"))
    hosts = tuple(dict.fromkeys(base + extra))
    return FetchSettings(
        allowed_hosts=hosts,
        timeout_seconds=_number(s.get("timeout_seconds", 15), 15.0, float, 1.0, 15.0),
        max_bytes=_number(s.get("max_bytes", MAX_FETCH_BYTES_LIMIT), MAX_FETCH_BYTES_LIMIT, int, 1024, MAX_FETCH_BYTES_LIMIT),
        max_redirects=_number(s.get("max_redirects", MAX_REDIRECTS_LIMIT), MAX_REDIRECTS_LIMIT, int, 0, MAX_REDIRECTS_LIMIT),
    )


def settings_from_mapping(section: dict | None) -> PolicySettings:
    s = section or {}
    db_path = Path(str(s.get("db_path") or "data/policy.db")).expanduser()
    if not db_path.is_absolute() and str(db_path) != ":memory:":
        db_path = BACKEND_ROOT / db_path
    return PolicySettings(
        enabled=bool(s.get("enabled", False)),
        base_url=str(s.get("base_url") or "").strip(),
        timeout_seconds=_number(s.get("timeout_seconds", 15), 15.0, float, 1.0, 60.0),
        retry=_number(s.get("retry", 2), 2, int, 0, 2),
        min_interval_seconds=_number(s.get("min_interval_seconds", 1.0), 1.0, float, 1.0, 60.0),
        cache_ttl_seconds=_number(s.get("cache_ttl_seconds", 300), 300.0, float, 0.0, 86400.0),
        max_pages=_number(s.get("max_pages", MAX_PAGES_LIMIT), MAX_PAGES_LIMIT, int, 1, MAX_PAGES_LIMIT),
        db_path=db_path,
        fetch=fetch_settings_from_mapping(s.get("fetch") if isinstance(s.get("fetch"), dict) else None),
    )


def load_settings() -> PolicySettings:
    try:
        from app.config import get_config

        cfg = get_config() or {}
    except Exception as exc:  # config.yaml missing or unreadable: stay local-only
        logger.warning("policy settings unavailable, running local-only: %s", type(exc).__name__)
        cfg = {}
    return settings_from_mapping(cfg.get("policy") if isinstance(cfg, dict) else None)
