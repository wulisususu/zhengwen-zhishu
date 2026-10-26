"""Isolated acceptance server using the SAME real auth/gov routers as app.main.

Optional OCR, knowledge-base and PPT model runtimes are not imported here.
AI_BOX_DATA_DIR, BACKEND_CONFIG_FILE and GOV_DATA_DIR must point to isolated data.
Production's complete app.main also mounts the government router.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.database import Base, engine
from app.routers.auth import router as auth_router
from .router import router


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Government integration acceptance", lifespan=lifespan)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    return {"status": "healthy", "scope": "government-integration", "models_verified": False}
