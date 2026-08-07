"""KB Ingest Service — bridge rich-parse results into the vector store.

Responsibilities:
  - Read ParsedFile + ParsedFileChunk from file_parse_service output
  - Re-chunk into 500-char KB chunks with parent provenance
  - Embed via bge-small-zh (reuses embedding.py lazy singleton)
  - Write to KB documents / chunks / FAISS / vector_index_map
  - Idempotent: skips if content_hash unchanged; force=True rebuilds

file_parse_service.py should NOT contain any vectorization logic.
"""
import hashlib
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger('app.kb.ingest')

# Reuse constants from config
from app.kb.config import CHUNK_SIZE, CHUNK_OVERLAP, EMBEDDING_MODEL_NAME

INGEST_PARSER_VERSION = 'unified_v1'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def vectorize_parsed_file(parsed_file_id: int, force: bool = False) -> dict:
    """Ingest a ParsedFile into the KB vector store.

    Returns:
        {"status": "indexed"|"skipped"|"rebuilt"|"error", ...}
    """
    from app.database import SessionLocal
    from app.models import ParsedFile, ParsedFileChunk
    from app.kb.db import (
        get_document_by_source_ref, add_document, add_chunks,
        add_vector_mappings, delete_chunks_for_doc,
        get_all_chunk_ids_for_doc,
    )
    from app.kb.embedding import embed_texts
    from app.kb.kb_manager import _split_text, KnowledgeBase

    source_ref = f'parsed:{parsed_file_id}'
    db = SessionLocal()
    try:
        parsed = db.query(ParsedFile).filter(ParsedFile.id == parsed_file_id).first()
        if not parsed:
            return {"status": "error", "message": f"ParsedFile {parsed_file_id} not found"}

        markdown = parsed.markdown or ''
        if not markdown.strip():
            return {"status": "error", "message": "empty markdown"}

        content_hash = hashlib.sha256(markdown.encode('utf-8')).hexdigest()[:32]

        # --- Idempotency check ---
        existing = get_document_by_source_ref(source_ref)
        if existing and not force:
            if existing.get('content_hash') == content_hash:
                logger.info('KB ingest skipped: %s (hash unchanged)', source_ref)
                return {"status": "skipped", "doc_id": existing['id'],
                        "message": "content_hash unchanged"}
            # Hash changed — rebuild
            logger.info('KB ingest rebuild: %s (hash changed)', source_ref)
            force = True

        # --- Delete old vectors if rebuilding ---
        old_doc_id = None
        if existing and force:
            old_doc_id = existing['id']
            old_chunk_ids = delete_chunks_for_doc(old_doc_id)
            if old_chunk_ids:
                try:
                    kb = _get_kb_singleton()
                    kb.vs.remove(old_chunk_ids)
                except Exception as e:
                    logger.warning('Failed to remove old FAISS vectors: %s', e)

        # --- Re-chunk into 500-char KB chunks ---
        kb_chunks = _split_text(markdown, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        if not kb_chunks:
            return {"status": "error", "message": "no chunks produced"}

        # --- Embed ---
        try:
            vectors = embed_texts(kb_chunks)
        except Exception as e:
            logger.error('Embedding failed for %s: %s', source_ref, e)
            return {"status": "error", "message": f"embedding failed: {e}"}

        # --- Write to KB ---
        now_str = datetime.now().isoformat()
        original_name = parsed.title or f'file-{parsed.file_id}'

        if old_doc_id and force:
            # Update existing document row
            _update_document_metadata(old_doc_id, content_hash, now_str)
            doc_id = old_doc_id
        else:
            doc_id = add_document(
                filename=original_name,
                filepath=f'parsed://{parsed_file_id}',
                stored_name=f'{uuid.uuid4().hex[:8]}_{original_name}',
                file_type=parsed.mime_type or '',
                file_size=0,
                clearance=0,
                source_ref=source_ref,
                content_hash=content_hash,
                parser_version=INGEST_PARSER_VERSION,
                embedding_model=EMBEDDING_MODEL_NAME,
                indexed_at=now_str,
            )

        # Compute per-chunk provenance from ParsedFileChunk page info
        provenance = _compute_provenance(parsed, parsed_file_id, db)

        chunk_ids = add_chunks(
            doc_id, kb_chunks, clearance=0,
            parsed_file_id=parsed_file_id,
            source_ref=source_ref,
        )

        # Write FAISS vectors
        try:
            kb = _get_kb_singleton()
            kb.vs.add(vectors, chunk_ids)
        except Exception as e:
            logger.error('FAISS write failed for %s: %s', source_ref, e)
            return {"status": "error", "message": f"faiss write failed: {e}"}

        # Write vector_index_map
        add_vector_mappings(chunk_ids, doc_id, source_ref=source_ref)

        status = "rebuilt" if force else "indexed"
        logger.info('KB ingest %s: %s (%d chunks)', status, source_ref, len(kb_chunks))
        return {
            "status": status,
            "doc_id": doc_id,
            "chunks": len(kb_chunks),
            "content_hash": content_hash,
        }

    except Exception as e:
        logger.error('KB ingest error for parsed_file_id=%d: %s', parsed_file_id, e, exc_info=True)
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_kb_singleton = None


def _get_kb_singleton():
    global _kb_singleton
    if _kb_singleton is None:
        from app.kb.kb_manager import KnowledgeBase
        _kb_singleton = KnowledgeBase()
    return _kb_singleton


def _update_document_metadata(doc_id: int, content_hash: str, indexed_at: str):
    from app.kb.db import get_conn
    conn = get_conn()
    conn.execute(
        'UPDATE documents SET content_hash=?, indexed_at=?, parser_version=?, '
        'embedding_model=?, updated_at=datetime("now","localtime") WHERE id=?',
        (content_hash, indexed_at, INGEST_PARSER_VERSION, EMBEDDING_MODEL_NAME, doc_id)
    )
    conn.commit()
    conn.close()


def _compute_provenance(parsed, parsed_file_id: int, db) -> list[dict]:
    """Map each KB chunk back to its parent ParsedFileChunk (page info)."""
    from app.models import ParsedFileChunk

    parent_chunks = (
        db.query(ParsedFileChunk)
        .filter(ParsedFileChunk.parsed_file_id == parsed_file_id)
        .order_by(ParsedFileChunk.chunk_index)
        .all()
    )
    if not parent_chunks:
        return []

    # Build a flat char-offset map of parent chunks
    provenance = []
    offset = 0
    for pc in parent_chunks:
        text = pc.content or ''
        start = offset
        end = offset + len(text)
        provenance.append({
            "parent_parsed_chunk_id": pc.id,
            "page_start": int(pc.page_start or 0),
            "page_end": int(pc.page_end or 0),
            "char_start": start,
            "char_end": end,
        })
        offset = end + 2  # account for "\n\n" separator
    return provenance


def expand_to_parent_chunk(chunk_row: dict) -> str:
    """Given a KB chunk row, return the parent ParsedFileChunk content for richer context."""
    parsed_file_id = chunk_row.get('parsed_file_id', 0)
    parent_id = chunk_row.get('parent_parsed_chunk_id', 0)

    if not parsed_file_id:
        return ''

    from app.database import SessionLocal
    from app.models import ParsedFileChunk

    db = SessionLocal()
    try:
        if parent_id:
            parent = db.query(ParsedFileChunk).filter(ParsedFileChunk.id == parent_id).first()
            if parent:
                return parent.content or ''

        # Fallback: find by page_no
        page_no = chunk_row.get('page_no', 0)
        if page_no:
            parent = (
                db.query(ParsedFileChunk)
                .filter(
                    ParsedFileChunk.parsed_file_id == parsed_file_id,
                    ParsedFileChunk.page_start <= page_no,
                    ParsedFileChunk.page_end >= page_no,
                )
                .first()
            )
            if parent:
                return parent.content or ''
    finally:
        db.close()

    return ''


def backfill_all(dry_run: bool = False, limit: int = 0, force: bool = False) -> dict:
    """Vectorize all existing ParsedFile records that are not yet in KB."""
    from app.database import SessionLocal
    from app.models import ParsedFile
    from app.kb.db import get_document_by_source_ref

    db = SessionLocal()
    try:
        parsed_files = db.query(ParsedFile).order_by(ParsedFile.id).all()
    finally:
        db.close()

    stats = {"total": len(parsed_files), "indexed": 0, "skipped": 0,
             "rebuilt": 0, "failed": 0, "failed_ids": []}

    for pf in parsed_files:
        if limit and (stats["indexed"] + stats["rebuilt"]) >= limit:
            break

        source_ref = f'parsed:{pf.id}'
        existing = get_document_by_source_ref(source_ref) if not force else None

        if dry_run:
            if existing and not force:
                stats["skipped"] += 1
            else:
                stats["indexed"] += 1
            continue

        result = vectorize_parsed_file(pf.id, force=force)
        status = result.get("status", "error")
        if status in ("indexed",):
            stats["indexed"] += 1
        elif status == "skipped":
            stats["skipped"] += 1
        elif status == "rebuilt":
            stats["rebuilt"] += 1
        else:
            stats["failed"] += 1
            stats["failed_ids"].append(pf.id)
            logger.warning('Backfill failed for parsed_file_id=%d: %s',
                           pf.id, result.get("message", ""))

    return stats
