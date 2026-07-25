"""Internal service authentication for backend-to-agent bridge calls."""
from __future__ import annotations

import os

from fastapi import Header, HTTPException

from app.config import get_config


def _service_token() -> str:
    env_token = str(os.getenv("BACKEND_INTERNAL_SERVICE_TOKEN") or "").strip()
    if env_token:
        return env_token
    cfg = get_config()
    internal = cfg.get("internal", {}) or {}
    token = str(internal.get("service_token") or "").strip()
    return token


def require_internal_service(authorization: str | None = Header(None)) -> bool:
    expected = _service_token()
    if not expected:
        raise HTTPException(status_code=503, detail="internal service token is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing internal bearer token")
    actual = authorization.split(" ", 1)[1].strip()
    if actual != expected:
        raise HTTPException(status_code=403, detail="invalid internal bearer token")
    return True
