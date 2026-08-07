"""Cancelable async subprocess execution with POSIX process-group cleanup."""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes


class CommandExecutionError(RuntimeError):
    def __init__(self, returncode: int) -> None:
        super().__init__(f"command_failed:{returncode}")
        self.returncode = returncode


class CommandTimeoutError(TimeoutError):
    pass


async def _terminate_process_group(process: asyncio.subprocess.Process, grace: float) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=grace)
        return
    except asyncio.TimeoutError:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


async def run_command(
    args: Sequence[str],
    *,
    cwd: Path | str | None = None,
    timeout: float,
    check: bool = False,
    terminate_grace: float = 2.0,
) -> CommandResult:
    normalized = tuple(str(arg) for arg in args)
    process = await asyncio.create_subprocess_exec(
        *normalized,
        cwd=str(cwd) if cwd is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        await _terminate_process_group(process, terminate_grace)
        raise CommandTimeoutError("command_timeout") from exc
    except asyncio.CancelledError:
        await _terminate_process_group(process, terminate_grace)
        raise
    result = CommandResult(normalized, process.returncode or 0, stdout, stderr)
    if check and result.returncode != 0:
        raise CommandExecutionError(result.returncode)
    return result
