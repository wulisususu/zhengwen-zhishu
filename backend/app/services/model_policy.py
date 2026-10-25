"""模型接入策略（Model Egress Policy）。

三种模式，必须由配置显式指定，代码不会因为超时/异常/健康检查失败而自动改变模式：

- ``cloud_allowed``
    允许调用显式配置的云端模型。请求内容会离开本机 / 当前网络边界，
    调用方必须在日志与接口响应中向操作者明示这一点。
- ``intranet``
    只允许 loopback 与私有网段地址（内网模型服务）。命中公网地址直接拒绝。
- ``offline``
    只允许 loopback（本机进程）。任何指向非本机的地址都拒绝，
    无法完成任务时抛出 ``ModelPolicyError``，**不会**静默降级到云端。

配置位置：``config.yaml`` 的 ``model.mode``；可用环境变量 ``AI_BOX_MODEL_MODE`` 覆盖。
未配置时按 ``intranet`` 处理（fail-closed），并在日志中给出一次性告警。

边界说明（重要）：
    本模块只做**应用层**出口限制——它约束本进程主动发起的模型请求。
    它不能证明设备没有其他外网流量：OpenClaw 子进程、系统服务、其他进程
    仍可能直接出网。真正的断网需要在操作系统层（iptables / nftables /
    路由 / 防火墙）落实，见 ``describe()["os_level_enforced"]``。
"""
from __future__ import annotations

import ipaddress
import logging
import os
import time
from urllib.parse import urlparse

logger = logging.getLogger("app.model_policy")

MODES = ("cloud_allowed", "intranet", "offline")

#: 配置缺失时的兜底模式：fail-closed，宁可不出网
DEFAULT_MODE = "intranet"

_ENV_MODE = "AI_BOX_MODEL_MODE"

_MODE_LABELS = {
    "cloud_allowed": "允许云端（内容会离开本机）",
    "intranet": "仅内网模型",
    "offline": "纯离线（仅本机 loopback）",
}

_default_warned = False


class ModelPolicyError(RuntimeError):
    """模型出口策略拒绝。调用方应把它转换成明确的业务错误，而不是 500 堆栈。"""

    code = "MODEL_POLICY_VIOLATION"

    def __init__(self, message: str, *, mode: str = "", purpose: str = "", url: str = ""):
        self.mode = mode
        self.purpose = purpose
        self.url = url
        super().__init__(message)


def _read_config_mode() -> tuple[str, str]:
    """返回 (mode, source)。source 用于日志说明模式来自哪里。"""
    env_value = str(os.getenv(_ENV_MODE) or "").strip().lower()
    if env_value:
        return env_value, f"env:{_ENV_MODE}"
    try:
        from app.config import get_config

        cfg = get_config() or {}
        model_cfg = cfg.get("model") or {}
        value = str(model_cfg.get("mode") or "").strip().lower()
        if value:
            return value, "config.yaml:model.mode"
    except FileNotFoundError:
        return DEFAULT_MODE, "default(config.yaml 缺失)"
    except Exception as exc:  # 配置损坏时也不能静默放行
        logger.error("读取 model.mode 失败，按 %s 处理：%s", DEFAULT_MODE, exc)
        return DEFAULT_MODE, "default(读取失败)"
    return DEFAULT_MODE, "default(未配置)"


def get_mode() -> str:
    """当前模型出口模式。非法值直接抛错，不做猜测。"""
    global _default_warned
    mode, source = _read_config_mode()
    if mode not in MODES:
        raise ModelPolicyError(
            f"模型模式配置无效：{mode!r}（来源 {source}），可选值 {', '.join(MODES)}",
            mode=mode,
        )
    if source.startswith("default") and not _default_warned:
        _default_warned = True
        logger.warning(
            "未显式配置 model.mode，已按 %s 处理（不会调用云端模型）。"
            "如需云端请在 config.yaml 设置 model.mode: cloud_allowed，"
            "如需纯离线请设置 model.mode: offline。",
            mode,
        )
    return mode


def get_mode_source() -> str:
    _, source = _read_config_mode()
    return source


def classify_host(host: str) -> str:
    """把主机名分成 loopback / intranet / cloud / invalid。

    无法解析或不确定的一律归为 cloud（保守判定），这样 intranet 模式不会误放行。
    """
    name = (host or "").strip().strip("[]").lower()
    if not name:
        return "invalid"
    if name in {"localhost", "localhost.localdomain", "ip6-localhost"}:
        return "loopback"
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        if name.endswith((".local", ".lan", ".internal", ".localdomain", ".home")):
            return "intranet"
        return "cloud"
    if ip.is_loopback:
        return "loopback"
    if ip.is_unspecified:
        return "loopback"
    if ip.is_private or ip.is_link_local:
        return "intranet"
    return "cloud"


