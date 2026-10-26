"""Unified response helper and error codes."""
from app.schemas import R
from fastapi.responses import JSONResponse
import uuid


def ok(data=None, message="ok") -> dict:
    return R(code=0, message=message, data=data, trace_id=uuid.uuid4().hex[:16]).model_dump()


def fail(code: int, message: str, data=None) -> dict:
    return R(code=code, message=message, data=data, trace_id=uuid.uuid4().hex[:16]).model_dump()


class AppError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message


# Error codes
ERR_AUTH = 40100
ERR_NOT_FOUND = 40400
ERR_PARAM = 40000
ERR_INTERNAL = 50000
ERR_ASR = 50100
ERR_POLICY = 50200  # policy retrieval; detail in data.error.code (see docs/policy-api.md)
