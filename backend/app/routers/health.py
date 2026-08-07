"""OpenClaw-aware health endpoints with safe, opt-in deep checks."""
from datetime import datetime, timedelta, timezone
import json
import re
import subprocess
import os
import hmac
from pathlib import Path
from typing import Optional

import requests
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text

from app.database import SessionLocal
from app.errors import ok

router = APIRouter()
BASE = Path(__file__).resolve().parent.parent.parent
PI_AGENT = BASE / ".pi-agent"
CHAT_PORT, DOC_PORT, BACKEND_PORT = 18790, 18791, 8000


def _run(command: list[str], timeout: int = 8) -> str:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def _service_active(name: str) -> bool:
    return _run(["systemctl", "--user", "is-active", name]).strip() == "active"


def _http_get(url: str, timeout: int = 5) -> tuple[bool, str]:
    try:
        response = requests.get(url, timeout=timeout)
        return response.status_code == 200, response.text[:160]
    except Exception as exc:
        return False, str(exc)[:160]


def _port_listener_count(port: int) -> int:
    out = _run(["ss", "-tlnp"])
    pids = set()
    for line in out.splitlines():
        if f":{port} " not in line:
            continue
        pids.update(re.findall(r"pid=(\d+)", line))
    return len(pids)


def _configured_model() -> dict:
    try:
        from app.services.model_config import get_35b_config
        cfg = get_35b_config()
        return {
            "base_url": cfg["base_url"],
            "model": cfg["model"],
            "context_window": cfg["context_window"],
            "max_tokens": cfg["max_tokens"],
            "api_key_configured": bool(cfg["api_key"]),
        }
    except Exception as exc:
        return {"error": str(exc)[:160]}


def _recent_doc_tasks(hours: int) -> dict:
    db = SessionLocal()
    try:
        row = db.execute(text(
            "SELECT COUNT(*), SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) "
            "FROM document_tasks WHERE updated_at > datetime('now', :window)"
        ), {"window": f"-{hours} hours"}).fetchone()
        total, done = int(row[0] or 0), int(row[1] or 0)
        return {"total": total, "done": done, "not_done": total - done}
    except Exception as exc:
        return {"error": str(exc)[:160]}
    finally:
        db.close()


def _journal_counts(hours: int) -> dict:
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    result = {"abort_error": 0, "context_overflow": 0, "auth_error": 0, "fallback": 0, "recent": []}
    for service in ("openclaw-chat.service", "openclaw-doc.service"):
        text_out = _run(["journalctl", "--user", "-u", service, "--since", since, "--no-pager"], timeout=15)
        for line in text_out.splitlines():
            lower = line.lower()
            if "aborterror" in lower or "operation was aborted" in lower:
                result["abort_error"] += 1
            if "context-overflow" in lower or "context overflow" in lower:
                result["context_overflow"] += 1
            if "401" in lower or "unauthorized" in lower:
                result["auth_error"] += 1
            if "falling back" in lower or "fallback" in lower:
                result["fallback"] += 1
            if any(token in lower for token in ("aborterror", "context-overflow", "unauthorized", "falling back")):
                result["recent"].append(line[-240:])
    result["recent"] = result["recent"][-8:]
    return result


def _deep_model_probe() -> dict:
    try:
        from app.services.model_config import get_35b_config, test_connectivity, test_tool_call
        cfg = get_35b_config()
        connected, connection_message = test_connectivity(cfg["base_url"], cfg["api_key"], cfg["model"], timeout=30)
        tool_ok, tool_message = (False, "skipped") if not connected else test_tool_call(
            cfg["base_url"], cfg["api_key"], cfg["model"], timeout=30
        )
        return {
            "checked": True,
            "connectivity": {"ok": connected, "message": connection_message},
            "tool_call": {"ok": tool_ok, "message": tool_message},
        }
    except Exception as exc:
        return {"checked": True, "connectivity": {"ok": False, "message": str(exc)[:160]}, "tool_call": {"ok": False, "message": "skipped"}}


def collect_openclaw_health(*, deep: bool = False, hours: int = 12) -> dict:
    hours = min(max(int(hours), 1), 168)
    services = {
        "chat": _service_active("openclaw-chat.service"),
        "doc": _service_active("openclaw-doc.service"),
        "legacy_gateway": _service_active("openclaw-gateway.service"),
    }
    agents = {}
    for key, port in (("chat", CHAT_PORT), ("doc", DOC_PORT)):
        http_ok, body = _http_get(f"http://127.0.0.1:{port}/health")
        agents[key] = {"http_ok": http_ok, "listener_count": _port_listener_count(port), "response": body}
    model = _configured_model()
    events = _journal_counts(hours)
    deep_probe = _deep_model_probe() if deep else {"checked": False}
    core_ok = services["chat"] and services["doc"] and all(v["http_ok"] and v["listener_count"] == 1 for v in agents.values())
    warnings = []
    if not services["legacy_gateway"]:
        warnings.append("legacy openclaw-gateway.service is failed/disabled; chat/doc use independent services")
    if events["abort_error"] or events["context_overflow"] or events["auth_error"]:
        warnings.append("new OpenClaw errors detected in reporting window")
    if deep and not (deep_probe.get("connectivity", {}).get("ok") and deep_probe.get("tool_call", {}).get("ok")):
        warnings.append("external model deep probe failed")
    verdict = "healthy" if core_ok and not warnings[1:] else ("degraded" if core_ok else "unhealthy")
    return {
        "verdict": verdict,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "window_hours": hours,
        "services": services,
        "agents": agents,
        "configured_model": model,
        "events": events,
        "document_tasks": _recent_doc_tasks(hours),
        "deep_probe": deep_probe,
        "warnings": warnings,
    }


@router.get("/health")
def health():
    return ok(data={"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat(), "version": "0.1.0"})


@router.post("/health/detailed")
def health_detailed(deep: bool = False, hours: int = 12, x_health_token: str | None = Header(default=None)):
    """Protected detailed report. deep=true performs paid external model probes."""
    expected = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
    if not expected or not x_health_token or not hmac.compare_digest(x_health_token, expected):
        raise HTTPException(status_code=401, detail="health report authorization required")
    return ok(data=collect_openclaw_health(deep=deep, hours=hours))
