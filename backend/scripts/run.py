"""Run the server."""
import sys
from pathlib import Path

# 确保 backend 根目录在 sys.path 中，才能 import app.*
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import os

# Load .env file before any other imports
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print("Runtime environment loaded")
except ImportError:
    pass

import uvicorn
from app.config import get_config

if __name__ == "__main__":
    cfg = get_config()["server"]
    # Stage A: the process-local PPT limiter is deployment-global only with one worker.
    uvicorn.run("app.main:app", host=cfg["host"], port=cfg["port"], reload=False, workers=1)
