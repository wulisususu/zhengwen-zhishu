"""KB database schema and helpers.

Tables:
  documents  -- one row per indexed file
  chunks     -- 500-char embedding chunks, FK to documents
  vector_index_map  -- FAISS faiss_id -> chunk_id mapping
  kb_audit_logs     -- search audit trail
"""
import sqlite3
import logging
from pathlib import Path
from app.kb.config import DB_PATH

logger = logging.getLogger('app.kb.db')


def get_conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

def _migrate(conn):
    """Apply schema migrations for existing databases."""

    # --- documents table ----------------------------------------------------
    doc_cols = {row[1] for row in conn.execute('PRAGMA table_info(documents)').fetchall()}

    if 'stored_name' not in doc_cols:
        logger.info('Migrating documents: adding stored_name')
        conn.execute('ALTER TABLE documents ADD COLUMN stored_name TEXT DEFAULT ""')
        conn.execute('UPDATE documents SET stored_name = filename WHERE stored_name = ""')
        conn.commit()

    if 'clearance' not in doc_cols:
        logger.info('Migrating documents: adding clearance')
        conn.execute('ALTER TABLE documents ADD COLUMN clearance INTEGER DEFAULT 0')
        conn.commit()

    # 资源隔离：文档归属用户（NULL = 历史存量文档，按「仅管理员可见」处理）
    if 'owner_user_id' not in doc_cols:
        logger.info('Migrating documents: adding owner_user_id')
        conn.execute('ALTER TABLE documents ADD COLUMN owner_user_id INTEGER DEFAULT NULL')
        conn.commit()
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_kb_documents_owner ON documents(owner_user_id)'
    )
    conn.commit()

    # New unified-parse columns
    _add_col_if_missing(conn, 'documents', doc_cols, 'source_ref', 'TEXT DEFAULT ""')
    _add_col_if_missing(conn, 'documents', doc_cols, 'content_hash', 'TEXT DEFAULT ""')
    _add_col_if_missing(conn, 'documents', doc_cols, 'parser_version', 'TEXT DEFAULT ""')
    _add_col_if_missing(conn, 'documents', doc_cols, 'embedding_model', 'TEXT DEFAULT ""')
    _add_col_if_missing(conn, 'documents', doc_cols, 'indexed_at', 'TEXT DEFAULT ""')

    # Unique index on source_ref (nullable-safe: empty string is ok)
    conn.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_documents_source_ref '
        'ON documents(source_ref) WHERE source_ref != ""'
    )
    conn.commit()

    # --- chunks table -------------------------------------------------------
    chunk_cols = {row[1] for row in conn.execute('PRAGMA table_info(chunks)').fetchall()}

    needs_rebuild = 'faiss_id' in chunk_cols
    if 'clearance' not in chunk_cols:
        logger.info('Migrating chunks: adding clearance')
        conn.execute('ALTER TABLE chunks ADD COLUMN clearance INTEGER DEFAULT 0')
        conn.execute('UPDATE chunks SET clearance = 0 WHERE clearance IS NULL')
        conn.commit()

    # New provenance columns for dual-layer chunking
    _add_col_if_missing(conn, 'chunks', chunk_cols, 'parsed_file_id', 'INTEGER DEFAULT 0')
    _add_col_if_missing(conn, 'chunks', chunk_cols, 'parent_parsed_chunk_id', 'INTEGER DEFAULT 0')
    _add_col_if_missing(conn, 'chunks', chunk_cols, 'page_no', 'INTEGER DEFAULT 0')
    _add_col_if_missing(conn, 'chunks', chunk_cols, 'start_offset', 'INTEGER DEFAULT 0')
    _add_col_if_missing(conn, 'chunks', chunk_cols, 'end_offset', 'INTEGER DEFAULT 0')
    _add_col_if_missing(conn, 'chunks', chunk_cols, 'source_ref', 'TEXT DEFAULT ""')

    if needs_rebuild:
        logger.info('Migrating chunks: removing old faiss_id column')
        conn.executescript("""
            CREATE TABLE chunks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                clearance INTEGER DEFAULT 0,
                parsed_file_id INTEGER DEFAULT 0,
                parent_parsed_chunk_id INTEGER DEFAULT 0,
                page_no INTEGER DEFAULT 0,
                start_offset INTEGER DEFAULT 0,
                end_offset INTEGER DEFAULT 0,
                source_ref TEXT DEFAULT '',
                FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE,
                UNIQUE(doc_id, chunk_index)
            );
            INSERT INTO chunks_new (id, doc_id, chunk_index, chunk_text, clearance)
                SELECT id, doc_id, chunk_index, chunk_text, clearance FROM chunks;
            DROP TABLE chunks;
            ALTER TABLE chunks_new RENAME TO chunks;
            CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
        """)
        conn.commit()

    # --- vector_index_map table ---------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vector_index_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            index_name TEXT DEFAULT 'default',
            faiss_id INTEGER NOT NULL,
            chunk_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            source_ref TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_vector_map_chunk_id ON vector_index_map(chunk_id)'
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_vector_map_source_ref ON vector_index_map(source_ref)'
    )
    conn.commit()

    # --- audit log table ----------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kb_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            query TEXT NOT NULL,
            hit_chunk_ids TEXT,
            hit_filenames TEXT,
            clearance INTEGER DEFAULT 0,
            answer_snippet TEXT,
            grounded INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()


