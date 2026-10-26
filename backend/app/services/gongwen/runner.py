"""Run gongwen-kit / bridge Node processes safely.

Argument lists only (never shell=True); own process group so a timeout kills
the whole tree (gongwen check spawns one node per check script); a minimal
environment; a process-wide cap on concurrent Node processes. Blocking: call
from a thread pool, never on the event loop.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.services.gongwen import catalog
from app.services.gongwen.settings import GongwenSettings


class GongwenToolError(Exception):
    """Explicit tool failure with a stable code (catalog.TOOL_*)."""

    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail   # truncated stderr; returned to the caller, never logged

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "detail": self.detail}


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    seconds: float


_semaphores: dict[int, threading.BoundedSemaphore] = {}
_sem_lock = threading.Lock()


def _semaphore(limit: int) -> threading.BoundedSemaphore:
    with _sem_lock:
        return _semaphores.setdefault(limit, threading.BoundedSemaphore(limit))


def _env() -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "LANG": "C.UTF-8", "NODE_OPTIONS": ""}
    for key, value in os.environ.items():   # documented font overrides only (docs/字体.md)
        if key.startswith("GONGWEN_FONT_"):
            env[key] = value
    return env


def resolve_node(settings: GongwenSettings) -> str:
    node = shutil.which(settings.node_bin)
    if not node:
        raise GongwenToolError(catalog.TOOL_NODE_NOT_FOUND, f"找不到 Node.js（{settings.node_bin}），需要 Node >= 18")
    return node


def require_kit(settings: GongwenSettings) -> Path:
    kit = settings.kit_path
    if not (kit / "bin" / "gongwen.js").is_file() or not (kit / "node_modules").is_dir():
        raise GongwenToolError(catalog.TOOL_KIT_NOT_FOUND,
                               "gongwen-kit 未安装或缺依赖（见 backend/third_party/README.md）")
    return kit


def run_node(settings: GongwenSettings, args: list[str], *, timeout: float, cwd: Path,
             stdin: bytes | None = None) -> RunResult:
    node = resolve_node(settings)
    sem = _semaphore(settings.max_concurrent)
    if not sem.acquire(timeout=timeout):
        raise GongwenToolError(catalog.TOOL_BUSY, "格式工具繁忙，请稍后重试")
    try:
        start = time.monotonic()
        proc = subprocess.Popen(
            [node, *args], stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(cwd), env=_env(),
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(input=stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
            raise GongwenToolError(catalog.TOOL_TIMEOUT, f"格式工具超过 {timeout:g} 秒未完成，已终止")
        return RunResult(proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"),
                         time.monotonic() - start)
    finally:
        sem.release()
