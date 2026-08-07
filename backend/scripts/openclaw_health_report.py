#!/usr/bin/env python3
"""Safe periodic OpenClaw health report. It never restarts services or deletes data."""
from __future__ import annotations
import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BACKEND = Path("/home/youyeetoo/INnet_agent/backend")
sys.path.insert(0, str(BACKEND / "app" / "services"))
from model_config import get_35b_config, test_connectivity, test_tool_call  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--hours", type=int, default=12)
parser.add_argument("--deep", action="store_true", help="probe external model and OpenAI tool calling")
args = parser.parse_args()
hours = min(max(args.hours, 1), 168)


def run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def active(name):
    return run(["systemctl", "--user", "is-active", name]).strip() == "active"


def agent(port):
    try:
        r = requests.get(f"http://127.0.0.1:{port}/health", timeout=5)
        ok = r.status_code == 200
        return {"http_ok": ok, "response": r.text[:160]}
    except Exception as e:
        return {"http_ok": False, "response": str(e)[:160]}


def journal_events():
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    result = {"abort_error": 0, "context_overflow": 0, "auth_error": 0, "fallback": 0, "recent": []}
    for unit in ("openclaw-chat.service", "openclaw-doc.service"):
        for line in run(["journalctl", "--user", "-u", unit, "--since", since, "--no-pager"], 20).splitlines():
            low = line.lower()
            for key, needles in {
                "abort_error": ("aborterror", "operation was aborted"),
                "context_overflow": ("context-overflow", "context overflow"),
                "auth_error": ("unauthorized", " 401"),
                "fallback": ("falling back",),
            }.items():
                if any(n in low for n in needles):
                    result[key] += 1
                    result["recent"].append(line[-240:])
                    break
    result["recent"] = result["recent"][-8:]
    return result


def documents():
    try:
        db = sqlite3.connect(BACKEND / "data" / "app.db")
        total, done = db.execute(
            "SELECT COUNT(*), SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) FROM document_tasks WHERE updated_at > datetime('now', ?)",
            (f"-{hours} hours",),
        ).fetchone()
        db.close()
        return {"total": int(total or 0), "done": int(done or 0), "not_done": int((total or 0) - (done or 0))}
    except Exception as e:
        return {"error": str(e)[:160]}


cfg = get_35b_config()
services = {"chat": active("openclaw-chat.service"), "doc": active("openclaw-doc.service"), "legacy_gateway": active("openclaw-gateway.service")}
agents = {"chat": agent(18790), "doc": agent(18791)}
events = journal_events()
deep = {"checked": False}
if args.deep:
    ok, msg = test_connectivity(cfg["base_url"], cfg["api_key"], cfg["model"], timeout=30)
    tool_ok, tool_msg = (False, "skipped") if not ok else test_tool_call(cfg["base_url"], cfg["api_key"], cfg["model"], timeout=30)
    deep = {"checked": True, "connectivity": {"ok": ok, "message": msg}, "tool_call": {"ok": tool_ok, "message": tool_msg}}
core = services["chat"] and services["doc"] and agents["chat"]["http_ok"] and agents["doc"]["http_ok"]
warnings = []
if not services["legacy_gateway"]:
    warnings.append("legacy openclaw-gateway.service is failed/disabled; independent chat/doc services are active")
if events["abort_error"] or events["context_overflow"] or events["auth_error"]:
    warnings.append("new OpenClaw errors detected in reporting window")
if args.deep and not (deep["connectivity"]["ok"] and deep["tool_call"]["ok"]):
    warnings.append("external model deep probe failed")
print(json.dumps({
    "verdict": "healthy" if core and len(warnings) <= 1 else ("degraded" if core else "unhealthy"),
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "window_hours": hours,
    "services": services,
    "agents": agents,
    "configured_model": {"base_url": cfg["base_url"], "model": cfg["model"], "context_window": cfg["context_window"], "max_tokens": cfg["max_tokens"], "api_key_configured": bool(cfg["api_key"])},
    "events": events,
    "document_tasks": documents(),
    "deep_probe": deep,
    "warnings": warnings,
}, ensure_ascii=False, indent=2))