def _add_col_if_missing(conn, table, existing_cols, col_name, col_type):
    if col_name not in existing_cols:
        logger.info('Migrating %s: adding %s', table, col_name)
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {col_name} {col_type}')
        conn.commit()
        existing_cols.add(col_name)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            stored_name TEXT DEFAULT '',
            filepath TEXT NOT NULL UNIQUE,
            file_type TEXT,
            file_size INTEGER,
            chunk_count INTEGER DEFAULT 0,
            clearance INTEGER DEFAULT 0,
            source_ref TEXT DEFAULT '',
            content_hash TEXT DEFAULT '',
            parser_version TEXT DEFAULT '',
            embedding_model TEXT DEFAULT '',
            indexed_at TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            clearance INTEGER DEFAULT 0,
            parsed_file_id INTEGER DEFAULT 0,
            parent_parsed_chunk_id INTEGER DEFAULT 0,
            page_no INTEGER DEFAULT 0,
            start_offset INTEGER DEFAULT 0,
            end_offset INTEGER DEFAULT 0,
            source_ref TEXT DEFAULT '',
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE,
            UNIQUE(doc_id, chunk_index)
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
        CREATE TABLE IF NOT EXISTS vector_index_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            index_name TEXT DEFAULT 'default',
            faiss_id INTEGER NOT NULL,
            chunk_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            source_ref TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_vector_map_chunk_id ON vector_index_map(chunk_id);
        CREATE INDEX IF NOT EXISTS idx_vector_map_source_ref ON vector_index_map(source_ref);
        CREATE TABLE IF NOT EXISTS kb_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            query TEXT NOT NULL,
            hit_chunk_ids TEXT,
            hit_filenames TEXT,
            clearance INTEGER DEFAULT 0,
            answer_snippet TEXT,
            grounded INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
    """)
    conn.commit()
    _migrate(conn)
    conn.close()


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def add_document(filename, filepath, stored_name='', file_type=None, file_size=0,
                 clearance=0, source_ref='', content_hash='', parser_version='',
                 embedding_model='', indexed_at='', owner_user_id=None):
    conn = get_conn()
    cur = conn.execute(
        'INSERT INTO documents (filename, stored_name, filepath, file_type, file_size, '
        'clearance, source_ref, content_hash, parser_version, embedding_model, indexed_at, owner_user_id) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (filename, stored_name or filename, filepath, file_type, file_size,
         clearance, source_ref, content_hash, parser_version, embedding_model, indexed_at,
         owner_user_id)
    )
    doc_id = cur.lastrowid
    conn.commit()
    conn.close()
    return doc_id


def get_document_owner(doc_id):
    """返回文档归属用户 id；文档不存在返回 None。NULL=历史存量文档。"""
    conn = get_conn()
    row = conn.execute('SELECT owner_user_id FROM documents WHERE id = ?', (doc_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return row['owner_user_id']


def get_document_owner_row(doc_id):
    """区分「文档不存在」与「文档存在但 owner 为 NULL」。"""
    conn = get_conn()
    row = conn.execute('SELECT id, owner_user_id FROM documents WHERE id = ?', (doc_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_document_ids(owner_user_id):
    """某用户可检索的文档 id 列表（用于语义检索的权限过滤）。"""
    conn = get_conn()
    if owner_user_id is None:
        rows = conn.execute('SELECT id FROM documents').fetchall()
    else:
        rows = conn.execute(
            'SELECT id FROM documents WHERE owner_user_id = ?', (owner_user_id,)
        ).fetchall()
    conn.close()
    return [r['id'] for r in rows]


def get_document_clearance(doc_id):
    conn = get_conn()
    row = conn.execute('SELECT clearance FROM documents WHERE id = ?', (doc_id,)).fetchone()
    conn.close()
    return row['clearance'] if row else 0


def add_chunks(doc_id, chunks, clearance=0, parsed_file_id=0,
               parent_parsed_chunk_id=0, page_no=0, start_offset=0,
               end_offset=0, source_ref=''):
    """Insert chunks with provenance info for dual-layer retrieval."""
    conn = get_conn()
    chunk_ids = []
    for i, text in enumerate(chunks):
        cur = conn.execute(
            'INSERT INTO chunks (doc_id, chunk_index, chunk_text, clearance, '
            'parsed_file_id, parent_parsed_chunk_id, page_no, start_offset, end_offset, source_ref) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (doc_id, i, text, clearance,
             parsed_file_id, parent_parsed_chunk_id, page_no,
             start_offset, end_offset, source_ref)
        )
        chunk_ids.append(cur.lastrowid)
    conn.execute(
        'UPDATE documents SET chunk_count = ?, updated_at = datetime("now", "localtime") WHERE id = ?',
        (len(chunks), doc_id)
    )
    conn.commit()
    conn.close()
    return chunk_ids


def add_vector_mappings(chunk_ids, document_id, source_ref=''):
    """Write faiss_id -> chunk_id mappings to vector_index_map."""
    conn = get_conn()
    for cid in chunk_ids:
        conn.execute(
            'INSERT INTO vector_index_map (faiss_id, chunk_id, document_id, source_ref) '
            'VALUES (?, ?, ?, ?)',
            (cid, cid, document_id, source_ref)
        )
    conn.commit()
    conn.close()


def get_chunks_by_ids(chunk_ids):
    conn = get_conn()
    placeholders = ','.join('?' * len(chunk_ids))
    rows = conn.execute(
        f'SELECT c.id as chunk_id, c.chunk_text, c.chunk_index, c.clearance, '
        f'c.parsed_file_id, c.parent_parsed_chunk_id, c.page_no, '
        f'c.start_offset, c.end_offset, c.source_ref, '
        f'd.filename, d.filepath '
        f'FROM chunks c JOIN documents d ON c.doc_id = d.id '
        f'WHERE c.id IN ({placeholders})',
        chunk_ids
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_chunk_ids_for_doc(doc_id):
    conn = get_conn()
    rows = conn.execute('SELECT id FROM chunks WHERE doc_id = ?', (doc_id,)).fetchall()
    conn.close()
    return [r['id'] for r in rows]


def get_chunks_for_document_ids(doc_ids):
    """Return indexed chunks for explicitly selected knowledge documents."""
    if not doc_ids:
        return []
    conn = get_conn()
    placeholders = ','.join('?' * len(doc_ids))
    rows = conn.execute(
        'SELECT c.id AS chunk_id, c.doc_id, c.chunk_index, c.chunk_text, d.filename '
        'FROM chunks c JOIN documents d ON d.id = c.doc_id '
        'WHERE c.doc_id IN ({}) ORDER BY c.doc_id, c.chunk_index'.format(placeholders),
        doc_ids,
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_document_by_source_ref(source_ref):
    conn = get_conn()
    row = conn.execute(
        'SELECT * FROM documents WHERE source_ref = ?', (source_ref,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_documents(owner_user_id=None):
    """列出文档。owner_user_id=None 表示不按归属过滤（仅管理员使用）。"""
    conn = get_conn()
    cols = ('id, filename, stored_name, file_type, file_size, chunk_count, '
            'source_ref, content_hash, indexed_at, created_at, owner_user_id')
    if owner_user_id is None:
        rows = conn.execute(
            f'SELECT {cols} FROM documents ORDER BY id DESC'
        ).fetchall()
    else:
        rows = conn.execute(
            f'SELECT {cols} FROM documents WHERE owner_user_id = ? ORDER BY id DESC',
            (owner_user_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_documents_by_ids(doc_ids, owner_user_id=None):
    """Fetch knowledge documents by id (used to resolve message knowledge refs)."""
    if not doc_ids:
        return []
    conn = get_conn()
    placeholders = ','.join('?' * len(doc_ids))
    params = list(doc_ids)
    where = f'id IN ({placeholders})'
    if owner_user_id is not None:
        where += ' AND owner_user_id = ?'
        params.append(owner_user_id)
    rows = conn.execute(
        'SELECT id, filename, stored_name, file_type, file_size, chunk_count, '
        'source_ref, content_hash, indexed_at, created_at, owner_user_id '
        f'FROM documents WHERE {where}',
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_document(doc_id):
    conn = get_conn()
    doc = conn.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)).fetchone()
    if not doc:
        conn.close()
        return None
    chunk_ids = [r['id'] for r in
                 conn.execute('SELECT id FROM chunks WHERE doc_id = ?', (doc_id,)).fetchall()]
    conn.execute('DELETE FROM vector_index_map WHERE document_id = ?', (doc_id,))
    conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
    conn.commit()
    conn.close()
    return dict(doc), chunk_ids


def delete_chunks_for_doc(doc_id):
    """Delete all chunks and vector mappings for a document (used for rebuild)."""
    conn = get_conn()
    chunk_ids = [r['id'] for r in
                 conn.execute('SELECT id FROM chunks WHERE doc_id = ?', (doc_id,)).fetchall()]
    conn.execute('DELETE FROM vector_index_map WHERE document_id = ?', (doc_id,))
    conn.execute('DELETE FROM chunks WHERE doc_id = ?', (doc_id,))
    conn.commit()
    conn.close()
    return chunk_ids


def get_document_count():
    conn = get_conn()
    count = conn.execute('SELECT COUNT(*) as cnt FROM documents').fetchone()['cnt']
    conn.close()
    return count


def get_all_chunk_ids():
    conn = get_conn()
    rows = conn.execute('SELECT id FROM chunks').fetchall()
    conn.close()
    return {r['id'] for r in rows}


def get_all_chunks_with_doc():
    """Return all chunks with their document info, for index rebuild."""
    conn = get_conn()
    rows = conn.execute(
        'SELECT c.id as chunk_id, c.chunk_text, c.clearance, c.parsed_file_id, '
        'c.parent_parsed_chunk_id, c.page_no, c.source_ref, '
        'd.filename, d.id as doc_id '
        'FROM chunks c JOIN documents d ON c.doc_id = d.id ORDER BY c.id'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_audit_log(user_id, query, hit_chunk_ids=None, hit_filenames=None,
                     clearance=0, answer_snippet='', grounded=False):
    conn = get_conn()
    conn.execute(
        'INSERT INTO kb_audit_logs (user_id, query, hit_chunk_ids, hit_filenames, '
        'clearance, answer_snippet, grounded) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (user_id, query,
         ','.join(str(i) for i in hit_chunk_ids) if hit_chunk_ids else '',
         ','.join(hit_filenames) if hit_filenames else '',
         clearance,
         (answer_snippet or '')[:500],
         1 if grounded else 0)
    )
    conn.commit()
    conn.close()
