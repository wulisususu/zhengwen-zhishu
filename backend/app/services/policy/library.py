"""Policy library facade: import (URL / file), list, clause search, citations, verify.

Output for citations matches web/src/features/gov-office/types.ts ``Citation``
exactly (see backend/docs/policy-api.md for the field mapping):

- ``status`` is one of current / abolished / unverified and comes only from
  the human verification field;
- ``text.before/highlight/after`` is the matched fragment with its context,
  not the whole clause. The match position is recorded at search time and
  carried in the citation id: ``clause:<id>@<start>-<end>``;
- ``previousClause`` / ``nextClause`` come from adjacent ``sequence`` values.

Search returns only ``current`` policies unless other statuses are asked for
explicitly; every hit carries its own status. Methods never raise: failures
come back as ``{"code", "message"}`` errors.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

from app.services.policy import errors
from app.services.policy.clauses import segment
from app.services.policy.errors import PolicyError
from app.services.policy.extract import decode_bytes, extract_file, extract_html
from app.services.policy.fetcher import SafeFetcher
from app.services.policy.parser import normalize_date
from app.services.policy.settings import MAX_FETCH_BYTES_LIMIT, PolicySettings
from app.services.policy.store import STATUSES, ClauseHit, PolicyFilter, PolicyStore, StoredClause, text_hash

logger = logging.getLogger("app.policy.library")

DEFAULT_STATUSES = ("current",)
MAX_TERMS = 5
CONTEXT_BEFORE = 60
CONTEXT_AFTER = 80
NOT_RECORDED = "未录入"
_CITATION_ID = re.compile(r"^clause:(\d+)(?:@(\d+)-(\d+))?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TITLE_SUFFIX = re.compile(r"\s*[_|｜-]\s*中国政府网\s*$")


def _err(code: str, message: str, **extra) -> dict:
    return {"code": code, "message": message, **extra}


def _fetch_error(exc: PolicyError) -> dict:
    return _err(exc.code, exc.message, fallback=errors.MANUAL_UPLOAD_HINT)


def citation_id(clause_id: int, start: int | None = None, end: int | None = None) -> str:
    return f"clause:{clause_id}" if start is None else f"clause:{clause_id}@{start}-{end}"


def parse_citation_id(value: str) -> tuple[int, int | None, int | None] | None:
    m = _CITATION_ID.match(str(value or "").strip())
    if not m:
        return None
    clause_id = int(m.group(1))
    if m.group(2) is None:
        return clause_id, None, None
    start, end = int(m.group(2)), int(m.group(3))
    return (clause_id, start, end) if end > start else (clause_id, None, None)


def locate(content: str, query: str, terms: list[str]) -> tuple[int, int] | None:
    """Position of the full query, else of the earliest matching term (case-insensitive)."""
    haystack = content.lower()
    whole = query.strip().lower()
    if whole and whole in haystack:
        start = haystack.index(whole)
        return start, start + len(whole)
    best = None
    for term in terms:
        idx = haystack.find(term.lower())
        if idx >= 0 and (best is None or idx < best[0]):
            best = (idx, idx + len(term))
    return best


def fragment(content: str, start: int | None, end: int | None) -> dict:
    """before / highlight / after around a match; first sentence when no match."""
    if start is None or end is None or end > len(content) or start < 0:
        stop = content.find("。")
        end = stop + 1 if 0 <= stop < CONTEXT_AFTER else min(len(content), CONTEXT_AFTER)
        start = 0
    before = content[max(0, start - CONTEXT_BEFORE):start]
    after = content[end:end + CONTEXT_AFTER]
    return {
        "before": ("…" if start > CONTEXT_BEFORE else "") + before,
        "highlight": content[start:end],
        "after": after + ("…" if end + CONTEXT_AFTER < len(content) else ""),
    }


def clause_label(clause: StoredClause) -> str:
    return clause.article_number or clause.heading or f"第{clause.sequence}段"


def _brief(clause: StoredClause | None, limit: int = 80) -> str | None:
    if clause is None:
        return None
    text = clause.content.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


@dataclass
class ImportRequest:
    url: str | None = None
    filename: str | None = None
    data: bytes | None = None
    source_url: str | None = None
    title: str | None = None
    doc_number: str | None = None
    issuer: str | None = None
    publish_date: str | None = None


class PolicyLibraryService:
    def __init__(self, settings: PolicySettings, store: PolicyStore, fetcher: SafeFetcher):
        self.settings = settings
        self.store = store
        self.fetcher = fetcher

    # ---------- import ----------

    def import_policy(self, req: ImportRequest) -> dict:
        try:
            if bool(req.url) == bool(req.data is not None):
                return {"error": _err(errors.INVALID_QUERY, "请提供 url 或上传文件（二选一）。")}
            meta = {k: v.strip() for k, v in {"title": req.title, "doc_number": req.doc_number, "issuer": req.issuer}.items() if v and v.strip()}
            if req.publish_date:
                date = normalize_date(req.publish_date, None)
                if not date:
                    return {"error": _err(errors.INVALID_QUERY, "publish_date 需为 YYYY-MM-DD。")}
                meta["publish_date"] = date
            if req.url:
                return self._import_url(req.url, meta)
            return self._import_file(req, meta)
        except Exception as exc:
            logger.error("policy import failed error=%s", type(exc).__name__)
            return {"error": _err(errors.INTERNAL_ERROR, "导入失败，已有数据未改动。")}

    def _import_url(self, url: str, meta: dict) -> dict:
        try:
            key = self.fetcher.check_url(url).url
            fetched = self.fetcher.fetch(key)
        except PolicyError as exc:
            return {"error": _fetch_error(exc)}
        doc = extract_html(decode_bytes(fetched.body, fetched.charset)) if "html" in fetched.content_type else None
        if doc is None:
            from app.services.policy.extract import ExtractedDocument

            text = decode_bytes(fetched.body, fetched.charset)
            doc = ExtractedDocument(text="\n".join(line.strip() for line in text.splitlines() if line.strip()))
        if not doc.text:
            return {"error": _err(errors.EMPTY_CONTENT, "页面中没有可识别的正文，未写入任何内容。", fallback=errors.MANUAL_UPLOAD_HINT)}
        page_meta = {
            "title": _TITLE_SUFFIX.sub("", doc.title or "").strip() or None,
            "publish_date": normalize_date(doc.meta.get("PubDate") or doc.meta.get("firstpublishedtime"), None),
        }
        merged = {**{k: v for k, v in page_meta.items() if v}, **meta}
        return self._save(key, merged, doc.text, doc.reliable, "url_import")

    def _import_file(self, req: ImportRequest, meta: dict) -> dict:
        data = req.data or b""
        if len(data) > MAX_FETCH_BYTES_LIMIT:
            return {"error": _err(errors.FETCH_TOO_LARGE, "上传文件超过 10 MB 上限。")}
        try:
            doc = extract_file(req.filename or "", data)
        except PolicyError as exc:
            return {"error": exc.to_dict()}
        if not doc.text:
            return {"error": _err(errors.EMPTY_CONTENT, "文件中没有可识别的正文，未写入任何内容。")}
        if req.source_url:
            try:
                key = self.fetcher.check_url(req.source_url).url  # validated, never fetched
            except PolicyError as exc:
                return {"error": exc.to_dict()}
        else:
            key = f"upload://sha256/{text_hash(doc.text)}"
        merged = {**({"title": doc.title} if doc.title else {}), **meta}
        if not merged.get("title"):
            merged["title"] = (req.filename or "上传文件").rsplit(".", 1)[0]
        result = self._save(key, merged, doc.text, doc.reliable, "file_import", extraction=doc.meta)
        if "pdf_pages" in doc.meta and not result.get("error"):
            result["extraction"] = {k: v for k, v in doc.meta.items() if k != "pdf_pages"}
            result["extraction"]["page_count"] = len(doc.meta["pdf_pages"])
        return result

    def _save(self, key: str, meta: dict, text: str, reliable: bool, origin: str, extraction=None) -> dict:
        drafts = segment(text, reliable=reliable)
        if extraction and extraction.get("pdf_pages"):
            cursor = 0
            boundaries = []
            offset = 0
            for page in extraction["pdf_pages"]:
                boundaries.append((offset, page["page"]))
                offset += len(page["text"]) + 1
            for draft in drafts:
                first_line = draft.content.splitlines()[0]
                position = text.find(first_line, cursor)
                if position < 0:
                    draft.needs_review = True
                    position = cursor
                start_page = next((p for start, p in reversed(boundaries) if start <= position), 1)
                end_page = next((p for start, p in reversed(boundaries) if start <= position + len(draft.content) - 1), start_page)
                draft.page_number = start_page
                draft.source_anchor = f"PDF第{start_page}页" + (f"至第{end_page}页" if end_page != start_page else "") + f" / {draft.source_anchor} / sha256:{extraction['pdf_sha256']}"
                cursor = position + len(first_line)
        if not drafts:
            return {"error": _err(errors.EMPTY_CONTENT, "未识别到正文段落，未写入任何内容。")}
        outcome = self.store.save_import(url=key, meta=meta, content=text, clauses=drafts, origin=origin)
        logger.info(
            "policy import ok origin=%s new_version=%s clauses=%d needs_review=%d",
            origin, outcome.created_new_version, outcome.clause_count, outcome.needs_review_count,
        )
        return {
            "policy": outcome.policy.to_dict(),
            "created_new_version": outcome.created_new_version,
            "superseded_id": outcome.superseded_id,
            "clause_count": outcome.clause_count,
            "needs_review_count": outcome.needs_review_count,
            "error": None,
        }

    # ---------- list ----------

    def list_policies(self, *, keyword="", doc_number="", issuer="", statuses=(), include_history=False, url="", page=1, page_size=20) -> dict:
        bad = [s for s in statuses if s not in STATUSES]
        if bad:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "error": _err(errors.INVALID_STATUS, f"status 只能是 {'/'.join(STATUSES)}。")}
        try:
            flt = PolicyFilter(keyword=keyword.strip(), doc_number=doc_number.strip(), issuer=issuer.strip(),
                               statuses=tuple(statuses), include_history=include_history, url=url.strip())
            docs, total = self.store.list_policies(flt, page, page_size)
            return {"items": [d.to_dict() for d in docs], "total": total, "page": page, "page_size": page_size, "error": None}
        except Exception as exc:
            logger.error("policy list failed error=%s", type(exc).__name__)
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "error": _err(errors.STORE_ERROR, "读取政策库失败。")}

    # ---------- clause search ----------

    def search(self, query: str, *, statuses=None, limit: int = 10, include_history: bool = False) -> dict:
        text = (query or "").strip()
        if not text or len(text) > 100:
            return {"query": text, "hits": [], "error": _err(errors.INVALID_QUERY, "检索词不能为空且不超过 100 个字符。")}
        chosen = tuple(dict.fromkeys(statuses)) if statuses else DEFAULT_STATUSES
        if any(s not in STATUSES for s in chosen):
            return {"query": text, "hits": [], "error": _err(errors.INVALID_STATUS, f"status 只能是 {'/'.join(STATUSES)}。")}
        terms = [t for t in text.split() if t][:MAX_TERMS]
        try:
            rows = self.store.search_clauses(terms, chosen, max(1, min(50, limit)), include_history)
        except Exception as exc:
            logger.error("policy clause search failed error=%s", type(exc).__name__)
            return {"query": text, "statuses": list(chosen), "hits": [], "error": _err(errors.STORE_ERROR, "检索政策条款失败。")}
        hits = []
        for row in rows:
            pos = locate(row.clause.content, text, terms)
            start, end = pos if pos else (None, None)
            hits.append({
                "clause_id": row.clause.id,
                "citation_id": citation_id(row.clause.id, start, end),
                "policy_id": row.policy.id,
                "policy_title": row.policy.title,
                "doc_number": row.policy.doc_number,
                "issuer": row.policy.issuer,
                "publish_date": row.policy.publish_date,
                "status": row.policy.verified_status,
                "version": row.policy.version,
                "is_current_version": bool(row.policy.is_current),
                "article_number": row.clause.article_number,
                "heading": row.clause.heading,
                "clause": clause_label(row.clause),
                "sequence": row.clause.sequence,
                "source_anchor": row.clause.source_anchor,
                "needs_review": bool(row.clause.needs_review),
                "excerpt": fragment(row.clause.content, start, end),
                "match": {"start": start, "end": end} if pos else None,
            })
        logger.info("policy clause search q=%r statuses=%s count=%d", text, ",".join(chosen), len(hits))
        return {"query": text, "statuses": list(chosen), "hits": hits, "error": None}

    # ---------- citations ----------

    def citations(self, ids: list[str]) -> dict:
        parsed = {raw: parse_citation_id(raw) for raw in ids}
        missing = [raw for raw, p in parsed.items() if p is None]
        try:
            rows = self.store.clauses_by_ids(sorted({p[0] for p in parsed.values() if p}))
        except Exception as exc:
            logger.error("policy citations failed error=%s", type(exc).__name__)
            return {"citations": [], "missing": list(ids), "error": _err(errors.STORE_ERROR, "读取政策条款失败。")}
        out = []
        for raw in ids:
            p = parsed.get(raw)
            if p is None:
                continue
            hit = rows.get(p[0])
            if hit is None:
                missing.append(raw)
                continue
            out.append(self._citation(raw, hit, p[1], p[2]))
        return {"citations": out, "missing": missing, "error": None}

    def _status_note(self, hit: ClauseHit) -> str:
        notes = []
        if hit.policy.status_note:
            notes.append(hit.policy.status_note)
        elif hit.policy.verified_status == "unverified":
            notes.append("尚未人工核验，不能作为正式依据。")
        if not hit.policy.is_current and hit.policy.superseded_by:
            newer = self.store.get(hit.policy.superseded_by)
            notes.append(f"该条款所属版本（第 {hit.policy.version} 版）已被第 {newer.version if newer else '?'} 版替代，仅供历史对照。")
        if hit.clause.needs_review:
            notes.append("条款切分需人工复核。")
        return " ".join(notes)

    def _citation(self, raw_id: str, hit: ClauseHit, start, end) -> dict:
        c, p = hit.clause, hit.policy
        prev, nxt = self.store.adjacent(c.policy_id, c.sequence)
        citation = {
            "id": raw_id,
            "policyTitle": p.title,
            "docNumber": p.doc_number or NOT_RECORDED,
            "issuer": p.issuer or NOT_RECORDED,
            "issuedOn": p.publish_date or NOT_RECORDED,
            "effectiveOn": p.effective_date or NOT_RECORDED,
            "expiresOn": p.expire_date or NOT_RECORDED,
            "status": p.verified_status,
            "clause": clause_label(c),
            "excerpt": _brief(c, 60),
            "text": fragment(c.content, start, end),
            "sourceUrl": p.url,
            "policyId": p.id,
            "version": p.version,
            "pageNumber": c.page_number,
            "sourceAnchor": c.source_anchor,
            "isCurrentVersion": bool(p.is_current),
        }
        note = self._status_note(hit)
        if note:
            citation["statusNote"] = note
        if prev is not None:
            citation["previousClause"] = f"{clause_label(prev)} {_brief(prev)}"
        if nxt is not None:
            citation["nextClause"] = f"{clause_label(nxt)} {_brief(nxt)}"
        return citation

    # ---------- verify ----------

    def verify(self, policy_id: int, *, status: str, note: str | None, fields: dict, verifier: str) -> dict:
        if status not in STATUSES:
            return {"policy": None, "error": _err(errors.INVALID_STATUS, f"status 只能是 {'/'.join(STATUSES)}。")}
        for key in ("publish_date", "effective_date", "expire_date"):
            value = fields.get(key)
            if value and not _DATE.match(value):
                return {"policy": None, "error": _err(errors.INVALID_QUERY, f"{key} 需为 YYYY-MM-DD。")}
        try:
            doc = self.store.verify(policy_id, status=status, note=(note or "").strip() or None, fields=fields, verifier=verifier)
        except Exception as exc:
            logger.error("policy verify failed id=%s error=%s", policy_id, type(exc).__name__)
            return {"policy": None, "error": _err(errors.STORE_ERROR, "保存核验结果失败。")}
        if doc is None:
            return {"policy": None, "error": _err(errors.NOT_FOUND, "政策不存在。")}
        logger.info("policy verified id=%s status=%s by=%s", policy_id, status, verifier)
        return {"policy": doc.to_dict(), "error": None}


_library: PolicyLibraryService | None = None
_library_lock = threading.Lock()


def get_policy_library() -> PolicyLibraryService:
    """Shares the store with the T1 search service (one DB, one write lock)."""
    global _library
    with _library_lock:
        if _library is None:
            from app.services.policy.service import get_policy_service

            service = get_policy_service()
            _library = PolicyLibraryService(service.settings, service.store, SafeFetcher(service.settings.fetch))
        return _library
