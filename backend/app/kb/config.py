import os
from pathlib import Path

os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')

LOCAL_KB_MODELS = Path("/home/youyeetoo/rkllm_model_zoo/local_kb/models")
KB_DATA_DIR = Path("/home/youyeetoo/rkllm_model_zoo/local_kb/data")
DOCS_DIR = KB_DATA_DIR / 'docs'
DB_DIR = KB_DATA_DIR / 'db'
VECTOR_DIR = KB_DATA_DIR / 'vector'
DB_PATH = DB_DIR / 'knowledge.db'

EMBEDDING_MODEL_NAME = 'BAAI/bge-small-zh'
EMBEDDING_DIM = 512  # bge-small-zh output dimension
EMBEDDING_DEVICE = 'cpu'

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K = 3

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
KB_EMBEDDING_IDLE_TIMEOUT = 1800   # 30 minutes

ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".log",
    ".pdf", ".docx", ".xlsx",
}

for d in [DOCS_DIR, DB_DIR, VECTOR_DIR, LOCAL_KB_MODELS]:
    d.mkdir(parents=True, exist_ok=True)
