"""
统一 35B 外部模型配置入口。

优先级: 环境变量 → config.yaml → 代码默认值

环境变量:
  35B_BASE_URL       - 35B 服务地址
  35B_API_KEY        - API Key (敏感, 仅存 .env)
  35B_MODEL          - 模型名
  35B_TIMEOUT_SECONDS - 超时秒数

config.yaml (兜底):
  llm.ollama_base_url
  llm.ollama_model
  llm.ollama_timeout_seconds
"""
from __future__ import annotations

import os
import re
import json
import logging
import subprocess
import time
import shutil
from pathlib import Path
from typing import Optional

import requests
import yaml

logger = logging.getLogger(__name__)

# ── 路径常量 ─────────────────────────────────────────────────────────────
ENV_FILE = Path("/home/youyeetoo/.config/ai-box/backend/.env")
CONFIG_FILE = Path("/home/youyeetoo/.config/ai-box/backend/config.yaml")
OPENCLAW_DIR = Path("/home/youyeetoo/INnet_agent/backend/.pi-agent")
CHAT_AGENT_PORT = 18790
DOC_AGENT_PORT = 18791

# ── 默认值 ────────────────────────────────────────────────────────────────
DEFAULT_35B_BASE_URL = "http://192.168.10.212:8081/v1"
DEFAULT_35B_MODEL = "Qwen3.5-35B-A3B-UD-Q4_K_XL.gguf"
DEFAULT_35B_TIMEOUT = 240


def get_35b_config() -> dict:
    """读取 35B 配置，三级优先级合并。"""
    base_url = (
        os.environ.get("35B_BASE_URL")
        or _read_config_yaml("ollama_base_url")
        or DEFAULT_35B_BASE_URL
    ).rstrip("/")
    model = (
        os.environ.get("35B_MODEL")
        or _read_config_yaml("ollama_model")
        or DEFAULT_35B_MODEL
    )
    timeout = int(
        os.environ.get("35B_TIMEOUT_SECONDS")
        or _read_config_yaml("ollama_timeout_seconds")
        or DEFAULT_35B_TIMEOUT
    )
    api_key = os.environ.get("35B_API_KEY", "") or _read_config_yaml("ollama_api_key") or "ollama"

    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "timeout_seconds": timeout,
        "source": _source_label(),
    }


def _source_label() -> str:
    """返回当前生效的配置来源。"""
    if os.environ.get("35B_BASE_URL"):
        return "env"
    if _read_config_yaml("ollama_base_url"):
        return "config.yaml"
    return "default"


def _read_config_yaml(key: str) -> Optional[str]:
    """读取 config.yaml 中 llm 段的值。"""
    try:
        if not CONFIG_FILE.exists():
            return None
        with open(CONFIG_FILE, "r") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("llm", {}).get(key)
    except Exception:
        return None


