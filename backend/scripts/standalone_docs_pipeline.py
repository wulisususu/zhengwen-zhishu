"""
Standalone docs_pipeline service — 独立于主后端 8000 端口运行.

安全基线（本次加固）：
- 所有端点都要求有效的登录 token（与主后端同一套 JWT）
- 文件下载校验归属：普通用户只能下载自己的文件，管理员不受限
- CORS 默认不开放；确需跨域时用 STANDALONE_CORS_ORIGINS 显式列出来源
- 默认只监听 127.0.0.1，需要对外暴露时必须显式 --host 0.0.0.0

Usage:
    cd /home/youyeetoo/InNet_box/backend
    source /home/youyeetoo/rkllm_model_zoo/funasr_env/bin/activate
    python scripts/standalone_docs_pipeline.py --port 8001

    对外暴露（不推荐，需自备反代与访问控制）：
    python scripts/standalone_docs_pipeline.py --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# 确保 backend 根目录在 sys.path 中，才能 import app.*
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.models import User

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("standalone-docs")

# --- App ---
app = FastAPI(title="Docs Pipeline Standalone", version="3.1")

# CORS 默认关闭；只有显式配置了来源才放行，且不使用通配符 + credentials 组合
_cors_origins = [o.strip() for o in str(os.getenv("STANDALONE_CORS_ORIGINS") or "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    logger.info("CORS 已按显式白名单开放：%s", _cors_origins)
else:
    logger.info("CORS 未开放（默认）。如需跨域请设置 STANDALONE_CORS_ORIGINS")


# --- Request schema (同步自 docs_pipeline/router.py) ---
class DocPipelineRequest(BaseModel):
    user_input: str = Field(..., min_length=5, description="文档主题")
    section_count: int = Field(default=6, ge=2, le=10, description="章节数")


# --- 核心 pipeline runner ---
async def _generate_stream(user_input: str, section_count: int, user_id: int):
    """调用原有 run_pipeline_stream，使用当前登录用户的身份。"""
    from app.docs_pipeline.runner import run_pipeline_stream

    async for sse in run_pipeline_stream(
        user_input=user_input,
        section_count=section_count,
        user_id=user_id,
    ):
        yield sse


# --- Routes ---
@app.post("/api/v1/docs-pipeline/generate")
async def docs_pipeline_generate(
    req: DocPipelineRequest,
    user: User = Depends(get_current_user),
):
    """文档生成 SSE 端点（需要登录）。"""
    logger.info("docs-pipeline generate: user=%s sections=%s", user.id, req.section_count)
    return StreamingResponse(
        _generate_stream(req.user_input, req.section_count, user.id),
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
def download_file(file_id: int, user: User = Depends(get_current_user)):
    """文件下载端点（需要登录 + 归属校验）。"""
    from app.models import File as FileModel
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        f = db.query(FileModel).filter(FileModel.id == file_id).first()
        if not f:
            raise HTTPException(status_code=404, detail="file not found")
        owner_id = f.owner_user_id if f.owner_user_id is not None else f.user_id
        if not getattr(user, "is_admin", False) and owner_id != user.id:
            # 不区分「不存在」与「无权限」，避免枚举他人文件 id
            raise HTTPException(status_code=404, detail="file not found")
        path = Path(f.filepath or "")
        if not path.exists():
            raise HTTPException(status_code=404, detail="file not found on disk")
        return FileResponse(str(path), filename=f.filename)
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
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="监听地址（默认仅本机 127.0.0.1；对外暴露请显式指定 0.0.0.0 并自备访问控制）",
    )
    args = parser.parse_args()

    if args.host == "0.0.0.0":
        logger.warning("独立文档服务监听 0.0.0.0：所有端点仍要求登录，请确认网络边界与反代配置")

    logger.info(f"Standalone docs_pipeline starting on {args.host}:{args.port}")
    logger.info(f"Frontend: http://{args.host}:{args.port}/")
    logger.info(f"Health:   http://{args.host}:{args.port}/api/v1/health")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