def classify_url(url: str) -> str:
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return "invalid"
    if parsed.scheme not in {"http", "https"}:
        return "invalid"
    return classify_host(parsed.hostname or "")


def is_allowed(url: str, mode: str | None = None) -> bool:
    kind = classify_url(url)
    if kind == "invalid":
        return False
    current = mode or get_mode()
    if current == "cloud_allowed":
        return True
    if current == "intranet":
        return kind in {"loopback", "intranet"}
    if current == "offline":
        return kind == "loopback"
    return False


def guard_model_url(url: str, *, purpose: str = "model_call", mode: str | None = None) -> str:
    """校验模型地址是否在当前模式下允许；不允许则抛 ModelPolicyError。

    返回原 url，便于 `url = guard_model_url(url, ...)` 直接串联。
    """
    current = mode or get_mode()
    kind = classify_url(url)
    if kind == "invalid":
        raise ModelPolicyError(
            f"模型地址无效（{purpose}）：{url!r}",
            mode=current, purpose=purpose, url=url,
        )
    if is_allowed(url, current):
        return url
    host = urlparse(url).hostname or ""
    raise ModelPolicyError(
        f"模型地址 {host} 属于 {kind}，当前模式 {current}（{_MODE_LABELS.get(current, current)}）不允许调用",
        mode=current, purpose=purpose, url=url,
    )


def agent_providers_compliant(config_path, *, mode: str | None = None) -> tuple[bool, str]:
    """检查 OpenClaw Agent 的 openclaw.json 里各 provider 的 baseUrl 是否合规。

    Agent 是独立子进程，它的出网不经过本模块的 requests 出口，
    因此 offline/intranet 模式必须额外检查它的静态配置，否则「本进程没出网」
    不代表设备没出网。

    返回 (是否合规, 原因)。
    """
    import json
    from pathlib import Path

    current = mode or get_mode()
    if current == "cloud_allowed":
        return True, ""
    try:
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"无法读取 Agent 配置 {config_path}: {exc}"

    providers = ((data.get("models") or {}).get("providers") or {})
    for name, provider in providers.items():
        if not isinstance(provider, dict):
            continue
        base_url = str(provider.get("baseUrl") or "").strip()
        if not base_url:
            continue
        kind = classify_url(base_url)
        allowed = kind == "loopback" if current == "offline" else kind in {"loopback", "intranet"}
        if not allowed:
            host = urlparse(base_url).hostname or base_url
            return False, f"provider {name} 指向 {host}（{kind}），模式 {current} 不允许"
    return True, ""


def describe() -> dict:
    """供 /api/v1/system 与运维脚本展示当前策略边界。"""
    mode = get_mode()
    return {
        "mode": mode,
        "mode_label": _MODE_LABELS.get(mode, mode),
        "mode_source": get_mode_source(),
        "allows_cloud": mode == "cloud_allowed",
        "allows_intranet": mode in {"cloud_allowed", "intranet"},
        "allows_loopback": True,
        "cloud_content_leaves_device": mode == "cloud_allowed",
        "os_level_enforced": False,
        "note": (
            "应用层限制只约束本进程发起的模型请求；OpenClaw 子进程与系统其他进程的出网"
            "需在操作系统层（iptables/nftables/防火墙）另行限制，"
            "仅设置配置开关不能证明设备没有外网流量。"
        ),
    }


def log_model_call(
    *,
    purpose: str,
    model: str = "",
    url: str = "",
    elapsed_ms: int | None = None,
    error_type: str = "",
    mode: str | None = None,
) -> None:
    """记录一次模型调用。只记名称/模式/主机/耗时/错误类型，不记 Key 与请求正文。"""
    host = ""
    try:
        host = urlparse(str(url or "")).netloc or ""
    except Exception:
        host = ""
    logger.info(
        "model_call purpose=%s mode=%s host=%s model=%s elapsed_ms=%s error=%s",
        purpose,
        mode or _safe_mode(),
        host,
        model or "-",
        elapsed_ms if elapsed_ms is not None else "-",
        error_type or "-",
    )


def _safe_mode() -> str:
    try:
        return get_mode()
    except ModelPolicyError:
        return "invalid"


class timed:  # noqa: N801 - 轻量上下文管理器，避免各处重复写 time.perf_counter
    """with timed() as t: ... → t.ms"""

    def __enter__(self):
        self._start = time.perf_counter()
        self.ms = 0
        return self

    def __exit__(self, exc_type, exc, tb):
        self.ms = int((time.perf_counter() - self._start) * 1000)
        return False
