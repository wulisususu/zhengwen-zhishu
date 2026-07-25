"""Run the server."""
import os
from pathlib import Path

# Load .env file before any other imports
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / '.env'
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
