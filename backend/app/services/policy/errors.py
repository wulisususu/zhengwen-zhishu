"""Explicit error codes for policy retrieval. Nothing here leaks raw exceptions."""
from __future__ import annotations

# Stable, documented codes (backend/docs/policy-api.md).
INVALID_QUERY = "INVALID_QUERY"
NOT_CONFIGURED = "POLICY_NOT_CONFIGURED"
DISABLED = "POLICY_DISABLED"
EGRESS_BLOCKED = "EGRESS_BLOCKED"
REMOTE_TIMEOUT = "REMOTE_TIMEOUT"
REMOTE_HTTP_ERROR = "REMOTE_HTTP_ERROR"
REMOTE_UNAVAILABLE = "REMOTE_UNAVAILABLE"
REMOTE_BAD_RESPONSE = "REMOTE_BAD_RESPONSE"
STORE_ERROR = "STORE_ERROR"
INTERNAL_ERROR = "INTERNAL_ERROR"

# Import / fetch (SSRF guard). Fetch failures never fabricate text; callers
# return MANUAL_UPLOAD_HINT so the operator can upload the file instead.
FETCH_BAD_URL = "FETCH_BAD_URL"
FETCH_HOST_NOT_ALLOWED = "FETCH_HOST_NOT_ALLOWED"
FETCH_PRIVATE_ADDRESS = "FETCH_PRIVATE_ADDRESS"
FETCH_DNS_FAILED = "FETCH_DNS_FAILED"
FETCH_TOO_MANY_REDIRECTS = "FETCH_TOO_MANY_REDIRECTS"
FETCH_TOO_LARGE = "FETCH_TOO_LARGE"
FETCH_TIMEOUT = "FETCH_TIMEOUT"
FETCH_HTTP_ERROR = "FETCH_HTTP_ERROR"
FETCH_FAILED = "FETCH_FAILED"
FETCH_UNSUPPORTED_CONTENT = "FETCH_UNSUPPORTED_CONTENT"
UNSUPPORTED_FILE = "UNSUPPORTED_FILE"
EXTRACT_FAILED = "EXTRACT_FAILED"
EMPTY_CONTENT = "EMPTY_CONTENT"
NOT_FOUND = "NOT_FOUND"
INVALID_STATUS = "INVALID_STATUS"

MANUAL_UPLOAD_HINT = (
    "抓取失败时不会生成或编造正文。可改为人工上传原文文件："
    "POST /api/v1/gov/policies/import（multipart，字段 file，可附 source_url 保持同一版本链）。"
)


class PolicyError(Exception):
    """A failure with a stable code and a user-facing (Chinese) message."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}
