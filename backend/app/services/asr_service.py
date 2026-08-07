"""ASR service.

Pipeline (default — ONNX full model):
  WAV -> WavFrontend(CPU) -> ONNX Encoder+Decoder(CPU) -> text

Set USE_RKNN=1 env var to use RKNN NPU encoder (experimental).
"""
import os
import sys
import json
import logging
import requests
from typing import Tuple

import numpy as np
import librosa

from app.config import get_config
logger = logging.getLogger(__name__)

# --------------- paths ---------------
_FLOAT_DIR = "/home/youyeetoo/INnet_agent/backend/app/Fun_ASR_float"
_RKNN_ENCODER = os.path.join(_FLOAT_DIR, "encoder_v6.rknn")
_FULL_ONNX = os.path.join(_FLOAT_DIR, "model.onnx")
_DECODER_ONNX = os.path.join(_FLOAT_DIR, "decoder_fixed.onnx")
_ORIG_MODEL_DIR = "/home/youyeetoo/INnet_agent/backend/app/Fun_ASR"
_CMVN_FILE = os.path.join(_ORIG_MODEL_DIR, "am.mvn")
_TOKEN_FILE = os.path.join(_ORIG_MODEL_DIR, "tokens.json")

# --------------- singletons ---------------
_paraformer = None
_rknn = None
_full_session = None
_dec_session = None
_frontend = None
_token_list = None

SAMPLE_RATE = 16000
_PRED_BIAS = 1
_MAX_SEQ = 512
try:
    _ASR_CFG = get_config().get("asr", {})
except Exception:
    _ASR_CFG = {}
_MODE = os.environ.get("ASR_MODE") or _ASR_CFG.get("mode", "quant")  # quant | float | rknn | pytorch
_PYTORCH_WORKER_URL = "http://127.0.0.1:8003/transcribe"



# ============================================================
#  Init
# ============================================================

def _get_frontend():
    global _frontend
    if _frontend is None:
        sys.path.insert(0,
            "/home/youyeetoo/rkllm_model_zoo/funasr_env/lib/python3.10/site-packages")
        from funasr_onnx.utils.frontend import WavFrontend
        _frontend = WavFrontend(
            cmvn_file=_CMVN_FILE, fs=16000, window="hamming",
            n_mels=80, frame_length=25, frame_shift=10,
            lfr_m=7, lfr_n=6, dither=1.0)
    return _frontend


def _get_full_session():
    """Full float ONNX model on CPU."""
    global _full_session
    if _full_session is None:
        import onnxruntime as ort
        _full_session = ort.InferenceSession(
            _FULL_ONNX, providers=["CPUExecutionProvider"])
        logger.info("Full float ONNX loaded")
    return _full_session


def _get_paraformer():
    """Original quantized Paraformer (fastest on CPU)."""
    global _paraformer
    if _paraformer is None:
        from funasr_onnx.paraformer_bin import Paraformer
        _paraformer = Paraformer(model_dir=_ORIG_MODEL_DIR, quantize=True)
        logger.info("Quantized Paraformer loaded")
    return _paraformer


def _get_rknn():
    global _rknn
    if _rknn is None:
        from rknnlite.api import RKNNLite
        rknn = RKNNLite()
        rknn.load_rknn(_RKNN_ENCODER)
        rknn.init_runtime()
        _rknn = rknn
        logger.info("RKNN encoder loaded")
    return _rknn


def _get_dec_session():
    """Decoder-only ONNX on CPU (used with RKNN encoder)."""
    global _dec_session
    if _dec_session is None:
        import onnxruntime as ort
        _dec_session = ort.InferenceSession(
            _DECODER_ONNX, providers=["CPUExecutionProvider"])
        logger.info("Decoder ONNX loaded")
    return _dec_session


def _get_tokens():
    global _token_list
    if _token_list is None:
        with open(_TOKEN_FILE, "r", encoding="utf-8") as f:
            _token_list = json.load(f)
    return _token_list


# ============================================================
#  Feature extraction (CPU)
# ============================================================

def _extract(wav_path: str) -> Tuple[np.ndarray, np.ndarray]:
    frontend = _get_frontend()
    waveform, _ = librosa.load(wav_path, sr=SAMPLE_RATE)
    speech, _ = frontend.fbank(waveform)
    feat, feat_len = frontend.lfr_cmvn(speech)  # [seq, 560]

    seq = feat.shape[0]
    if seq < _MAX_SEQ:
        pad = np.zeros((_MAX_SEQ - seq, feat.shape[1]), dtype=np.float32)
        feat = np.concatenate([feat, pad], axis=0)
    else:
        feat = feat[:_MAX_SEQ]
        seq = _MAX_SEQ

    feats = np.expand_dims(feat, 0).astype(np.float32)
    feats_len = np.array([min(seq, _MAX_SEQ)], dtype=np.int32)
    return feats, feats_len


