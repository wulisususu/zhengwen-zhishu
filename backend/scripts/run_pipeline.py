"""Standalone docs-pipeline server — port 8003. 自包含静态前端 + API."""
import sys as _s, pathlib as _p; _s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.docs_pipeline.router import router as pipeline_router

app = FastAPI(title="Docs Pipeline", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(pipeline_router, prefix="/api/v1")

# 挂载静态前端，跟 8000 一样
_static = Path(__file__).resolve().parent.parent / "app" / "docs_pipeline" / "static"
_static.mkdir(parents=True, exist_ok=True)
app.mount("/doc-generate", StaticFiles(directory=str(_static), html=True), name="doc-generate")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)
