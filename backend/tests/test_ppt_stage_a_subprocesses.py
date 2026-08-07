import asyncio
import os
import sys
import time
from pathlib import Path

import pytest


def test_run_command_returns_captured_output():
    from app.PPT_master.subprocesses import run_command

    result = asyncio.run(
        run_command([sys.executable, "-c", "print('stage-a-ok')"], timeout=5, check=True)
    )
    assert result.returncode == 0
    assert result.stdout.decode().strip() == "stage-a-ok"


def test_run_command_raises_for_nonzero_when_check_enabled():
    from app.PPT_master.subprocesses import CommandExecutionError, run_command

    with pytest.raises(CommandExecutionError) as exc_info:
        asyncio.run(run_command([sys.executable, "-c", "raise SystemExit(7)"], timeout=5, check=True))
    assert exc_info.value.returncode == 7


def test_run_command_timeout_kills_process_group(tmp_path: Path):
    from app.PPT_master.subprocesses import CommandTimeoutError, run_command

    child_pid_file = tmp_path / "child.pid"
    script = (
        "import pathlib,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(child.pid)); "
        "time.sleep(60)"
    )
    with pytest.raises(CommandTimeoutError):
        asyncio.run(
            run_command(
                [sys.executable, "-c", script],
                timeout=0.4,
                check=True,
                terminate_grace=0.2,
            )
        )

    child_pid = int(child_pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("child process survived process-group timeout cleanup")
