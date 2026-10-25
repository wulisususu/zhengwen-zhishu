from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import ApiSetting
from app.deps import require_admin
from app.errors import ok
from app.config import get_config
import subprocess

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/api")
def get_settings(db: Session = Depends(get_db), _=Depends(require_admin)):
    rows = db.query(ApiSetting).all()
    return ok(data=[{"key": r.key, "value": r.value, "description": r.description} for r in rows])


@router.put("/api")
def update_setting(body: dict, db: Session = Depends(get_db), _=Depends(require_admin)):
    key = body.get("key", "")
    if not key:
        return ok(message="key required")
    row = db.query(ApiSetting).filter(ApiSetting.key == key).first()
    if row:
        row.value = body.get("value", row.value)
        row.description = body.get("description", row.description)
    else:
        db.add(ApiSetting(key=key, value=body.get("value", ""), description=body.get("description", "")))
    db.commit()
    return ok(message="saved")


def _external_model_payload(cfg: dict, *, applied: bool = False, agent_status: str | None = None) -> dict:
    payload = {
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "timeout_seconds": cfg["timeout_seconds"],
        "context_window": cfg["context_window"],
        "max_tokens": cfg["max_tokens"],
        "source": cfg.get("source", "project .env"),
        "api_key": "",
        "api_key_configured": bool(cfg["api_key"]),
        "api_key_hint": cfg["api_key"][:3] + "****" + cfg["api_key"][-3:] if len(cfg["api_key"]) > 6 else ("已配置" if cfg["api_key"] else ""),
    }
    if applied:
        payload["applied"] = True
        payload["agent_status"] = agent_status or "unknown"
    return payload


def _parse_external_model(body: dict, *, resolve_key: bool) -> tuple[dict, str]:
    from app.services.model_config import (
        DEFAULT_CONTEXT_WINDOW, DEFAULT_MAX_TOKENS, DEFAULT_TIMEOUT,
        _as_int, _validate_base_url, resolve_api_key,
    )
    base_url = _validate_base_url(str(body.get("base_url", "")))
    model = str(body.get("model", "")).strip()
    if not model:
        raise ValueError("模型名称不能为空")
    timeout = _as_int(body.get("timeout_seconds"), DEFAULT_TIMEOUT, 30, 600)
    context_window = _as_int(body.get("context_window"), DEFAULT_CONTEXT_WINDOW, 4096, 1048576)
    max_tokens = _as_int(body.get("max_tokens"), DEFAULT_MAX_TOKENS, 256, context_window)
    api_key_mode = str(body.get("api_key_mode", "keep"))
    if api_key_mode not in {"keep", "replace", "clear"}:
        raise ValueError("api_key_mode 无效")
    api_key = str(body.get("api_key", "")).strip()
    if resolve_key:
        api_key = resolve_api_key(api_key, api_key_mode)
    return {
        "base_url": base_url, "api_key": api_key, "model": model,
        "timeout_seconds": timeout, "context_window": context_window, "max_tokens": max_tokens,
    }, api_key_mode


@router.get("/external-model")
def get_external_model_config(_=Depends(require_admin)):
    from app.services.model_config import get_35b_config
    return ok(data=_external_model_payload(get_35b_config()))


@router.post("/external-model/test")
def test_external_model_config(body: dict, _=Depends(require_admin)):
    from app.errors import AppError
    from app.services.model_config import test_connectivity, test_tool_call
    try:
        cfg, _ = _parse_external_model(body, resolve_key=True)
    except ValueError as exc:
        raise AppError(400, str(exc))

    conn_ok, conn_msg = test_connectivity(
        cfg["base_url"], cfg["api_key"], cfg["model"], timeout=min(cfg["timeout_seconds"], 60)
    )
    tool_ok, tool_msg = (False, "连通性未通过") if not conn_ok else test_tool_call(
        cfg["base_url"], cfg["api_key"], cfg["model"], timeout=min(cfg["timeout_seconds"], 60)
    )
    return ok(data={
        "connectivity": {"ok": conn_ok, "message": conn_msg},
        "tool_call": {"ok": tool_ok, "message": tool_msg},
        "all_passed": conn_ok and tool_ok,
    })


@router.put("/external-model")
def set_external_model_config(body: dict, _=Depends(require_admin)):
    from app.errors import AppError
    from app.services.model_config import (
        apply_35b_config, get_35b_config, set_35b_config, test_connectivity, test_tool_call,
    )
    try:
        candidate, api_key_mode = _parse_external_model(body, resolve_key=True)
    except ValueError as exc:
        raise AppError(400, str(exc))

    conn_ok, conn_msg = test_connectivity(
        candidate["base_url"], candidate["api_key"], candidate["model"], timeout=min(candidate["timeout_seconds"], 60)
    )
    tool_ok, tool_msg = (False, "连通性未通过") if not conn_ok else test_tool_call(
        candidate["base_url"], candidate["api_key"], candidate["model"], timeout=min(candidate["timeout_seconds"], 60)
    )
    if not (conn_ok and tool_ok):
        raise AppError(400, f"配置未保存：连通性={conn_msg}；Tool Call={tool_msg}")

    try:
        cfg = set_35b_config(
            candidate["base_url"], str(body.get("api_key", "")), candidate["model"],
            candidate["timeout_seconds"], candidate["context_window"], candidate["max_tokens"], api_key_mode,
        )
        result = apply_35b_config()
    except Exception as exc:
        raise AppError(500, f"配置写入或 Agent 重启失败：{exc}")

    if result.get("agent_status") != "running":
        raise AppError(500, "配置已写入，但 Chat/Doc Agent 未在时限内恢复健康")
    return ok(data=_external_model_payload(cfg, applied=True, agent_status="running"), message="配置已保存并验证")


@router.get("/feature-flags")
def get_feature_flags(_=Depends(require_admin)):
    cfg = get_config()
    flags = (cfg.get("feature_flags") or {}) if isinstance(cfg, dict) else {}
    return ok(data={
        "show_ppt": bool(flags.get("show_ppt", False)),
        "show_table": bool(flags.get("show_table", False)),
        "show_agents": bool(flags.get("show_agents", False)),
    })


@router.get("/local-models")
def get_local_models(_=Depends(require_admin)):
    models = [
        {"port": 8002, "name": "Qwen3-0.6B", "model": "Qwen3-0.6B", "role": "聊天/文档降级"},
        {"port": 8003, "name": "MiniCPM Vision", "model": "MiniCPM-V-2_6", "role": "文档解析/OCR"},
        {"port": 8004, "name": "Qwen2.5-3B RKLLM", "model": "Qwen2.5-3B", "role": "NPU 推理"},
    ]
    for item in models:
        try:
            result = subprocess.run(
                ["curl", "-sf", "-m", "3", f"http://127.0.0.1:{item['port']}/health"],
                capture_output=True, text=True, timeout=5,
            )
            item["status"] = "running" if result.returncode == 0 else "stopped"
            if result.returncode:
                item["last_error"] = (result.stderr or "no response").strip()[:200]
        except Exception as exc:
            item["status"] = "stopped"
            item["last_error"] = str(exc)[:200]
    return ok(data={"models": models})
