import os
import asyncio
import tempfile
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from app.deps import get_current_user
from app.models import User
from app.errors import ok, fail, ERR_INTERNAL
from app.kb.config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
logger = logging.getLogger("app.knowledge")

_kb = None
_init_lock = asyncio.Lock()
_write_lock = asyncio.Lock()
_init_error = None


async def _get_kb():
    global _kb, _init_error
    if _kb is not None:
        return _kb
    async with _init_lock:
        if _kb is not None:
            return _kb
        try:
            logger.info("Initializing knowledge base...")
            from app.kb.kb_manager import KnowledgeBase
            _kb = KnowledgeBase()
            _init_error = None
            logger.info("Knowledge base ready: %d vectors", _kb.vector_count)
        except Exception as exc:
            _init_error = str(exc)
            logger.error("KB init failed: %s", exc)
            raise
    return _kb


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)


@router.get("/status")
async def kb_status(user: User = Depends(get_current_user)):
    # Read stats directly from DB and FAISS file — no model loading
    try:
        from app.kb.db import get_document_count, get_all_chunk_ids
        doc_count = get_document_count()
        chunk_count = len(get_all_chunk_ids())
        # Check if FAISS index file exists
        from app.kb.config import VECTOR_DIR
        index_exists = (VECTOR_DIR / 'faiss.index').exists()
        return ok(data={
            "ready": True,
            "vector_count": chunk_count,
            "document_count": doc_count,
            "error": None,
        })
    except Exception as exc:
        return ok(data={"ready": False, "message": str(exc), "error": str(exc)})


@router.post("/documents")
async def upload_document(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    filename = file.filename or "(none)"
    ext = os.path.splitext(filename)[1].lower()
    content_type = file.content_type or "(none)"
    logger.info('Upload: filename=%s, ext=%s, content_type=%s, size_hint=%s', filename, ext, content_type, file.size)
    if ext not in ALLOWED_EXTENSIONS:
        logger.warning('Rejected file type: ext=%s, allowed=%s', ext, ALLOWED_EXTENSIONS)
        raise HTTPException(status_code=415, detail=f"不支持的文件类型：{ext}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"文件大小超过限制（{MAX_FILE_SIZE // 1024 // 1024}MB）")

    kb = await _get_kb()
    suffix = ext or ".txt"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir="/tmp")
    try:
        tmp.write(content)
        tmp.close()
        async with _write_lock:
            result = await asyncio.to_thread(kb.add_file, tmp.name, file.filename)
        return ok(data={
            "doc_id": result["doc_id"],
            "filename": file.filename,
            "chunks": result["chunks"],
        })
    except Exception as exc:
        return fail(ERR_INTERNAL, str(exc))
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@router.get("/documents")
async def list_documents(user: User = Depends(get_current_user)):
    # Read directly from DB — no need to wait for KnowledgeBase init
    try:
        from app.kb.db import list_documents as _list_docs
        return ok(data={"documents": _list_docs()})
    except Exception as exc:
        return ok(data={"documents": [], "loading": True})


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: int, user: User = Depends(get_current_user)):
    try:
        kb = await _get_kb()
    except Exception:
        return fail(ERR_INTERNAL, "Knowledge base not ready")
    async with _write_lock:
        result = await asyncio.to_thread(kb.delete, doc_id)
    if result is None:
        return fail(40400, "Document not found")
    return ok(data={"deleted": True, "filename": result["filename"]})


@router.get("/documents/{doc_id}/file")
async def preview_document_file(doc_id: int, user: User = Depends(get_current_user)):
    from app.kb.db import get_conn
    conn = get_conn()
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    filepath = row["filepath"] or ""
    filename = row["filename"] or ""

    # Handle parsed:// virtual paths (backfilled from file_parse_service)
    if filepath.startswith("parsed://"):
        try:
            parsed_id = int(filepath.replace("parsed://", ""))
            from app.database import SessionLocal
            from app.models import File as FileModel, ParsedFile
            db = SessionLocal()
            try:
                parsed = db.query(ParsedFile).filter(ParsedFile.id == parsed_id).first()
                if parsed:
                    file_rec = db.query(FileModel).filter(FileModel.id == parsed.file_id).first()
                    if file_rec and file_rec.filepath and os.path.exists(file_rec.filepath):
                        filepath = file_rec.filepath
                        filename = filename or file_rec.filename
            finally:
                db.close()
        except Exception:
            pass

    if not filepath or not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found on disk")
    # Detect correct media type for inline preview
    import mimetypes
    mime_type, _ = mimetypes.guess_type(filepath)
    if not mime_type:
        mime_type = "application/octet-stream"
    return FileResponse(filepath, filename=filename, media_type=mime_type)


@router.post("/search")
async def search(body: SearchRequest, user: User = Depends(get_current_user)):
    try:
        kb = await _get_kb()
    except Exception:
        return fail(ERR_INTERNAL, "Embedding model is still loading, please wait...")
    results = await asyncio.to_thread(kb.search, body.query, body.top_k)
    return ok(data={"query": body.query, "results": results})
