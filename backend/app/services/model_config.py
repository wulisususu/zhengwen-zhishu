"""External OpenAI-compatible model configuration and OpenClaw synchronization."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
import yaml

logger = logging.getLogger(__name__)

PROJECT_BACKEND = Path("/home/youyeetoo/InNet_box/backend")
ENV_FILE = PROJECT_BACKEND / ".env"
CONFIG_FILE = Path("/home/youyeetoo/.config/ai-box/backend/config.yaml")
OPENCLAW_DIR = PROJECT_BACKEND / ".pi-agent"
RESTART_SCRIPT = Path("/home/youyeetoo/InNet_box/restart_backend.sh")
CHAT_AGENT_PORT = 18790
DOC_AGENT_PORT = 18791

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 600
DEFAULT_CONTEXT_WINDOW = 262144
DEFAULT_MAX_TOKENS = 32768
LOCAL_PROVIDER = "qwen06b-local-8002"
LOCAL_MODEL = "Qwen3-0.6B-Q4_K_M.gguf"
LOCAL_MODEL_REF = f"{LOCAL_PROVIDER}/{LOCAL_MODEL}"


def _read_env_file() -> dict[str, str]:
    result: dict[str, str] = {}
    if not ENV_FILE.exists():
        return result
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip("\"'")
    return result


def _write_env_values(values: dict[str, str]) -> None:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True) if ENV_FILE.exists() else []
    pending = dict(values)
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in pending:
                output.append(f"{key}={pending.pop(key)}\n")
                continue
        output.append(line if line.endswith("\n") else line + "\n")
    for key, value in pending.items():
        output.append(f"{key}={value}\n")
    ENV_FILE.write_text("".join(output), encoding="utf-8")


def _configured_value(*keys: str, default: str = "") -> str:
    env_file = _read_env_file()
    for key in keys:
        value = os.environ.get(key) or env_file.get(key)
        if value:
            return str(value)
    return default


def _as_int(value: str | int | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def get_35b_config() -> dict:
    """Read the active external OpenAI-compatible model configuration."""
    base_url = _configured_value(
        "EXTERNAL_MODEL_BASE_URL", "35B_BASE_URL",
        default=_read_config_yaml("ollama_base_url") or DEFAULT_BASE_URL,
    ).rstrip("/")
    model = _configured_value(
        "EXTERNAL_MODEL_NAME", "35B_MODEL",
        default=_read_config_yaml("ollama_model") or DEFAULT_MODEL,
    )
    api_key = _configured_value("EXTERNAL_MODEL_API_KEY", "DEEPSEEK_API_KEY", "35B_API_KEY")
    timeout = _as_int(
        _configured_value("EXTERNAL_MODEL_TIMEOUT_SECONDS", "35B_TIMEOUT_SECONDS"),
        DEFAULT_TIMEOUT, 30, 600,
    )
    context_window = _as_int(
        _configured_value("EXTERNAL_MODEL_CONTEXT_WINDOW"),
        DEFAULT_CONTEXT_WINDOW, 4096, 1048576,
    )
    max_tokens = _as_int(
        _configured_value("EXTERNAL_MODEL_MAX_TOKENS"),
        DEFAULT_MAX_TOKENS, 256, context_window,
    )
    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "timeout_seconds": timeout,
        "context_window": context_window,
        "max_tokens": max_tokens,
        "source": "project .env",
    }


def _read_config_yaml(key: str) -> Optional[str]:
    try:
        if not CONFIG_FILE.exists():
            return None
        cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
        return cfg.get("llm", {}).get(key)
    except Exception:
        return None


def _validate_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("服务地址必须是 http(s) URL，例如 http://192.168.1.10:8000/v1")
    if parsed.username or parsed.password:
        raise ValueError("服务地址不能包含用户名或密码")
    # 模型出口策略：intranet / offline 模式下不允许把模型地址配到公网
    from app.services.model_policy import ModelPolicyError, guard_model_url

    try:
        guard_model_url(value, purpose="external_model_config")
    except ModelPolicyError as exc:
        raise ValueError(str(exc)) from exc
    return value


def mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 6:
        return "已配置"
    return key[:3] + "****" + key[-3:]


def resolve_api_key(api_key: str, mode: str = "keep") -> str:
    if mode == "clear":
        return ""
    if api_key:
        return api_key
    return get_35b_config()["api_key"]


def set_35b_config(
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    api_key_mode: str = "keep",
) -> dict:
    base_url = _validate_base_url(base_url)
    model = model.strip()
    if not model:
        raise ValueError("模型名称不能为空")
    timeout = _as_int(timeout, DEFAULT_TIMEOUT, 30, 600)
    context_window = _as_int(context_window, DEFAULT_CONTEXT_WINDOW, 4096, 1048576)
    max_tokens = _as_int(max_tokens, DEFAULT_MAX_TOKENS, 256, context_window)
    resolved_key = resolve_api_key(api_key.strip(), api_key_mode)

    _write_env_values({
        "EXTERNAL_MODEL_BASE_URL": base_url,
        "EXTERNAL_MODEL_API_KEY": resolved_key,
        "EXTERNAL_MODEL_NAME": model,
        "EXTERNAL_MODEL_TIMEOUT_SECONDS": str(timeout),
        "EXTERNAL_MODEL_CONTEXT_WINDOW": str(context_window),
        "EXTERNAL_MODEL_MAX_TOKENS": str(max_tokens),
    })
    for key, value in {
        "EXTERNAL_MODEL_BASE_URL": base_url,
        "EXTERNAL_MODEL_API_KEY": resolved_key,
        "EXTERNAL_MODEL_NAME": model,
        "EXTERNAL_MODEL_TIMEOUT_SECONDS": str(timeout),
        "EXTERNAL_MODEL_CONTEXT_WINDOW": str(context_window),
        "EXTERNAL_MODEL_MAX_TOKENS": str(max_tokens),
    }.items():
        os.environ[key] = value
    logger.info("external model config saved: base_url=%s model=%s", base_url, model)
    return get_35b_config()


def _headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def test_connectivity(base_url: str, api_key: str, model: str, timeout: int = 15) -> tuple[bool, str]:
    try:
        base_url = _validate_base_url(base_url)
        response = requests.post(
            base_url + "/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": "Reply with OK."}], "max_tokens": 32},
            headers=_headers(api_key),
            timeout=_as_int(timeout, 15, 5, 60),
        )
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}: {response.text[:200]}"
        data = response.json()
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            return True, "ok"
        return False, "模型响应缺少 choices 字段"
    except requests.exceptions.Timeout:
        return False, "连接超时"
    except Exception as exc:
        return False, str(exc)


def test_tool_call(base_url: str, api_key: str, model: str, timeout: int = 20) -> tuple[bool, str]:
    tool = {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        },
    }
    try:
        base_url = _validate_base_url(base_url)
        response = requests.post(
            base_url + "/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Call get_weather for Beijing. Do not answer in prose."}],
                "tools": [tool],
                "tool_choice": "auto",
                "max_tokens": 96,
                "temperature": 0,
            },
            headers=_headers(api_key),
            timeout=_as_int(timeout, 20, 5, 60),
        )
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}: {response.text[:200]}"
        message = response.json().get("choices", [{}])[0].get("message", {})
        return (True, "ok") if message.get("tool_calls") else (
            False, "模型未返回 OpenAI 标准 tool_calls，不能用于 OpenClaw Agent",
        )
    except requests.exceptions.Timeout:
        return False, "Tool Call 测试超时"
    except Exception as exc:
        return False, str(exc)


def _backup_config(json_path: Path) -> None:
    backup = json_path.with_name(json_path.name + f".bak-before-settings-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(json_path, backup)


def _sync_models_registry(agent_type: str, provider: dict) -> None:
    """Keep OpenClaw's runtime model registry aligned with openclaw.json.

    OpenClaw gives ``models.json`` precedence over the provider embedded in
    ``openclaw.json``. Updating only the latter leaves a running agent pointed
    at a previously configured endpoint.
    """
    registry_path = OPENCLAW_DIR / agent_type / "models.json"
    if not registry_path.exists():
        return
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    _backup_config(registry_path)
    registry.setdefault("providers", {})["qwen35-35b-external"] = provider
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _generate_openclaw_json(agent_type: str, config: dict) -> None:
    json_path = OPENCLAW_DIR / agent_type / "openclaw.json"
    if not json_path.exists():
        raise FileNotFoundError(f"openclaw.json not found: {json_path}")
    cfg = json.loads(json_path.read_text(encoding="utf-8"))
    _backup_config(json_path)

    provider_id = "qwen35-35b-external"
    # Documents are streamed and post-processed; keep their completion budget
    # bounded so one request cannot consume the entire agent run window.
    model_max_tokens = min(config["max_tokens"], 8192) if agent_type == "doc" else config["max_tokens"]
    provider = {
        "baseUrl": config["base_url"],
        "api": "openai-completions",
        "models": [{
            "id": config["model"],
            "name": f"External OpenAI-compatible ({config['base_url']})",
            "contextWindow": config["context_window"],
            "maxTokens": model_max_tokens,
            "input": ["text"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            # The external Qwen server emits only reasoning_content unless
            # its chat template is told to disable thinking.  Mark the
            # compatible payload shape so OpenClaw sends that flag whenever
            # the session thinking level is off.
            "reasoning": True,
            "compat": {
                "thinkingFormat": "qwen-chat-template",
                "supportsTools": True,
                "supportsStore": False,
                "supportsStrictMode": False,
                "supportsUsageInStreaming": False,
                "supportsDeveloperRole": False,
            },
        }],
        "timeoutSeconds": config["timeout_seconds"],
    }
    if config["api_key"]:
        provider["apiKey"] = "$" + "{EXTERNAL_MODEL_API_KEY}"

    # The standalone registry is consulted before openclaw.json at runtime.
    # Keep it on the environment reference too, rather than persisting a Token.
    _sync_models_registry(agent_type, provider)

    providers = cfg.setdefault("models", {}).setdefault("providers", {})
    providers[provider_id] = provider
    external_ref = f"{provider_id}/{config['model']}"

    defaults = cfg.setdefault("agents", {}).setdefault("defaults", {})
    is_doc_agent = agent_type == "doc"
    # Chat may degrade to the local lightweight model. Documents must not: a
    # failed external writer is handed to the dedicated 3B docs_pipeline.
    agent_model = {"primary": external_ref, "fallbacks": [] if is_doc_agent else [LOCAL_MODEL_REF]}
    defaults["model"] = agent_model
    if is_doc_agent:
        # Provider timeout is capped independently; this bounds the complete
        # OpenClaw document run, including finalization, at fifteen minutes.
        defaults["timeoutSeconds"] = 900
    for agent in cfg["agents"].get("list", []):
        agent_id = agent.get("id")
        if agent_id == "chat-fallback":
            agent["model"] = LOCAL_MODEL_REF
        elif agent_id in {"chat", "doc"}:
            agent["model"] = dict(agent_model)

    cfg.setdefault("gateway", {}).setdefault("auth", {})["mode"] = "token"
    cfg["gateway"]["auth"]["token"] = {"source": "env", "provider": "default", "id": "OPENCLAW_GATEWAY_TOKEN"}
    json_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _health_check(port: int) -> bool:
    try:
        return requests.get(f"http://127.0.0.1:{port}/health", timeout=3).status_code == 200
    except requests.RequestException:
        return False


def _restart_openclaw() -> None:
    env = os.environ.copy()
    uid = str(os.geteuid())
    # The backend is launched through nohup and has no desktop-session DBus
    # variables. Override inherited values so systemctl --user always targets
    # the service manager belonging to this backend process's Unix user.
    env["XDG_RUNTIME_DIR"] = "/run/user/" + uid
    env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/" + uid + "/bus"
    completed = subprocess.run(
        [str(RESTART_SCRIPT), "--agent"],
        cwd=str(RESTART_SCRIPT.parent),
        capture_output=True,
        text=True,
        timeout=90,
        env=env,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "restart failed")[-1000:])


def apply_35b_config() -> dict:
    config = get_35b_config()
    for agent_type in ("chat", "doc"):
        _generate_openclaw_json(agent_type, config)
    _restart_openclaw()
    deadline = time.time() + 30
    while time.time() < deadline:
        if _health_check(CHAT_AGENT_PORT) and _health_check(DOC_AGENT_PORT):
            return {"agent_status": "running"}
        time.sleep(2)
    return {"agent_status": "restarting"}