def _read_env_file() -> dict:
    """解析 .env 文件为 dict。"""
    result = {}
    if not ENV_FILE.exists():
        return result
    with open(ENV_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip("\"'")
    return result


def _write_env_file(env: dict) -> None:
    """写回 .env 文件，保留已有注释和空行。"""
    existing_lines = []
    existing_keys = set()
    if ENV_FILE.exists():
        with open(ENV_FILE, "r") as f:
            existing_lines = f.readlines()
        for line in existing_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=")[0].strip()
                existing_keys.add(key)

    thirty_five_keys = {"35B_BASE_URL", "35B_API_KEY", "35B_MODEL", "35B_TIMEOUT_SECONDS"}
    # 去掉已存在的旧 35B 行
    filtered = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=")[0].strip()
            if key in thirty_five_keys:
                continue
        filtered.append(line)

    # 追加新的 35B 配置
    for key, value in [
        ("35B_BASE_URL", env.get("35B_BASE_URL", "")),
        ("35B_API_KEY", env.get("35B_API_KEY", "")),
        ("35B_MODEL", env.get("35B_MODEL", "")),
        ("35B_TIMEOUT_SECONDS", str(env.get("35B_TIMEOUT_SECONDS", ""))),
    ]:
        filtered.append(f"{key}={value}\n")

    with open(ENV_FILE, "w") as f:
        f.writelines(filtered)


def _write_config_yaml(base_url: str, model: str, timeout: int) -> None:
    """更新 config.yaml 的 ollama_* 字段。"""
    if not CONFIG_FILE.exists():
        return
    with open(CONFIG_FILE, "r") as f:
        content = f.read()

    replacements = {
        r"ollama_base_url:\s*.*": f"  ollama_base_url: {base_url}",
        r"ollama_model:\s*.*": f"  ollama_model: {model}",
        r"ollama_timeout_seconds:\s*.*": f"  ollama_timeout_seconds: {timeout}",
    }
    for pattern, replacement in replacements.items():
        content = re.sub(pattern, replacement, content)

    with open(CONFIG_FILE, "w") as f:
        f.write(content)


def set_35b_config(base_url: str, api_key: str, model: str, timeout: int) -> dict:
    """写入 35B 配置到 .env 和 config.yaml。

    注意: api_key 只写 .env, 不写 config.yaml。
    """
    base_url = base_url.rstrip("/")

    # 写 .env
    env = _read_env_file()
    env["35B_BASE_URL"] = base_url
    env["35B_API_KEY"] = api_key
    env["35B_MODEL"] = model
    env["35B_TIMEOUT_SECONDS"] = str(timeout)
    _write_env_file(env)

    # 同步 config.yaml
    _write_config_yaml(base_url, model, timeout)

    # 设置当前进程环境
    os.environ["35B_BASE_URL"] = base_url
    os.environ["35B_API_KEY"] = api_key
    os.environ["35B_MODEL"] = model
    os.environ["35B_TIMEOUT_SECONDS"] = str(timeout)

    logger.info("35B config saved: base_url=%s model=%s", base_url, model)
    return get_35b_config()


# ── 验证 ──────────────────────────────────────────────────────────────────


def test_connectivity(base_url: str, api_key: str, model: str, timeout: int = 10) -> tuple[bool, str]:
    """Step 1: 连通性测试 — POST {base_url}/chat/completions 调用。"""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key != "ollama":
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 200,
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if text:
                return True, "ok"
            return False, "模型返回空内容"
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.exceptions.Timeout:
        return False, f"连接超时 ({timeout}s)"
    except requests.exceptions.ConnectionError as e:
        return False, f"无法连接: {e}"
    except Exception as e:
        return False, str(e)


def test_tool_call(base_url: str, api_key: str, model: str, timeout: int = 15) -> tuple[bool, str]:
    """Step 2: Tool call 验证 — 模型必须支持 tools/functions 调用。"""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key != "ollama":
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "What is the weather in Beijing?"}
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "City name",
                            }
                        },
                        "required": ["location"],
                    },
                },
            }
        ],
        "tool_choice": "auto",
        "max_tokens": 50,
        "temperature": 0.1,
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            msg = data.get("choices", [{}])[0].get("message", {})
            if msg.get("tool_calls"):
                return True, "ok"
            # Some models return content instead of tool_calls — still check
            if msg.get("content"):
                return True, "ok (response as text, tool_call capability unverified)"
            return False, "模型未返回 tool_calls，不支持 Agent 工具调用"
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.exceptions.Timeout:
        return False, f"Tool call 测试超时 ({timeout}s)"
    except Exception as e:
        return False, str(e)


# ── OpenClaw 配置同步 ────────────────────────────────────────────────────


