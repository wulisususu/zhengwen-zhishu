"""SQLite storage for the public policy library (backend/data/policy.db).

This database holds public policy only. Users' private materials live in the
knowledge base (app/kb, its own DB); the two are never queried together.

Versioning (per ``url``, the source URL):
- each version is its own row; exactly one row per url has ``is_current = 1``;
- when the content hash changes a new row is inserted (version + 1) and the
  old row gets ``is_current = 0`` and ``superseded_by = <new id>``; old rows
  and their clauses are never overwritten or deleted;
- an unchanged hash only refreshes ``last_checked_at``;
- everything happens in one transaction: if anything fails, existing rows —
  including verified ones — stay exactly as they were.

``verified_status`` is the only source of the policy status and is set only by
a person (verify). New versions always start as ``unverified``.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.services.policy.parser import PolicyRecord

STATUSES = ("current", "abolished", "unverified")

SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL DEFAULT 'gov_zcwjk',
  remote_id TEXT,
  title TEXT NOT NULL,
  doc_number TEXT,
  issuer TEXT,
  publish_date TEXT,
  category TEXT,
  subject TEXT,
  url TEXT NOT NULL,
  summary TEXT,
  content TEXT,
  content_hash TEXT,
  fetched_at TEXT NOT NULL,
  verified_status TEXT NOT NULL DEFAULT 'unverified' CHECK (verified_status IN ('current', 'abolished', 'unverified')),
  version INTEGER NOT NULL DEFAULT 1,
  is_current INTEGER NOT NULL DEFAULT 1,
  superseded_by INTEGER REFERENCES policy_documents(id),
  last_checked_at TEXT,
  effective_date TEXT,
  expire_date TEXT,
  status_note TEXT,
  verified_by TEXT,
  verified_at TEXT,
  origin TEXT NOT NULL DEFAULT 'search'
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_policy_url_version ON policy_documents(url, version);
CREATE UNIQUE INDEX IF NOT EXISTS uq_policy_url_current ON policy_documents(url) WHERE is_current = 1;
CREATE INDEX IF NOT EXISTS idx_policy_documents_publish_date ON policy_documents(publish_date);

CREATE TABLE IF NOT EXISTS gov_policy_clauses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  policy_id INTEGER NOT NULL REFERENCES policy_documents(id),
  article_number TEXT,
  parent_clause_id INTEGER REFERENCES gov_policy_clauses(id),
  heading TEXT,
  content TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  page_number INTEGER,
  source_anchor TEXT,
  needs_review INTEGER NOT NULL DEFAULT 0,
  UNIQUE (policy_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_gov_policy_clauses_policy ON gov_policy_clauses(policy_id, sequence);
"""

#: T1 shipped ``url TEXT UNIQUE``; that constraint blocks versioning, so the
#: table is rebuilt once with these columns copied over.
_T1_COLUMNS = (
    "id", "source", "remote_id", "title", "doc_number", "issuer", "publish_date", "category",
    "subject", "url", "summary", "content", "content_hash", "fetched_at", "verified_status",
)

DOC_COLUMNS = (
    "id", "source", "remote_id", "title", "doc_number", "issuer", "publish_date", "category", "subject",
    "url", "summary", "content_hash", "fetched_at", "verified_status", "version", "is_current",
    "superseded_by", "last_checked_at", "effective_date", "expire_date", "status_note",
    "verified_by", "verified_at", "origin",
)
CLAUSE_COLUMNS = (
    "id", "policy_id", "article_number", "parent_clause_id", "heading", "content",
    "sequence", "page_number", "source_anchor", "needs_review",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def text_hash(text: str) -> str:
    normalized = "\n".join(line.strip() for line in (text or "").splitlines() if line.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class StoredPolicy:
    id: int
    source: str
    remote_id: str | None
    title: str
    doc_number: str | None
    issuer: str | None
    publish_date: str | None
    category: str | None
    subject: str | None
    url: str
    summary: str | None
    content_hash: str | None
    fetched_at: str
    verified_status: str
    version: int = 1
    is_current: int = 1
    superseded_by: int | None = None
    last_checked_at: str | None = None
    effective_date: str | None = None
    expire_date: str | None = None
    status_note: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
    origin: str = "search"

    def to_dict(self) -> dict:
        data = dict(self.__dict__)
        data["is_current"] = bool(self.is_current)
        return data


@dataclass(frozen=True)
class StoredClause:
    id: int
    policy_id: int
    article_number: str | None
    parent_clause_id: int | None
    heading: str | None
    content: str
    sequence: int
    page_number: int | None
    source_anchor: str | None
    needs_review: int

    def to_dict(self) -> dict:
        data = dict(self.__dict__)
        data["needs_review"] = bool(self.needs_review)
        return data


@dataclass
class ImportOutcome:
    policy: StoredPolicy
    created_new_version: bool
    superseded_id: int | None = None
    clause_count: int = 0
    needs_review_count: int = 0


@dataclass
class PolicyFilter:
    keyword: str = ""
    doc_number: str = ""
    issuer: str = ""
    statuses: tuple[str, ...] = ()
    include_history: bool = False
    url: str = ""


@dataclass
class ClauseHit:
    clause: StoredClause
    policy: StoredPolicy
    extras: dict = field(default_factory=dict)


class PolicyStore:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False) if self.db_path == ":memory:" else None
        with self._connect() as conn:
            self._migrate_t1(conn)
            conn.executescript(SCHEMA)

    # ---------- infrastructure ----------

    @contextmanager
    def _connect(self):
        conn = self._memory_conn or sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if self._memory_conn is None:
                conn.close()

    @staticmethod
    def _migrate_t1(conn: sqlite3.Connection) -> None:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(policy_documents)")]
        if not cols or "version" in cols:
            return
        conn.execute("ALTER TABLE policy_documents RENAME TO policy_documents_t1")
        conn.executescript(SCHEMA)
        shared = ", ".join(c for c in _T1_COLUMNS if c in cols)
        conn.execute(f"INSERT INTO policy_documents ({shared}) SELECT {shared} FROM policy_documents_t1")
        conn.execute("UPDATE policy_documents SET verified_status = 'unverified' WHERE verified_status NOT IN ('current', 'abolished', 'unverified')")
        conn.execute("DROP TABLE policy_documents_t1")

    @staticmethod
    def _doc(row: sqlite3.Row) -> StoredPolicy:
        return StoredPolicy(**{c: row[c] for c in DOC_COLUMNS})

    @staticmethod
    def _clause(row: sqlite3.Row, prefix: str = "") -> StoredClause:
        return StoredClause(**{c: row[f"{prefix}{c}"] for c in CLAUSE_COLUMNS})

    @staticmethod
    def _current(conn, url: str):
        return conn.execute("SELECT * FROM policy_documents WHERE url = ? AND is_current = 1", (url,)).fetchone()

    @staticmethod
    def _next_version(conn, url: str) -> int:
        return int(conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM policy_documents WHERE url = ?", (url,)).fetchone()[0])

    @staticmethod
    def _insert_doc(conn, values: dict) -> int:
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        return int(conn.execute(f"INSERT INTO policy_documents ({cols}) VALUES ({marks})", tuple(values.values())).lastrowid)

    @staticmethod
    def _supersede(conn, old_id: int, new_id: int) -> None:
        conn.execute("UPDATE policy_documents SET superseded_by = ? WHERE id = ?", (new_id, old_id))

    # ---------- search metadata (T1) ----------

    def upsert(self, record: PolicyRecord, fetched_at: str | None = None) -> str:
        """Store one search result. Returns "inserted", "new_version" or "unchanged".

        A current row that already carries imported full text is never replaced
        by search metadata; it only gets ``last_checked_at`` refreshed.
        """
        now = fetched_at or utc_now()
        values = {
            "source": record.source, "remote_id": record.remote_id, "title": record.title,
            "doc_number": record.doc_number, "issuer": record.issuer, "publish_date": record.publish_date,
            "category": record.category, "subject": record.subject, "url": record.url,
            "summary": record.summary, "content_hash": record.content_hash,
            "fetched_at": now, "last_checked_at": now, "origin": "search",
        }
        with self._write_lock, self._connect() as conn:
            current = self._current(conn, record.url)
            if current is None:
                values["version"] = self._next_version(conn, record.url)
                self._insert_doc(conn, values)
                return "inserted"
            if current["content"] is not None or current["content_hash"] == record.content_hash:
                conn.execute("UPDATE policy_documents SET last_checked_at = ? WHERE id = ?", (now, current["id"]))
                return "unchanged"
            conn.execute("UPDATE policy_documents SET is_current = 0 WHERE id = ?", (current["id"],))
            values["version"] = current["version"] + 1
            values["status_note"] = f"检索摘要已变化（第 {values['version']} 版），需重新人工核验。"
            new_id = self._insert_doc(conn, values)
            self._supersede(conn, current["id"], new_id)
            return "new_version"

    # ---------- imported full text ----------

    def save_import(self, *, url: str, meta: dict, content: str, clauses: list, origin: str) -> ImportOutcome:
        """Store imported full text with its clauses as a version of ``url``."""
        content_hash = text_hash(content)
        now = utc_now()
        with self._write_lock, self._connect() as conn:
            current = self._current(conn, url)
            if current is not None and current["content"] is not None and current["content_hash"] == content_hash:
                conn.execute("UPDATE policy_documents SET last_checked_at = ? WHERE id = ?", (now, current["id"]))
                row = conn.execute("SELECT * FROM policy_documents WHERE id = ?", (current["id"],)).fetchone()
                count, review = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(needs_review), 0) FROM gov_policy_clauses WHERE policy_id = ?", (current["id"],)
                ).fetchone()
                return ImportOutcome(self._doc(row), False, None, int(count), int(review))

            def pick(key):
                value = meta.get(key)
                if value:
                    return value
                return current[key] if current is not None else None

            title = pick("title") or url
            values = {
                "source": (current["source"] if current is not None else meta.get("source")) or "gov_zcwjk",
                "remote_id": pick("remote_id"),
                "title": title,
                "doc_number": pick("doc_number"),
                "issuer": pick("issuer"),
                "publish_date": pick("publish_date"),
                "category": pick("category"),
                "subject": pick("subject"),
                "url": url,
                "summary": pick("summary") or content[:200],
                "content": content,
                "content_hash": content_hash,
                "fetched_at": now,
                "last_checked_at": now,
                "verified_status": "unverified",
                "version": self._next_version(conn, url),
                "is_current": 1,
                "origin": origin,
            }
            if current is not None:
                values["status_note"] = f"正文已更新（第 {values['version']} 版），需重新人工核验。"
                conn.execute("UPDATE policy_documents SET is_current = 0 WHERE id = ?", (current["id"],))
            new_id = self._insert_doc(conn, values)

            ids: list[int] = []
            for draft in clauses:
                parent_id = ids[draft.parent_index] if draft.parent_index is not None else None
                cur = conn.execute(
                    "INSERT INTO gov_policy_clauses (policy_id, article_number, parent_clause_id, heading, content, sequence, page_number, source_anchor, needs_review) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id, draft.article_number, parent_id, draft.heading, draft.content, draft.sequence,
                     getattr(draft, "page_number", None), draft.source_anchor, 1 if draft.needs_review else 0),
                )
                ids.append(int(cur.lastrowid))
            if current is not None:
                self._supersede(conn, current["id"], new_id)
            row = conn.execute("SELECT * FROM policy_documents WHERE id = ?", (new_id,)).fetchone()
            return ImportOutcome(
                self._doc(row), True, current["id"] if current is not None else None,
                len(ids), sum(1 for d in clauses if d.needs_review),
            )

    # ---------- verification ----------

    VERIFIABLE_FIELDS = ("doc_number", "issuer", "publish_date", "effective_date", "expire_date", "title")

    def verify(self, policy_id: int, *, status: str, note: str | None, fields: dict, verifier: str) -> StoredPolicy | None:
        if status not in STATUSES:
            raise ValueError("invalid status")
        updates = {k: v for k, v in fields.items() if k in self.VERIFIABLE_FIELDS and v is not None}
        updates.update({"verified_status": status, "status_note": note, "verified_by": verifier, "verified_at": utc_now()})
        assignments = ", ".join(f"{k} = ?" for k in updates)
        with self._write_lock, self._connect() as conn:
            if conn.execute("SELECT 1 FROM policy_documents WHERE id = ?", (policy_id,)).fetchone() is None:
                return None
            conn.execute(f"UPDATE policy_documents SET {assignments} WHERE id = ?", (*updates.values(), policy_id))
            return self._doc(conn.execute("SELECT * FROM policy_documents WHERE id = ?", (policy_id,)).fetchone())

    # ---------- reads ----------

    def search_local(self, query: str, limit: int = 10) -> list[StoredPolicy]:
        pattern = f"%{_escape_like(query)}%"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM policy_documents WHERE is_current = 1 AND (title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\') "
                "ORDER BY (publish_date IS NULL), publish_date DESC, id DESC LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall()
        return [self._doc(r) for r in rows]

    def get_by_url(self, url: str) -> StoredPolicy | None:
        with self._connect() as conn:
            row = self._current(conn, url)
        return self._doc(row) if row else None

    def get(self, doc_id: int) -> StoredPolicy | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM policy_documents WHERE id = ?", (doc_id,)).fetchone()
        return self._doc(row) if row else None

    def versions(self, url: str) -> list[StoredPolicy]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM policy_documents WHERE url = ? ORDER BY version", (url,)).fetchall()
        return [self._doc(r) for r in rows]

    def list_documents(self, page: int = 1, page_size: int = 20) -> tuple[list[StoredPolicy], int]:
        return self.list_policies(PolicyFilter(), page, page_size)

    def list_policies(self, flt: PolicyFilter, page: int = 1, page_size: int = 20) -> tuple[list[StoredPolicy], int]:
        where, params = [], []
        if not flt.include_history:
            where.append("is_current = 1")
        if flt.keyword:
            where.append("(title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\')")
            params += [f"%{_escape_like(flt.keyword)}%"] * 2
        if flt.doc_number:
            where.append("doc_number LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(flt.doc_number)}%")
        if flt.issuer:
            where.append("issuer LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(flt.issuer)}%")
        if flt.statuses:
            where.append(f"verified_status IN ({', '.join('?' for _ in flt.statuses)})")
            params += list(flt.statuses)
        if flt.url:
            where.append("url = ?")
            params.append(flt.url)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        page = max(1, page)
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM policy_documents {clause}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM policy_documents {clause} ORDER BY (publish_date IS NULL), publish_date DESC, url, version DESC LIMIT ? OFFSET ?",
                (*params, page_size, (page - 1) * page_size),
            ).fetchall()
        return [self._doc(r) for r in rows], int(total)

    def count(self, include_history: bool = False) -> int:
        with self._connect() as conn:
            sql = "SELECT COUNT(*) FROM policy_documents" + ("" if include_history else " WHERE is_current = 1")
            return int(conn.execute(sql).fetchone()[0])

    def clauses_for(self, policy_id: int) -> list[StoredClause]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM gov_policy_clauses WHERE policy_id = ? ORDER BY sequence", (policy_id,)).fetchall()
        return [self._clause(r) for r in rows]

    def _joined_select(self) -> str:
        clause_cols = ", ".join(f"c.{c} AS c_{c}" for c in CLAUSE_COLUMNS)
        doc_cols = ", ".join(f"p.{c} AS {c}" for c in DOC_COLUMNS)
        return f"SELECT {clause_cols}, {doc_cols} FROM gov_policy_clauses c JOIN policy_documents p ON p.id = c.policy_id"

    def search_clauses(self, terms: list[str], statuses: tuple[str, ...], limit: int, include_history: bool = False) -> list[ClauseHit]:
        where = [f"p.verified_status IN ({', '.join('?' for _ in statuses)})"]
        params: list = list(statuses)
        if not include_history:
            where.append("p.is_current = 1")
        for term in terms:
            where.append("c.content LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(term)}%")
        sql = f"{self._joined_select()} WHERE {' AND '.join(where)} ORDER BY (p.publish_date IS NULL), p.publish_date DESC, p.id DESC, c.sequence LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(sql, (*params, limit)).fetchall()
        return [ClauseHit(self._clause(r, "c_"), self._doc(r)) for r in rows]

    def clauses_by_ids(self, ids: list[int]) -> dict[int, ClauseHit]:
        if not ids:
            return {}
        sql = f"{self._joined_select()} WHERE c.id IN ({', '.join('?' for _ in ids)})"
        with self._connect() as conn:
            rows = conn.execute(sql, ids).fetchall()
        return {r["c_id"]: ClauseHit(self._clause(r, "c_"), self._doc(r)) for r in rows}

    def adjacent(self, policy_id: int, sequence: int) -> tuple[StoredClause | None, StoredClause | None]:
        with self._connect() as conn:
            prev = conn.execute("SELECT * FROM gov_policy_clauses WHERE policy_id = ? AND sequence = ?", (policy_id, sequence - 1)).fetchone()
            nxt = conn.execute("SELECT * FROM gov_policy_clauses WHERE policy_id = ? AND sequence = ?", (policy_id, sequence + 1)).fetchone()
        return (self._clause(prev) if prev else None), (self._clause(nxt) if nxt else None)
