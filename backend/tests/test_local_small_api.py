"""Integration tests for /internal/local-small/generate endpoint."""
import os
import pytest
import requests

BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000")
TOKEN = os.getenv("BACKEND_INTERNAL_SERVICE_TOKEN", "change-me-internal-service-token")
API = f"{BASE_URL}/api/v1/internal/local-small/generate"


def _headers(token=TOKEN):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


class TestLocalSmallGenerate:
    def test_normal_call(self):
        resp = requests.post(API, json={"prompt": "帮我写周报", "mode": "general"}, headers=_headers(), timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        result = data["data"]
        assert "text" in result
        assert result["source"] == "local-small"
        assert result["mode"] == "general"
        assert isinstance(result["fallback"], bool)

    def test_voice_refine_mode(self):
        resp = requests.post(API, json={"prompt": "那个啥帮我弄个月报", "mode": "voice_refine"}, headers=_headers(), timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["mode"] == "voice_refine"

    def test_missing_prompt_returns_error(self):
        resp = requests.post(API, json={"mode": "general"}, headers=_headers(), timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] != 0

    def test_invalid_mode_returns_error(self):
        resp = requests.post(API, json={"prompt": "test", "mode": "invalid_mode"}, headers=_headers(), timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] != 0

    def test_missing_token_returns_401(self):
        resp = requests.post(API, json={"prompt": "test"}, headers=_headers(token="wrong-token"), timeout=10)
        assert resp.status_code in (401, 403)

    def test_response_shape(self):
        resp = requests.post(API, json={"prompt": "你好"}, headers=_headers(), timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert "code" in data
        assert "data" in data
        result = data["data"]
        assert "text" in result
        assert "source" in result
        assert "fallback" in result
