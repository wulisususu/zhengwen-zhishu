from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import ApiSetting
from app.deps import get_current_user
from app.errors import ok
from app.config import get_config
import subprocess

router = APIRouter(prefix="/settings", tags=["settings"])

@router.get("/api")
def get_settings(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.query(ApiSetting).all()
    return ok(data=[{"key": r.key, "value": r.value, "description": r.description} for r in rows])

@router.put("/api")
def update_setting(body: dict, db: Session = Depends(get_db), _=Depends(get_current_user)):
    key = body.get("key", "")
    if not key:
        return ok(message="key required")
    row = db.query(ApiSetting).filter(ApiSetting.key == key).first()
    if row:
        row.value = body.get("value", row.value)
        row.description = body.get("description", row.description)
    else:
        row = ApiSetting(key=key, value=body.get("value", ""), description=body.get("description", ""))
        db.add(row)
    db.commit()
    return ok(message="saved")

@router.get("/external-model")
def get_external_model_config(_=Depends(get_current_user)):
    """获取 35B 外部模型配置 (api_key 脱敏)。"""
    from app.services.model_config import get_35b_config, mask_api_key
    cfg = get_35b_config()
    return ok(data={
        "base_url": cfg["base_url"],
        "api_key": mask_api_key(cfg["api_key"]),
        "model": cfg["model"],
        "timeout_seconds": cfg["timeout_seconds"],
        "source": cfg.get("source", "default"),
    })


@router.post("/external-model/test")
def test_external_model_config(body: dict, _=Depends(get_current_user)):
    """仅测试 35B 外部模型连通性 + Tool Call，不保存。"""
    from app.services.model_config import test_connectivity, test_tool_call
    from app.errors import AppError

    base_url = str(body.get("base_url", "")).strip()
    api_key = str(body.get("api_key", "")).strip()
    model = str(body.get("model", "")).strip()
    timeout = int(body.get("timeout_seconds", 240))

    if not base_url:
        raise AppError(400, "base_url 不能为空")
    if not model:
        raise AppError(400, "model 不能为空")

    conn_ok, conn_msg = test_connectivity(base_url, api_key, model, timeout=10)
    tool_ok, tool_msg = (False, "") if not conn_ok else test_tool_call(base_url, api_key, model, timeout=15)

    return ok(data={
        "connectivity": {"ok": conn_ok, "message": conn_msg},
        "tool_call": {"ok": tool_ok, "message": tool_msg},
        "all_passed": conn_ok and tool_ok,
    })


@router.put("/external-model")
def set_external_model_config(body: dict, _=Depends(get_current_user)):
    """保存 35B 外部模型配置并重启 Agent（需先通过测试）。"""
    from app.services.model_config import set_35b_config, apply_35b_config, mask_api_key
    from app.errors import AppError

    base_url = str(body.get("base_url", "")).strip()
    api_key = str(body.get("api_key", "")).strip()
    model = str(body.get("model", "")).strip()
    timeout = int(body.get("timeout_seconds", 240))

    if not base_url:
        raise AppError(400, "base_url 不能为空")
    if not model:
        raise AppError(400, "model 不能为空")

    cfg = set_35b_config(base_url, api_key, model, timeout)
    result = apply_35b_config()

    return ok(data={
        "base_url": cfg["base_url"],
        "api_key": mask_api_key(cfg["api_key"]),
        "model": cfg["model"],
        "timeout_seconds": cfg["timeout_seconds"],
        "applied": True,
        "agent_status": result.get("agent_status", "unknown"),
    }, message="配置已保存并应用")


@router.get("/feature-flags")
def get_feature_flags(_=Depends(get_current_user)):
    cfg = get_config()
    flags = (cfg.get("feature_flags") or {}) if isinstance(cfg, dict) else {}
    return ok(data={
        "show_ppt": bool(flags.get("show_ppt", False)),
        "show_table": bool(flags.get("show_table", False)),
        "show_agents": bool(flags.get("show_agents", False)),
    })



@router.get("/local-models")
def get_local_models(_=Depends(get_current_user)):
    """查询本地模型状态 (8002/8003/8004 端口连通性)。"""
    models = [
        {"port": 8002, "name": "Qwen3-0.6B", "model": "Qwen3-0.6B", "role": "聊天降级"},
        {"port": 8003, "name": "MiniCPM Vision", "model": "MiniCPM-V-2_6", "role": "文档解析/OCR"},
        {"port": 8004, "name": "Qwen2.5-3B RKLLM", "model": "Qwen2.5-3B", "role": "NPU 推理"},
    ]
    result = []
    for m in models:
        port = m["port"]
        try:
            r = subprocess.run(
                ["curl", "-sf", "-m", "3", f"http://127.0.0.1:{port}/health"],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0:
                m["status"] = "running"
            else:
                m["status"] = "stopped"
                m["last_error"] = (r.stderr or "no response").strip()[:200]
        except Exception as e:
            m["status"] = "stopped"
            m["last_error"] = str(e)[:200]
        result.append(m)

    return ok(data={"models": result})