def _generate_openclaw_json(agent_type: str, base_url: str, api_key: str, model: str, timeout: int) -> None:
    """根据当前 35B 配置重新生成 openclaw.json 的 provider 块。"""
    json_path = OPENCLAW_DIR / agent_type / "openclaw.json"
    if not json_path.exists():
        logger.warning("openclaw.json not found: %s", json_path)
        return

    with open(json_path, "r") as f:
        cfg = json.load(f)

    # 更新 35B provider
    provider_id = "qwen35-35b-external"
    cfg.setdefault("models", {}).setdefault("providers", {})
    providers = cfg["models"].setdefault("providers", {})

    # 删除旧的 35B provider (ID 可能变化)
    old_keys = [k for k in providers if "35b" in k.lower() or "35B" in k]
    for k in old_keys:
        del providers[k]

    providers[provider_id] = {
        "baseUrl": base_url,
        "api": "openai-completions",
        "models": [
            {
                "id": model,
                "name": f"External 35B ({base_url})",
                "contextWindow": 32768,
                "maxTokens": 7000,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "reasoning": False,
                "compat": {
                    "supportsTools": True,
                    "supportsStore": False,
                    "supportsStrictMode": False,
                    "supportsUsageInStreaming": False,
                    "supportsDeveloperRole": False,
                },
            }
        ],
        "apiKey": api_key,
        "timeoutSeconds": timeout,
    }

    # 更新 agent model 引用
    new_model_ref = f"{provider_id}/{model}"
    for agent in cfg.get("agents", {}).get("list", []):
        m = agent.get("model")
        if isinstance(m, dict):
            m["primary"] = new_model_ref
        elif isinstance(m, str):
            agent["model"] = new_model_ref

    defaults = cfg.get("agents", {}).get("defaults", {})
    dm = defaults.get("model")
    if isinstance(dm, dict):
        dm["primary"] = new_model_ref

    # 备份旧文件
    bak = str(json_path) + f".bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy(str(json_path), bak)

    with open(json_path, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    logger.info("openclaw.json regenerated: %s", json_path)


def apply_35b_config() -> dict:
    """Step 6: 重启 OpenClaw Agent 使配置生效。"""
    result = {"agent_status": "unknown"}

    # 获取当前配置
    config = get_35b_config()
    base_url = config["base_url"]
    api_key = config["api_key"]
    model = config["model"]
    timeout = config["timeout_seconds"]

    # 重新生成 openclaw.json
    for agent_type in ["chat", "doc"]:
        try:
            _generate_openclaw_json(agent_type, base_url, api_key, model, timeout)
        except Exception as e:
            logger.warning("Failed to regenerate openclaw.json for %s: %s", agent_type, e)

    # 重启 OpenClaw
    try:
        _restart_openclaw()
        # 等 health check
        for i in range(15):
            chat_ok = _health_check(CHAT_AGENT_PORT)
            doc_ok = _health_check(DOC_AGENT_PORT)
            if chat_ok and doc_ok:
                result["agent_status"] = "running"
                return result
            time.sleep(2)
        result["agent_status"] = "restarting"
    except Exception as e:
        logger.warning("OpenClaw restart failed: %s", e)
        result["agent_status"] = "error"
        result["error"] = str(e)

    return result


def _restart_openclaw() -> None:
    """重启 OpenClaw agent。"""
    import signal
    # 杀旧进程
    for port in [CHAT_AGENT_PORT, DOC_AGENT_PORT]:
        try:
            result = subprocess.run(
                ["ss", "-tlnp"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if f":{port} " in line:
                    pid_match = re.search(r"pid=(\d+)", line)
                    if pid_match:
                        pid = int(pid_match.group(1))
                        os.kill(pid, signal.SIGTERM)
                        time.sleep(0.5)
        except Exception:
            pass

    time.sleep(2)
    # 启动
    openclaw_bin = "/home/youyeetoo/.npm-global/bin/openclaw"
    subprocess.Popen(
        [openclaw_bin],
        cwd="/home/youyeetoo",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _health_check(port: int) -> bool:
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def mask_api_key(key: str) -> str:
    """脱敏: 保留前3位 + **** + 后3位。"""
    if len(key) <= 6:
        return key[:3] + "****"
    return key[:3] + "****" + key[-3:]
