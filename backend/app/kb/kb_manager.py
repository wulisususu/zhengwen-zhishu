import re
import uuid
import shutil
import subprocess
import tempfile
import logging
from pathlib import Path

from app.kb.config import DOCS_DIR, CHUNK_SIZE, CHUNK_OVERLAP, TOP_K, MAX_FILE_SIZE, ALLOWED_EXTENSIONS
from app.kb.db import (
    init_db, add_document, add_chunks, get_chunks_by_ids,
    list_documents, delete_document, get_all_chunk_ids_for_doc,
    get_all_chunks_with_doc, get_document_count, get_all_chunk_ids,
    get_document_clearance,
)
from app.kb.embedding import embed_texts, embed_query
from app.kb.vector_store import VectorStore

logger = logging.getLogger('app.kb')

_SNIPPET_MAX_LEN = 500
_OVER_FETCH_MULTIPLIER = 3
_MIN_SCORE_FLOOR = 0.15


def _read_pdf_via_pdftotext(filepath: Path) -> str:
    """Use pdftotext CLI for PDFs where pdfplumber may fail (non-standard encodings)."""
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', str(filepath), '-'],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ''


def _read_pdf_via_ocr(filepath: Path) -> str:
    """OCR a scanned/image-based PDF via pdftoppm + tesseract."""
    if not shutil.which('tesseract'):
        return ''
    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = Path(tmpdir) / 'page'
        try:
            subprocess.run(
                ['pdftoppm', '-r', '200', '-png', str(filepath), str(prefix)],
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            return ''
        page_texts = []
        for image_path in sorted(Path(tmpdir).glob('page-*.png')):
            try:
                result = subprocess.run(
                    ['tesseract', str(image_path), 'stdout', '-l', 'chi_sim+eng', '--psm', '6'],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                )
                text = result.stdout.strip()
                if text:
                    page_texts.append(text)
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
    return '\n'.join(page_texts)


def extract_text(filepath: Path) -> str:
    ext = filepath.suffix.lower()
    if ext in ('.txt', '.md', '.log', '.csv', '.json'):
        return filepath.read_text(encoding='utf-8', errors='replace')
    if ext == '.pdf':
        # 1. Try pdfplumber first (fast, good for text-based PDFs)
        text = ''
        try:
            import pdfplumber
            with pdfplumber.open(str(filepath)) as pdf:
                text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
        except ImportError:
            raise RuntimeError('需要安装 pdfplumber 才能解析 PDF 文件，请执行: pip install pdfplumber')
        if text.strip():
            return text

        # 2. Fallback: pdftotext (handles some non-standard encodings better)
        logger.info('pdfplumber returned empty for %s, trying pdftotext...', filepath.name)
        text = _read_pdf_via_pdftotext(filepath)
        if text.strip():
            return text

        # 3. Last resort: OCR for scanned/image-based PDFs
        logger.info('pdftotext also empty for %s, trying OCR...', filepath.name)
        text = _read_pdf_via_ocr(filepath)
        if text.strip():
            logger.info('OCR succeeded for %s: %d chars', filepath.name, len(text))
            return text

        logger.warning('All extraction methods failed for %s (pdfplumber, pdftotext, OCR)', filepath.name)
        return ''
    if ext == '.docx':
        try:
            from docx import Document
        except ImportError:
            raise RuntimeError('需要安装 python-docx 才能解析 Word 文件，请执行: pip install python-docx')
        doc = Document(str(filepath))
        return '\n'.join(p.text for p in doc.paragraphs)
    if ext == '.xlsx':
        try:
            import openpyxl
        except ImportError:
            raise RuntimeError('需要安装 openpyxl 才能解析 Excel 文件，请执行: pip install openpyxl')
        wb = openpyxl.load_workbook(str(filepath), read_only=True, data_only=True)
        lines = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                lines.append('\t'.join(str(c) for c in row if c is not None))
        return '\n'.join(lines)
    raise ValueError(f'不支持的文件类型：{ext}')


def _split_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    if not text.strip():
        return []
    sentences = re.split(r'(?<=[。！？.!?\n])', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return [text.strip()]

    chunks = []
    buf = []
    buf_len = 0

    for sent in sentences:
        sent_len = len(sent)
        if sent_len > chunk_size:
            if buf:
                chunks.append(''.join(buf))
                buf = []
                buf_len = 0
            for i in range(0, sent_len, chunk_size - overlap):
                chunks.append(sent[i:i + chunk_size])
            continue
        if buf_len + sent_len > chunk_size and buf:
            chunks.append(''.join(buf))
            overlap_text = ''.join(buf)[-overlap:]
            buf = [overlap_text]
            buf_len = len(overlap_text)
        buf.append(sent)
        buf_len += sent_len

    if buf:
        chunks.append(''.join(buf))
    return chunks if chunks else [text.strip()]


class KnowledgeBase:
    def __init__(self):
        init_db()
        self.vs = VectorStore()
        self._rebuild_if_needed()

    def _rebuild_if_needed(self):
        # Fast path: if FAISS index file exists and has vectors, trust it.
        # The index is kept in sync by kb_ingest_service during parse.
        # Only rebuild if index is completely empty but DB has chunks.
        if self.vs.count() > 0:
            db_count = len(get_all_chunk_ids())
            idx_count = self.vs.count()
            if abs(db_count - idx_count) <= 2:
                # Close enough — skip expensive rebuild
                logger.info('FAISS index OK: %d vectors, %d DB chunks', idx_count, db_count)
                return
            logger.warning('FAISS mismatch: %d vectors vs %d DB chunks. Will rebuild.',
                           idx_count, db_count)

        db_ids = get_all_chunk_ids()
        idx_ids = self.vs.get_all_ids()
        if db_ids == idx_ids:
            return

        logger.warning(
            'FAISS index mismatch: DB has %d chunks, index has %d vectors. Rebuilding...',
            len(db_ids), len(idx_ids)
        )
        self.vs.reset()
        all_chunks = get_all_chunks_with_doc()
        if not all_chunks:
            return
        batch_size = 64
        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i:i + batch_size]
            texts = [c['chunk_text'] for c in batch]
            ids = [c['chunk_id'] for c in batch]
            vectors = embed_texts(texts)
            self.vs.add(vectors, ids)
        logger.info('FAISS index rebuilt with %d vectors', self.vs.count())

    def add_file(self, filepath, original_name=None, clearance=0):
        filepath = Path(filepath).resolve()
        if not filepath.exists():
            raise FileNotFoundError(f'File not found: {filepath}')

        ext = filepath.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f'不支持的文件类型：{ext}')

        file_size = filepath.stat().st_size
        if file_size > MAX_FILE_SIZE:
            raise ValueError(f'文件大小 {file_size // 1024 // 1024}MB 超过限制 {MAX_FILE_SIZE // 1024 // 1024}MB')

        text = extract_text(filepath)
        chunks = _split_text(text)
        if not chunks:
            raise ValueError('No valid text content found')

        vectors = embed_texts(chunks)

        name = original_name or filepath.name
        unique_name = f'{uuid.uuid4().hex[:8]}_{name}'
        stored_path = DOCS_DIR / unique_name
        if stored_path != filepath:
            shutil.copy2(filepath, stored_path)

        doc_id = add_document(
            filename=name,
            filepath=str(stored_path),
            stored_name=unique_name,
            file_type=ext,
            file_size=file_size,
            clearance=clearance,
        )
        chunk_ids = add_chunks(doc_id, chunks, clearance=clearance)
        self.vs.add(vectors, chunk_ids)

        logger.info('Indexed %s: %d chunks (clearance=%d)', name, len(chunks), clearance)
        return {'doc_id': doc_id, 'chunks': len(chunks)}

    def search(self, query, top_k=TOP_K):
        query_vec = embed_query(query)
        results = self.vs.search(query_vec, top_k)
        if not results:
            return []
        chunk_ids = [r['chunk_id'] for r in results]
        rows = get_chunks_by_ids(chunk_ids)
        row_map = {r['chunk_id']: r for r in rows}
        merged = []
        for r in results:
            cid = r['chunk_id']
            if cid in row_map:
                item = {**row_map[cid], 'score': r['score']}
                text = item.get('chunk_text', '')
                if len(text) > _SNIPPET_MAX_LEN:
                    item['chunk_text'] = text[:_SNIPPET_MAX_LEN] + '...'
                merged.append(item)
            else:
                logger.warning('chunk_id %d not found in DB, skipping', cid)
        return merged

    def search_with_filter(self, query, top_k=TOP_K, allowed_clearance=None,
                           score_floor=_MIN_SCORE_FLOOR, score_ratio=0.65):
        """Search with clearance filtering and two-tier relevance gating.

        1. Over-fetch top_k * N from FAISS.
        2. Filter by clearance (chunk-level, no JOIN needed).
        3. Apply absolute floor: discard everything if top-1 < score_floor.
        4. Apply relative threshold: keep only chunks within score_ratio of top-1.
        5. Return top_k from the surviving set.

        Returns (results, grounded) where grounded is False if no chunks survived.
        """
        fetch_k = max(top_k * _OVER_FETCH_MULTIPLIER, 15)
        query_vec = embed_query(query)
        raw_results = self.vs.search(query_vec, fetch_k)
        if not raw_results:
            return [], False

        chunk_ids = [r['chunk_id'] for r in raw_results]
        rows = get_chunks_by_ids(chunk_ids)
        row_map = {r['chunk_id']: r for r in rows}

        merged = []
        for r in raw_results:
            cid = r['chunk_id']
            if cid not in row_map:
                continue
            item = {**row_map[cid], 'score': r['score']}
            if allowed_clearance is not None and item.get('clearance', 0) > allowed_clearance:
                continue
            merged.append(item)

        if not merged:
            return [], False

        # Absolute floor: reject entire batch if top-1 score is too low
        if merged[0]['score'] < score_floor:
            logger.info('KB search: top-1 score %.4f < floor %.2f, rejecting all', merged[0]['score'], score_floor)
            return [], False

        # Relative threshold: keep only chunks within ratio of top-1
        top_score = merged[0]['score']
        filtered = [r for r in merged if r['score'] >= top_score * score_ratio]

        # Truncate chunk text
        for item in filtered:
            text = item.get('chunk_text', '')
            if len(text) > _SNIPPET_MAX_LEN:
                item['chunk_text'] = text[:_SNIPPET_MAX_LEN] + '...'

        return filtered[:top_k], True

    def list_all(self):
        return list_documents()

    def delete(self, doc_id):
        result = delete_document(doc_id)
        if result is None:
            return None
        doc, chunk_ids = result
        if chunk_ids:
            self.vs.remove(chunk_ids)
        doc_path = Path(doc['filepath'])
        if doc_path.exists():
            doc_path.unlink()
        return doc

    def reset(self):
        self.vs.reset()
        logger.info('Vector store reset')

    @property
    def vector_count(self):
        return self.vs.count()

    @property
    def document_count(self):
        return get_document_count()
