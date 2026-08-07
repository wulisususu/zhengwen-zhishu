"""LLM service manager: communicates with RKLLM subprocess via file."""
import subprocess
import json
import os
import threading
import time

_proc = None
_lock = threading.Lock()
_ready = False

SCRIPT_PATH = "/home/youyeetoo/InNet_box/backend/app/services/llm_runner.py"
PYTHON_PATH = "/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm/.venv/bin/python3"
RESPONSE_FILE = "/tmp/llm_response.json"


def _wait_for_response(timeout=120):
    """Poll response file until it has new content."""
    deadline = time.time() + timeout
    last_mtime = 0
    if os.path.exists(RESPONSE_FILE):
        last_mtime = os.path.getmtime(RESPONSE_FILE)

    while time.time() < deadline:
        if os.path.exists(RESPONSE_FILE):
            mtime = os.path.getmtime(RESPONSE_FILE)
            if mtime > last_mtime:
                with open(RESPONSE_FILE, "r") as f:
                    content = f.read().strip()
                if content:
                    try:
                        return json.loads(content)
                    except:
                        return {"error": "Invalid response: %s" % content[:200]}
        time.sleep(0.1)
    return {"error": "LLM timeout"}


def start():
    """Start the LLM subprocess."""
    global _proc, _ready
    if _proc and _proc.poll() is None:
        return

    # Remove stale response file
    if os.path.exists(RESPONSE_FILE):
        os.unlink(RESPONSE_FILE)

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = (
        "/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm/lib:"
        + env.get("LD_LIBRARY_PATH", "")
    )

    _proc = subprocess.Popen(
        [PYTHON_PATH, SCRIPT_PATH],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
    )

    # Wait for ready signal via file
    result = _wait_for_response(timeout=120)
    if "status" in result and result["status"] == "ready":
        _ready = True
        print("[LLM] Service ready")
    else:
        print("[LLM] Startup failed: %s" % result)


def generate(prompt: str, max_tokens: int = 256) -> dict:
    """Send prompt to LLM subprocess, return response."""
    global _proc, _ready

    if not _ready or not _proc or _proc.poll() is not None:
        start()

    if not _ready:
        return {"error": "LLM not ready"}

    with _lock:
        req = json.dumps({"prompt": prompt, "max_tokens": max_tokens}) + "\n"
        try:
            _proc.stdin.write(req.encode("utf-8"))
            _proc.stdin.flush()
        except Exception as e:
            return {"error": "Write failed: %s" % e}

        return _wait_for_response(timeout=60)


def stop():
    global _proc, _ready
    if _proc:
        _proc.terminate()
        _proc = None
        _ready = False
