"""One-time backfill for stored_name column in documents table."""
import sqlite3
from pathlib import Path

DB_PATH = '/home/youyeetoo/rkllm_model_zoo/local_kb/data/db/knowledge.db'

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT id, filepath, stored_name FROM documents WHERE stored_name = '' OR stored_name IS NULL"
).fetchall()

for r in rows:
    basename = Path(r['filepath']).name
    conn.execute('UPDATE documents SET stored_name = ? WHERE id = ?', (basename, r['id']))
    print(f'  doc {r["id"]}: stored_name -> {basename}')

conn.commit()
conn.close()
print(f'Backfilled {len(rows)} documents.')
