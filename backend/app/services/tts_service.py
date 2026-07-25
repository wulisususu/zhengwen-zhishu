"""TTS service: text -> WAV audio bytes using local Piper TTS."""
import os
import subprocess
import tempfile

PIPER_PYTHON = os.getenv("PIPER_PYTHON", "/home/youyeetoo/piper_tts/bin/python")
PIPER_MODEL = os.getenv("PIPER_MODEL", "/home/youyeetoo/piper_tts/models/zh_CN-huayan-medium.onnx")
PIPER_CONFIG = os.getenv("PIPER_CONFIG", "/home/youyeetoo/piper_tts/models/zh_CN-huayan-medium.onnx.json")
PIPER_TIMEOUT_SECONDS = int(os.getenv("PIPER_TIMEOUT_SECONDS", "120"))


def synthesize(text: str) -> bytes:
    """Convert text to WAV audio bytes using Piper."""
    text = (text or "").strip()
    if not text:
        raise ValueError("text is required")

    if not os.path.exists(PIPER_MODEL):
        raise RuntimeError(f"Piper model not found: {PIPER_MODEL}")
    if not os.path.exists(PIPER_CONFIG):
        raise RuntimeError(f"Piper config not found: {PIPER_CONFIG}")

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    env = os.environ.copy()
    env.setdefault("ORT_LOG_SEVERITY_LEVEL", "3")

    try:
        result = subprocess.run(
            [
                PIPER_PYTHON,
                "-m",
                "piper",
                "--model",
                PIPER_MODEL,
                "--config",
                PIPER_CONFIG,
                "--output_file",
                tmp.name,
                "--sentence-silence",
                "0.2",
            ],
            input=text + "\n",
            text=True,
            capture_output=True,
            timeout=PIPER_TIMEOUT_SECONDS,
            env=env,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "Piper failed").strip()
            raise RuntimeError(err)

        with open(tmp.name, "rb") as f:
            audio = f.read()
        if not audio:
            raise RuntimeError("Piper returned empty audio")
        return audio
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Piper synthesis timed out") from exc
    finally:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass
