"""Resolve explicit PPT generation sources into bounded, traceable context."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


MAX_SOURCE_CONTEXT_CHARS = 30_000
MAX_CHUNKS_PER_SOURCE = 4


class SourceResolutionError(ValueError):
    def __init__(self, code: str, *, pending_file_ids: list[int] | None = None, failed_file_ids: list[int] | None = None):
        super().__init__(code)
        self.code = code
        self.pending_file_ids = pending_file_ids or []
        self.failed_file_ids = failed_file_ids or []


@dataclass(frozen=True)
class SourceContextResult:
    source_context: str
    source_manifest: list[dict[str, Any]]
    attachment_file_ids: list[int]
    knowledge_doc_ids: list[int]
    skipped_sources: list[dict[str, Any]]


def _ids(value: list[int] | None) -> list[int]:
    result: list[int] = []
    for item in value or []:
        try:
            item = int(item)
        except (TypeError, ValueError):
            continue
        if item > 0 and item not in result:
            result.append(item)
    return result


def _score_chunks(chunks: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    import re

    terms = set(re.findall(r"[A-Za-z0-9_\-/]{2,}|[\u4e00-\u9fff]{2,}", query or ""))
    scored = []
    for position, chunk in enumerate(chunks):
        text = str(chunk.get("content") or chunk.get("chunk_text") or "")
        score = sum(1 for term in terms if term in text) + min(len(text), 1200) / 6000
        scored.append((score, position, chunk))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = [item[2] for item in scored[:MAX_CHUNKS_PER_SOURCE]]
    return selected


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_source_context(*, user_id: int, attachment_file_ids: list[int], knowledge_doc_ids: list[int], source_policy: str, query: str, source_rows: list[dict[str, Any]], max_chars: int = MAX_SOURCE_CONTEXT_CHARS) -> SourceContextResult:
    del user_id
    requested_files = _ids(attachment_file_ids)
    requested_docs = _ids(knowledge_doc_ids)
    rows_by_key = {
        (row.get("kind"), int(row.get("file_id") or row.get("doc_id") or 0)): row
        for row in source_rows
    }
    ordered_rows = [rows_by_key.get(("file", file_id)) for file_id in requested_files]
    ordered_rows += [rows_by_key.get(("knowledge", doc_id)) for doc_id in requested_docs]
    missing = [row for row in ordered_rows if row is None]
    if missing:
        raise SourceResolutionError("source_not_found")

    pending = [int(row["file_id"]) for row in ordered_rows if row and row.get("kind") == "file" and row.get("parse_status") not in (None, "done") and row.get("parse_status") != "error"]
    failed = [int(row["file_id"]) for row in ordered_rows if row and row.get("kind") == "file" and row.get("parse_status") == "error"]
    if source_policy != "ready_only":
        if pending:
            raise SourceResolutionError("sources_pending", pending_file_ids=pending)
        if failed:
            raise SourceResolutionError("sources_failed", failed_file_ids=failed)

    usable = [row for row in ordered_rows if row and (row.get("kind") == "knowledge" or row.get("parse_status") in (None, "done"))]
    skipped = [
        {"kind": row.get("kind"), "file_id": row.get("file_id"), "doc_id": row.get("doc_id"), "filename": row.get("filename"), "status": row.get("parse_status"), "error": row.get("error")}
        for row in ordered_rows if row not in usable
    ]
    if (requested_files or requested_docs) and not usable:
        raise SourceResolutionError("no_ready_sources", pending_file_ids=pending, failed_file_ids=failed)

    per_source_budget = max(1, max_chars // max(1, len(usable)))
    context_parts: list[str] = []
    manifest: list[dict[str, Any]] = []
    for row in usable:
        chunks = _score_chunks(list(row.get("chunks") or []), query)
        if not chunks:
            continue
        remaining = per_source_budget
        rendered: list[str] = []
        for chunk in chunks:
            text = str(chunk.get("content") or chunk.get("chunk_text") or "").strip()
            if not text or remaining <= 0:
                continue
            text = text[:remaining]
            rendered.append(text)
            remaining -= len(text)
            manifest.append({
                "kind": row.get("kind"),
                "file_id": row.get("file_id"),
                "doc_id": row.get("doc_id"),
                "parsed_file_id": row.get("parsed_file_id"),
                "filename": row.get("filename") or "来源文件",
                "chunk_id": chunk.get("chunk_id") or chunk.get("id") or chunk.get("chunk_index"),
                "page_start": int(chunk.get("page_start") or chunk.get("page_no") or 0),
                "page_end": int(chunk.get("page_end") or chunk.get("page_no") or 0),
                "content_sha256": _sha256(text),
            })
        if rendered:
            context_parts.append("【来源：%s】\n%s" % (row.get("filename") or "来源文件", "\n\n".join(rendered)))
    return SourceContextResult(
        source_context="\n\n".join(context_parts),
        source_manifest=manifest,
        attachment_file_ids=requested_files,
        knowledge_doc_ids=requested_docs,
        skipped_sources=skipped,
    )


def resolve_ppt_sources(*, user_id: int, attachment_file_ids: list[int], knowledge_doc_ids: list[int], source_policy: str, query: str = "", source_rows: list[dict[str, Any]] | None = None) -> SourceContextResult:
    if source_rows is not None:
        return build_source_context(user_id=user_id, attachment_file_ids=attachment_file_ids, knowledge_doc_ids=knowledge_doc_ids, source_policy=source_policy, query=query, source_rows=source_rows)

    from app.database import SessionLocal
    from app.models import File, FileParseTask, ParsedFile, ParsedFileChunk
    from app.kb.db import get_documents_by_ids, get_chunks_for_document_ids

    file_ids = _ids(attachment_file_ids)
    doc_ids = _ids(knowledge_doc_ids)
    rows: list[dict[str, Any]] = []
    db = SessionLocal()
    try:
        files = db.query(File).filter(File.user_id == user_id, File.id.in_(file_ids)).all() if file_ids else []
        by_id = {item.id: item for item in files}
        if len(by_id) != len(file_ids):
            raise SourceResolutionError("source_access_denied")
        for file_id in file_ids:
            file = by_id[file_id]
            task = db.query(FileParseTask).filter(FileParseTask.file_id == file_id, FileParseTask.user_id == user_id).order_by(FileParseTask.created_at.desc()).first()
            parsed = db.query(ParsedFile).filter(ParsedFile.file_id == file_id, ParsedFile.user_id == user_id).order_by(ParsedFile.id.desc()).first()
            chunks = []
            if parsed:
                chunks = [
                    {"chunk_id": chunk.id, "content": chunk.content, "page_start": chunk.page_start, "page_end": chunk.page_end, "chunk_index": chunk.chunk_index}
                    for chunk in db.query(ParsedFileChunk).filter(ParsedFileChunk.parsed_file_id == parsed.id, ParsedFileChunk.user_id == user_id).order_by(ParsedFileChunk.chunk_index).all()
                ]
            rows.append({"kind": "file", "file_id": file_id, "parsed_file_id": parsed.id if parsed else None, "filename": file.filename, "parse_status": task.status if task else "queued", "error": task.error if task else "尚未解析", "chunks": chunks})
    finally:
        db.close()
    docs = get_documents_by_ids(doc_ids)
    if len(docs) != len(doc_ids):
        raise SourceResolutionError("knowledge_document_not_found")
    chunks_by_doc: dict[int, list[dict[str, Any]]] = {doc_id: [] for doc_id in doc_ids}
    for chunk in get_chunks_for_document_ids(doc_ids):
        chunks_by_doc[int(chunk["doc_id"])].append({"chunk_id": chunk.get("chunk_id"), "content": chunk.get("chunk_text"), "page_start": 0, "page_end": 0, "chunk_index": chunk.get("chunk_index")})
    for doc in docs:
        rows.append({"kind": "knowledge", "doc_id": doc["id"], "filename": doc.get("filename"), "chunks": chunks_by_doc.get(doc["id"], [])})
    return build_source_context(user_id=user_id, attachment_file_ids=file_ids, knowledge_doc_ids=doc_ids, source_policy=source_policy, query=query, source_rows=rows)
