"""TTS service: text -> WAV audio bytes using local MeloTTS :5101.
MeloTTS API: POST /tts → {audio_url} → GET /audio/xxx.wav → bytes
"""
import logging
import requests

MELO_API = "http://127.0.0.1:5101"
logger = logging.getLogger(__name__)


def synthesize(text: str, speaker: str = "ZH", speed: float = 1.0) -> bytes:
    text = (text or "").strip()
    if not text:
        raise ValueError("text is required")

    try:
        # Step 1: POST /tts to synthesize
        resp = requests.post(
            f"{MELO_API}/tts",
            json={"text": text, "speaker": speaker, "speed": speed},
            timeout=120,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"MeloTTS POST failed ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()
        audio_url = data.get("audio_url", "")
        if not audio_url:
            raise RuntimeError(f"MeloTTS returned no audio_url: {data}")

        # Step 2: GET the WAV file
        resp2 = requests.get(f"{MELO_API}{audio_url}", timeout=60)
        if resp2.status_code != 200:
            raise RuntimeError(f"MeloTTS GET audio failed ({resp2.status_code})")
        return resp2.content

    except requests.exceptions.ConnectionError:
        raise RuntimeError("MeloTTS service is not running on :5101")
    except requests.exceptions.Timeout:
        raise RuntimeError("MeloTTS synthesis timed out")
