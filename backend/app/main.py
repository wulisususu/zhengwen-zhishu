"""FastAPI main app."""
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_config
from app.database import init_db
from app.errors import AppError
from app.routers import health, auth, users, conversations, chat, files, knowledge, asr, tts, settings, system, documents, internal, policy, gov_policy
from app.minicpm_pipeline.router import router as minicpm_documents_router
from app.docs_pipeline import router as docs_pipeline_router
from app.gongwen.router import router as gongwen_router
from app.policy.router import router as policy_router
from app.PPT_master import router as ppt_master_router
from app.routers import gov_docs  # 公文生成与审校（gongwen-kit）；单独一行，避免与其他分支改同一行
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.gov.router import router as gov_router

cfg = get_config()
logging.basicConfig(level=getattr(logging, cfg["logging"]["level"]), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("app")

app = FastAPI(title="政文智枢 · 政务办公智能体", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

API = "/api/v1"
app.include_router(health.router,        prefix=API)
app.include_router(auth.router,          prefix=API)
app.include_router(users.router,         prefix=API)
app.include_router(conversations.router, prefix=API)
# DISABLED: only OpenClaw path -- app.include_router(chat.router, prefix=API)
app.include_router(files.router,         prefix=API)
app.include_router(knowledge.router,     prefix=API)
app.include_router(asr.router,           prefix=API)
app.include_router(tts.router,           prefix=API)
app.include_router(settings.router,      prefix=API)
app.include_router(system.router,        prefix=API)
app.include_router(documents.router,     prefix=API)
app.include_router(internal.router,      prefix=API)
app.include_router(policy.router,        prefix=API)
app.include_router(gov_policy.router,    prefix=API)
app.include_router(minicpm_documents_router, prefix=API)
app.include_router(docs_pipeline_router, prefix=API)
app.include_router(gongwen_router,        prefix=API)
app.include_router(policy_router,         prefix=API)
app.include_router(ppt_master_router,   prefix=API)
app.include_router(gov_router, prefix=API)
app.include_router(gov_docs.router,     prefix=API)

# docs_pipeline v3 standalone frontend
_docs_static = Path(__file__).resolve().parent / "docs_pipeline" / "static"
_docs_static.mkdir(parents=True, exist_ok=True)
app.mount("/doc-generate", StaticFiles(directory=str(_docs_static), html=True), name="doc-generate")

@app.on_event("startup")
def startup():
    init_db()
    logger.info("Database initialized")

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=400 if exc.code >= 400 and exc.code < 600 else exc.code,
        content={"code": exc.code, "message": exc.message, "data": None},
    )
