#!/usr/bin/env python3
"""Persistent MiniCPM-V 2.6 visual analysis service.

The service keeps the vision encoder and RKLLM process loaded, accepts image
analysis requests over localhost HTTP, and serializes inference so RK3588 stays
stable. It intentionally uses only the Python standard library in the parent
process so it can run inside the MiniCPM virtualenv without extra web deps.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from multiprocessing import Event, Process, Queue
from pathlib import Path
from queue import Empty

WORKDIR = "/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm"
VISION_PATH = "model/vision_transformer.rknn"
LLM_PATH = "model/qwen.rkllm"
IMG_SIZE = 448
MAX_TOKENS = 512
DEFAULT_PORT = 8002


def _setup_path() -> None:
    os.chdir(WORKDIR)
    sys.path.insert(0, WORKDIR)
    os.environ["RKLLM_LOG_LEVEL"] = "1"


def _vision_process(ready_q, image_q, embed_q, start_event) -> None:
    _setup_path()
    import cv2
    import numpy as np
    from rknnlite.api.rknn_lite import RKNNLite

    encoder = RKNNLite(verbose=False)
    encoder.load_rknn(VISION_PATH)
    encoder.init_runtime(core_mask=RKNNLite.NPU_CORE_0_1_2)
    ready_q.put("vision_ready")
    start_event.wait()

    while True:
        image_path = image_q.get()
        if image_path == "STOP":
            break
        try:
            img = cv2.imread(image_path)
            if img is None:
                embed_q.put({"error": "Cannot read image: %s" % image_path})
                continue
            img = cv2.resize(img, (IMG_SIZE, IMG_SIZE))
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img = img.astype("float32")[None, :, :, :]
            t0 = time.time()
            embed = encoder.inference(inputs=[img], data_type="float32", data_format="nhwc")[0].astype("float32")
            embed_q.put({"embed": embed, "vision_s": round(time.time() - t0, 3)})
        except Exception as exc:
            embed_q.put({"error": str(exc)})

    try:
        encoder.release()
    except Exception:
        pass


def _llm_process(ready_q, embed_q, prompt_q, result_q, start_event) -> None:
    _setup_path()
    import rkllm_binding
    from rkllm_binding import (
        LLMCallState,
        RKLLMExtendParam,
        RKLLMInferMode,
        RKLLMInferParam,
        RKLLMInputType,
    )

    output = []
    token_count = 0
    started_at = 0.0

    def callback(result, userdata, state):
        nonlocal output, token_count
        if state == LLMCallState.RKLLM_RUN_NORMAL:
            token_count += 1
            output.append(result.contents.text.decode("utf-8", errors="replace"))

    param = rkllm_binding.create_default_param()
    param.model_path = LLM_PATH.encode()
    param.max_new_tokens = MAX_TOKENS
    param.img_start = b"<image>"
    param.img_end = b"</image>"
    param.img_content = b"<unk>"
    extend_param = RKLLMExtendParam()
    extend_param.base_domain_id = 1
    param.extend_param = extend_param

    handle = rkllm_binding.init(param, callback)
    ready_q.put("llm_ready")
    start_event.wait()

    while True:
        prompt = prompt_q.get()
        if prompt == "STOP":
            break
        embed_payload = embed_q.get()
        if isinstance(embed_payload, dict) and embed_payload.get("error"):
            result_q.put({"error": embed_payload["error"], "text": ""})
            continue

        output = []
        token_count = 0
        started_at = time.time()
        rkllm_input = rkllm_binding.create_rkllm_input(
            RKLLMInputType.RKLLM_INPUT_MULTIMODAL,
            prompt=prompt,
            image_embed=embed_payload["embed"],
        )
        infer_param = RKLLMInferParam()
        infer_param.mode = RKLLMInferMode.RKLLM_INFER_GENERATE.value
        rkllm_binding.run(handle, rkllm_input, infer_param, None)
        result_q.put({
            "text": "".join(output).strip(),
            "tokens": token_count,
            "vision_s": embed_payload.get("vision_s", 0),
            "llm_s": round(time.time() - started_at, 3),
            "service": "minicpm_persistent",
        })

    rkllm_binding.destroy(handle)


def build_prompt(user_prompt: str | None = None) -> str:
    instruction = (user_prompt or "").strip() or (
        "请先描述图片里真实可见的视觉内容：人物、动作、物体、场景、环境、运动或事件。"
        "如果图片里有文字、表格、图表、截图、印章或签名，再继续提取和说明。"
        "不要因为没有可读文字就说图片没有内容；普通照片也必须描述画面。"
        "不要识别人物身份。请用中文直接回答。"
    )
    return (
        "<|im_start|>system\n"
        "You are a careful visual image understanding model and OCR assistant. "
        "For ordinary photos, visual scene understanding is the first priority. "
        "OCR is secondary.<|im_end|>\n"
        "<|im_start|>user\n"
        "<image_id>0</image_id><image>\n"
        + instruction
        + "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


class MiniCPMWorker:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.ready = False
        self.error = ""
        self.ready_q = Queue()
        self.image_q = Queue()
        self.embed_q = Queue()
        self.prompt_q = Queue()
        self.result_q = Queue()
        self.start_event = Event()
        self.vision_proc: Process | None = None
        self.llm_proc: Process | None = None

    def start(self) -> None:
        with self.lock:
            if self.ready:
                return
            self.error = ""
            self.vision_proc = Process(target=_vision_process, args=(self.ready_q, self.image_q, self.embed_q, self.start_event))
            self.llm_proc = Process(target=_llm_process, args=(self.ready_q, self.embed_q, self.prompt_q, self.result_q, self.start_event))
            self.vision_proc.start()
            self.llm_proc.start()
            ready = set()
            deadline = time.time() + 150
            while len(ready) < 2 and time.time() < deadline:
                try:
                    ready.add(self.ready_q.get(timeout=2))
                except Empty:
                    if not self._children_alive():
                        self.error = "MiniCPM process exited early"
                        self.stop()
                        raise RuntimeError(self.error)
            if len(ready) < 2:
                self.error = "MiniCPM service load timeout: " + ",".join(sorted(ready))
                self.stop()
                raise RuntimeError(self.error)
            self.start_event.set()
            self.ready = True

    def analyze(self, image_path: str, prompt: str = "", max_tokens: int | None = None) -> dict:
        if not self.ready:
            self.start()
        if not self._children_alive():
            self.ready = False
            raise RuntimeError("MiniCPM persistent process is not alive")
        with self.lock:
            self.image_q.put(image_path)
            self.prompt_q.put(build_prompt(prompt))
            try:
                result = self.result_q.get(timeout=300)
            except Empty:
                raise RuntimeError("MiniCPM persistent inference timeout")
            return result

    def status(self) -> dict:
        return {
            "status": "ready" if self.ready and self._children_alive() else "loading",
            "error": self.error,
            "vision_pid": self.vision_proc.pid if self.vision_proc else None,
            "llm_pid": self.llm_proc.pid if self.llm_proc else None,
        }

    def stop(self) -> None:
        try:
            self.image_q.put("STOP")
            self.prompt_q.put("STOP")
        except Exception:
            pass
        for proc in (self.vision_proc, self.llm_proc):
            if not proc:
                continue
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
        self.ready = False

    def _children_alive(self) -> bool:
        return bool(self.vision_proc and self.vision_proc.is_alive() and self.llm_proc and self.llm_proc.is_alive())


WORKER = MiniCPMWorker()


class Handler(BaseHTTPRequestHandler):
    server_version = "MiniCPMService/1.0"

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self._json(200, WORKER.status())
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/analyze":
            self._json(404, {"error": "not found"})
            return
        try:
            body = self._read_json()
            image_path = str(body.get("image_path") or body.get("path") or "")
            if not image_path or not Path(image_path).exists():
                self._json(400, {"error": "image_path not found", "text": ""})
                return
            result = WORKER.analyze(
                image_path,
                prompt=str(body.get("prompt") or ""),
                max_tokens=body.get("max_tokens"),
            )
            status = 500 if result.get("error") else 200
            self._json(status, result)
        except Exception as exc:
            self._json(500, {"error": str(exc), "text": ""})

    def log_message(self, fmt, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8", errors="replace") or "{}")

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    port = int(os.environ.get("MINICPM_SERVICE_PORT") or (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PORT))

    def shutdown(signum, frame):
        WORKER.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    WORKER.start()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(json.dumps({"status": "ready", "port": port}, ensure_ascii=False), flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