# ============================================================
#  Inference
# ============================================================

def _infer_full(feats: np.ndarray, feats_len: np.ndarray):
    """Full model on CPU."""
    sess = _get_full_session()
    names = [i.name for i in sess.get_inputs()]
    outputs = sess.run(None, {names[0]: feats, names[1]: feats_len})
    return outputs[0], int(outputs[1][0])


def _infer_split(feats: np.ndarray, feats_len: np.ndarray):
    """RKNN encoder (NPU) + ONNX decoder (CPU)."""
    rknn = _get_rknn()
    enc_out = rknn.inference(inputs=[feats, feats_len])[0]
    sess = _get_dec_session()
    names = [i.name for i in sess.get_inputs()]
    outputs = sess.run(None, {names[0]: enc_out, names[1]: feats_len})
    return outputs[0], int(outputs[1][0])


# ============================================================
#  Token -> text
# ============================================================

def _to_text(logits: np.ndarray, token_num: int) -> str:
    tokens = _get_tokens()
    ids = logits[0].argmax(axis=-1)
    ids = [int(t) for t in ids if t not in (0, 2)]
    words = [tokens[t] if t < len(tokens) else "" for t in ids]
    words = words[: max(0, token_num - _PRED_BIAS)]
    return "".join(words).replace("▁", " ").strip()


# ============================================================
#  Public
# ============================================================

def _pytorch_transcribe(wav_path: str) -> str:
    """Transcribe via PyTorch full Paraformer worker on port 8003."""
    try:
        resp = requests.post(_PYTORCH_WORKER_URL, json={"wav_path": wav_path}, timeout=300)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            logger.warning("PyTorch ASR worker error: %s", data["error"])
            return ""
        return data.get("text", "")
    except Exception as e:
        logger.warning("PyTorch ASR worker failed: %s", str(e))
        return ""

def transcribe(wav_path: str) -> str:
    if _MODE == "pytorch":
        return _pytorch_transcribe(wav_path)
    if _MODE == "quant":
        model = _get_paraformer()
        res = model(wav_content=wav_path)
        if res and len(res) > 0 and isinstance(res[0], dict) and "preds" in res[0]:
            return res[0]["preds"][0]
        return str(res)
    else:
        feats, feats_len = _extract(wav_path)
        if _MODE == "rknn":
            logits, tok_n = _infer_split(feats, feats_len)
        else:
            logits, tok_n = _infer_full(feats, feats_len)
        return _to_text(logits, tok_n)


def preload():
    _get_tokens()
    if _MODE == "pytorch":
        logger.info("ASR mode=pytorch, worker handles model loading")
    elif _MODE == "quant":
        _get_paraformer()
    elif _MODE == "rknn":
        _get_frontend()
        _get_rknn()
        _get_dec_session()
    else:
        _get_frontend()
        _get_full_session()
    logger.info("ASR preloaded (mode=%s)", _MODE)


# --------------- Polish config ---------------
try:
    _POLISH_CFG = get_config().get("polish", {})
except Exception:
    _POLISH_CFG = {}
POLISH_API_URL = _POLISH_CFG.get("api_url", "http://127.0.0.1:8002/v1/chat/completions")
POLISH_TIMEOUT = _POLISH_CFG.get("timeout_seconds", 30)

POLISH_SYSTEM_PROMPT = """你是文本润色助手。请对用户输入的语音识别文本进行润色：
1. 去除口语化表达、语气词（如"嗯"、"啊"、"那个"、"就是说"等）和重复内容
2. 修正语法错误和不流畅的表达
3. 凝练文本，保留核心意思，使其更简洁专业
4. 只输出润色后的文本，不要加任何解释或前缀"""

def polish_text(raw_text: str) -> str:
    """Polish ASR output through Qwen3-0.6B.
    
    Returns polished text on success, or raw_text on failure.
    """
    if not raw_text or not raw_text.strip():
        return raw_text
    
    try:
        payload = {
            "messages": [
                {"role": "system", "content": POLISH_SYSTEM_PROMPT},
                {"role": "user", "content": raw_text}
            ],
            "max_tokens": min(len(raw_text) * 2, 512),
            "temperature": 0.3
        }
        resp = requests.post(POLISH_API_URL, json=payload, timeout=POLISH_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices and choices[0].get("message", {}).get("content"):
            polished = choices[0]["message"]["content"].strip()
            if polished:
                logger.info("Polish: %d -> %d chars", len(raw_text), len(polished))
                return polished
    except Exception as e:
        logger.warning("Polish failed, using raw text: %s", str(e))
    
    return raw_text
