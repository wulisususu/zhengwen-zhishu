"""PolicyRetrievalService: the facade used by the router.

No method raises to the caller. Failures come back as ``error`` objects with
a stable code (app.services.policy.errors), and partial results are kept.

``source`` in search results:
- ``local``         local store was enough, no remote request made;
- ``local+remote``  local store topped up from gov.cn (results upserted);
- ``local_only``    remote access not permitted (egress mode, disabled or not
                    configured); only local results returned.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable

from app.services.policy import errors
from app.services.policy.client import PolicyClient, egress_mode, remote_allowed
from app.services.policy.errors import PolicyError
from app.services.policy.settings import MAX_PER_PAGE, PolicySettings, load_settings
from app.services.policy.store import PolicyStore, StoredPolicy, utc_now

logger = logging.getLogger("app.policy")

MAX_QUERY_LENGTH = 100
MAX_LIMIT = 50


@dataclass
class PolicyHit:
    id: int
    title: str
    doc_number: str | None
    issuer: str | None
    publish_date: str | None
    category: str | None
    subject: str | None
    url: str
    summary: str | None
    verified_status: str
    fetched_at: str

    @classmethod
    def from_stored(cls, doc: StoredPolicy) -> "PolicyHit":
        return cls(
            id=doc.id, title=doc.title, doc_number=doc.doc_number, issuer=doc.issuer,
            publish_date=doc.publish_date, category=doc.category, subject=doc.subject,
            url=doc.url, summary=doc.summary, verified_status=doc.verified_status, fetched_at=doc.fetched_at,
        )

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class SearchResult:
    query: str
    hits: list[PolicyHit] = field(default_factory=list)
    source: str = "local"
    egress_mode: str = ""
    remote_fetched: int = 0
    error: dict | None = None

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "source": self.source,
            "egress_mode": self.egress_mode,
            "remote_fetched": self.remote_fetched,
            "hits": [h.to_dict() for h in self.hits],
            "error": self.error,
        }


@dataclass
class SyncResult:
    topic: str
    pages_requested: int
    per_page: int
    pages_fetched: int = 0
    fetched: int = 0
    inserted: int = 0
    #: url already known with different content -> stored as a new version (old one kept)
    new_versions: int = 0
    unchanged: int = 0
    stopped_reason: str = ""
    error: dict | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _validate_text(value, label: str) -> tuple[str, dict | None]:
    text = (value or "").strip() if isinstance(value, str) else ""
    if not text:
        return "", PolicyError(errors.INVALID_QUERY, f"{label}不能为空。").to_dict()
    if len(text) > MAX_QUERY_LENGTH:
        return "", PolicyError(errors.INVALID_QUERY, f"{label}不能超过 {MAX_QUERY_LENGTH} 个字符。").to_dict()
    return text, None


class PolicyRetrievalService:
    def __init__(
        self,
        settings: PolicySettings,
        store: PolicyStore,
        client: PolicyClient,
        mode_provider: Callable[[], str] = egress_mode,
    ):
        self.settings = settings
        self.store = store
        self.client = client
        self._mode_provider = mode_provider

    def _remote_block(self) -> tuple[str, dict | None]:
        """(mode, error) — error is set when remote access is not permitted."""
        mode = self._mode_provider()
        if not remote_allowed(mode):
            return mode, PolicyError(errors.EGRESS_BLOCKED, f"当前出口模式为 {mode}，仅返回本地政策库结果。").to_dict()
        if not self.settings.enabled:
            return mode, PolicyError(errors.DISABLED, "政策联网检索未启用（policy.enabled=false），仅返回本地结果。").to_dict()
        if not self.settings.base_url:
            return mode, PolicyError(errors.NOT_CONFIGURED, "未配置 policy.base_url，仅返回本地结果。").to_dict()
        return mode, None

    def _upsert_all(self, records) -> dict[str, int]:
        counts = {"inserted": 0, "new_version": 0, "unchanged": 0}
        fetched_at = utc_now()
        for record in records:
            counts[self.store.upsert(record, fetched_at)] += 1
        return counts

    def search(self, query, limit: int = 10) -> SearchResult:
        text, invalid = _validate_text(query, "检索词")
        result = SearchResult(query=text)
        if invalid:
            result.error = invalid
            return result
        limit = max(1, min(MAX_LIMIT, int(limit or 10)))
        try:
            local = self.store.search_local(text, limit)
            result.hits = [PolicyHit.from_stored(d) for d in local]
            mode, blocked = self._remote_block()
            result.egress_mode = mode
            if len(local) >= limit:
                result.source = "local"
                return result
            if blocked:
                result.source = "local_only"
                result.error = blocked
                return result

            try:
                page = self.client.search_page(text, page=1, per_page=min(MAX_PER_PAGE, max(limit, 10)))
            except PolicyError as exc:
                result.source = "local"
                result.error = exc.to_dict()
                return result
            self._upsert_all(page.records)
            result.remote_fetched = len(page.records)
            result.source = "local+remote"
            known = {h.url for h in result.hits}
            for record in page.records:
                if len(result.hits) >= limit:
                    break
                if record.url in known:
                    continue
                stored = self.store.get_by_url(record.url)
                if stored:
                    result.hits.append(PolicyHit.from_stored(stored))
                    known.add(record.url)
            return result
        except Exception as exc:  # never leak raw exceptions to the router
            logger.error("policy search failed q=%r error=%s", text, type(exc).__name__)
            result.error = PolicyError(errors.INTERNAL_ERROR, "政策检索失败，请稍后重试。").to_dict()
            return result

    def sync_topic(self, topic, pages: int = 3, per_page: int = 20) -> SyncResult:
        text, invalid = _validate_text(topic, "同步主题")
        pages = max(1, min(self.settings.max_pages, int(pages or 1)))
        per_page = PolicyClient.normalize_per_page(per_page)
        result = SyncResult(topic=text, pages_requested=pages, per_page=per_page)
        if invalid:
            result.error = invalid
            return result
        try:
            _mode, blocked = self._remote_block()
            if blocked:
                result.error = blocked
                result.stopped_reason = "remote_not_permitted"
                return result
            for page_no in range(1, pages + 1):
                try:
                    page = self.client.search_page(text, page=page_no, per_page=per_page)
                except PolicyError as exc:
                    result.error = exc.to_dict()
                    result.stopped_reason = "error"
                    return result
                result.pages_fetched += 1
                result.fetched += len(page.records)
                counts = self._upsert_all(page.records)
                result.inserted += counts["inserted"]
                result.new_versions += counts["new_version"]
                result.unchanged += counts["unchanged"]
                if not page.has_next:
                    result.stopped_reason = "last_page"
                    return result
            result.stopped_reason = "page_limit"
            return result
        except Exception as exc:
            logger.error("policy sync failed topic=%r error=%s", text, type(exc).__name__)
            result.error = PolicyError(errors.INTERNAL_ERROR, "政策同步失败，请稍后重试。").to_dict()
            result.stopped_reason = "error"
            return result

    def list_documents(self, page: int = 1, page_size: int = 20) -> dict:
        page = max(1, int(page or 1))
        page_size = max(1, min(MAX_LIMIT, int(page_size or 20)))
        try:
            docs, total = self.store.list_documents(page, page_size)
            return {"items": [PolicyHit.from_stored(d).to_dict() for d in docs], "total": total, "page": page, "page_size": page_size, "error": None}
        except Exception as exc:
            logger.error("policy list failed error=%s", type(exc).__name__)
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "error": PolicyError(errors.STORE_ERROR, "读取本地政策库失败。").to_dict()}

    def get_document(self, doc_id: int) -> tuple[dict | None, dict | None]:
        try:
            doc = self.store.get(int(doc_id))
            return (PolicyHit.from_stored(doc).to_dict() if doc else None), None
        except Exception as exc:
            logger.error("policy get failed id=%s error=%s", doc_id, type(exc).__name__)
            return None, PolicyError(errors.STORE_ERROR, "读取本地政策库失败。").to_dict()


_service: PolicyRetrievalService | None = None
_service_lock = threading.Lock()


def get_policy_service() -> PolicyRetrievalService:
    """Process-wide singleton (one client => one rate limiter and cache)."""
    global _service
    with _service_lock:
        if _service is None:
            settings = load_settings()
            _service = PolicyRetrievalService(settings, PolicyStore(settings.db_path), PolicyClient(settings))
        return _service
