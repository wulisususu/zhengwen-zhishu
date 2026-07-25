"""Health check endpoint."""
from fastapi import APIRouter
from app.errors import ok
from datetime import datetime

router = APIRouter()


@router.get("/health")
def health():
    return ok(data={
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.1.0",
    })
