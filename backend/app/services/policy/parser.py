"""Response parsing and field cleaning for the gov.cn policy library search.

Pure functions only: no I/O, no logging of payloads. Facts about the source
(verified by the task owner, see backend/docs/policy-api.md):

- results live in ``searchVO.catMap.{gongwen|bumenfile|otherfile|gongbao}.listVO``,
  not in ``data``;
- ``searchVO.totalCount`` is always 0 and must not be used;
- whether another page exists is decided by "returned count == n";
- ``pcode`` is the document number (``fwzh`` is usually empty);
- ``pubtimeStr`` looks like ``2024.01.16`` and may be missing; ``ptime`` is a
  millisecond timestamp;
- ``summary`` is only the opening of the text, never the full content.
"""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

SOURCE = "gov_zcwjk"
CATEGORIES = ("gongwen", "bumenfile", "otherfile", "gongbao")

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_DATE_RE = re.compile(r"(\d{4})\s*[.\-/年]\s*(\d{1,2})\s*[.\-/月]\s*(\d{1,2})")
_CHINA_TZ = timezone(timedelta(hours=8))


class PolicyParseError(ValueError):
    """The response does not have the expected structure."""


@dataclass(frozen=True)
class PolicyRecord:
    title: str
    url: str
    source: str = SOURCE
    remote_id: str | None = None
    doc_number: str | None = None
    issuer: str | None = None
    publish_date: str | None = None
    category: str | None = None
    subject: str | None = None
    summary: str | None = None
    index_no: str | None = None
    content_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParsedPage:
    records: list[PolicyRecord] = field(default_factory=list)
    #: Every listVO entry returned by the server, before dedupe/validation.
    raw_count: int = 0
    skipped: int = 0


def clean_text(value) -> str:
    """Strip highlight/markup tags, decode entities, collapse whitespace."""
    if value is None:
        return ""
    text = _BR_RE.sub(" ", str(value))
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    return _SPACE_RE.sub(" ", text).strip()


def _optional(value) -> str | None:
    cleaned = clean_text(value)
    return cleaned or None


def normalize_date(pubtime_str, ptime) -> str | None:
    """Return YYYY-MM-DD from ``pubtimeStr`` or, failing that, from ``ptime`` (ms)."""
    if pubtime_str:
        match = _DATE_RE.search(str(pubtime_str))
        if match:
            year, month, day = (int(x) for x in match.groups())
            try:
                return datetime(year, month, day).strftime("%Y-%m-%d")
            except ValueError:
                pass
    if ptime not in (None, ""):
        try:
            millis = int(float(ptime))
        except (TypeError, ValueError):
            return None
        if millis <= 0:
            return None
        return datetime.fromtimestamp(millis / 1000, tz=_CHINA_TZ).strftime("%Y-%m-%d")
    return None


def content_hash(title: str, doc_number, issuer, publish_date, summary) -> str:
    joined = "␟".join(str(x or "") for x in (title, doc_number, issuer, publish_date, summary))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def parse_item(item: dict, category: str) -> PolicyRecord | None:
    """Clean one listVO entry. Returns None when it has no usable title or url."""
    if not isinstance(item, dict):
        return None
    title = clean_text(item.get("title"))
    url = str(item.get("url") or "").strip()
    if not title or not url:
        return None
    doc_number = _optional(item.get("pcode"))
    issuer = _optional(item.get("puborg"))
    publish_date = normalize_date(item.get("pubtimeStr"), item.get("ptime"))
    summary = _optional(item.get("summary"))
    remote_id = item.get("id")
    return PolicyRecord(
        title=title,
        url=url,
        remote_id=str(remote_id) if remote_id not in (None, "") else None,
        doc_number=doc_number,
        issuer=issuer,
        publish_date=publish_date,
        category=category,
        subject=_optional(item.get("childtype")),
        summary=summary,
        index_no=_optional(item.get("index")),
        content_hash=content_hash(title, doc_number, issuer, publish_date, summary),
    )


def _search_vo(payload) -> dict:
    if not isinstance(payload, dict):
        raise PolicyParseError("响应不是 JSON 对象")
    vo = payload.get("searchVO")
    if vo is None and isinstance(payload.get("data"), dict):
        vo = payload["data"].get("searchVO")
    if not isinstance(vo, dict):
        raise PolicyParseError("响应缺少 searchVO")
    cat_map = vo.get("catMap")
    if not isinstance(cat_map, dict):
        raise PolicyParseError("响应缺少 searchVO.catMap")
    return cat_map


def parse_search_response(payload) -> ParsedPage:
    """Parse one search page. Duplicate urls across categories keep the first."""
    cat_map = _search_vo(payload)
    page = ParsedPage()
    seen: set[str] = set()
    for category in CATEGORIES:
        bucket = cat_map.get(category) or {}
        entries = bucket.get("listVO") if isinstance(bucket, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            page.raw_count += 1
            record = parse_item(entry, category)
            if record is None or record.url in seen:
                page.skipped += 1
                continue
            seen.add(record.url)
            page.records.append(record)
    return page


def has_next_page(raw_count: int, per_page: int) -> bool:
    """totalCount is unusable; a full page means there may be another one."""
    return per_page > 0 and raw_count >= per_page
