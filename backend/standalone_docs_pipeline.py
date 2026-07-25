"""
Standalone docs_pipeline service — 独立于主后端 8000 端口运行.

Usage:
    cd /home/youyeetoo/backend
    source /home/youyeetoo/rkllm_model_zoo/funasr_env/bin/activate
    python standalone_docs_pipeline.py --port 8001

Or:
    nohup python standalone_docs_pipeline.py --port 8001 > /home/youyeetoo/backend/data/standalone_docs.log 2>&1 &
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 确保 backend 根目录在 sys.path 中，才能 import app.*
_BACKEND_ROOT = Path(__file__).resolve().parent if __name__ != "__main__" else Path("/home/youyeetoo/backend")
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi import HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("standalone-docs")

# --- App ---
app = FastAPI(title="Docs Pipeline Standalone", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request schema (同步自 docs_pipeline/router.py) ---
class DocPipelineRequest(BaseModel):
    user_input: str = Field(..., min_length=5, description="文档主题")
    section_count: int = Field(default=6, ge=2, le=10, description="章节数")


# --- 核心 pipeline runner ---
# 直接复用现有 runner，跳过 auth 和 File 记录
async def _generate_stream(user_input: str, section_count: int):
    """调用原有 run_pipeline_stream，但绕过 auth."""
    from app.docs_pipeline.runner import run_pipeline_stream

    async for sse in run_pipeline_stream(
        user_input=user_input,
        section_count=section_count,
        user_id=1,  # standalone 固定用户
    ):
        yield sse


# --- Routes ---
@app.post("/api/v1/docs-pipeline/generate")
async def docs_pipeline_generate(req: DocPipelineRequest):
    """文档生成 SSE 端点（无需认证）."""
    return StreamingResponse(
        _generate_stream(req.user_input, req.section_count),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "standalone-docs-pipeline"}


@app.get("/api/v1/files/{file_id}/download")
def download_file(file_id: int):
    """文件下载端点（复用主后端 DB 中的 File 记录）."""
    from app.models import File as FileModel
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        f = db.query(FileModel).filter(FileModel.id == file_id).first()
        if not f:
            raise HTTPException(status_code=404, detail="file not found")
        return FileResponse(f.filepath, filename=f.filename)
    finally:
        db.close()


# --- 静态前端 ---
_static_dir = _BACKEND_ROOT / "app" / "docs_pipeline" / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="doc-generate")


# --- 启动 ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001, help="监听端口 (默认 8001)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    args = parser.parse_args()

    logger.info(f"Standalone docs_pipeline starting on {args.host}:{args.port}")
    logger.info(f"Frontend: http://{args.host}:{args.port}/")
    logger.info(f"Health:   http://{args.host}:{args.port}/api/v1/health")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
