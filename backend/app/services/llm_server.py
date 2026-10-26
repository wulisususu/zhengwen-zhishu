#!/usr/bin/env python3
"""
FastAPI LLM Server for RK3588.
Supports sync + SSE streaming via file-based communication.
"""
import os
import sys
import json
import time
import subprocess
import threading

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="LLM Server", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

MODEL = "/home/youyeetoo/rkllm_model_zoo/qwen2.5-1.5b-rkllm/Qwen2.5-1.5B-Instruct_W8A8_RK3588.rkllm"
WORKDIR = "/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm"
PYTHON = WORKDIR + "/.venv/bin/python3"
LIB = WORKDIR + "/lib"
REQUEST_FILE = "/tmp/llm_request.json"
RESPONSE_FILE = "/tmp/llm_response.json"
STREAM_FILE = "/tmp/llm_stream.jsonl"

_proc = None
_ready = False
_paused = False
_lock = threading.Lock()

RUNNER_SCRIPT = "/tmp/_llm_persistent.py"


def write_runner():
    code = '''
import os, sys, json, time, re
os.chdir("WORKDIR")
sys.path.insert(0, ".")
os.environ["RKLLM_LOG_LEVEL"] = "1"
import rkllm_binding
from rkllm_binding import RKLLMParam, RKLLMExtendParam, RKLLMInferParam, RKLLMInferMode, RKLLMInputType, LLMCallState

MODEL = "MODEL_PATH"
REQ = "REQUEST_PATH"
RESP = "RESPONSE_PATH"
STREAM = "STREAM_PATH"

token_count = 0
stream_fp = None
current_output = []

def cb(r, ud, s):
    global token_count, stream_fp, current_output
    if s == LLMCallState.RKLLM_RUN_NORMAL:
        text = r.contents.text.decode("utf-8", errors="replace")
        token_count += 1
        current_output.append(text)
        # Write each token to stream file immediately
        if stream_fp:
            stream_fp.write(json.dumps({"type": "token", "content": text}, ensure_ascii=False) + "\\n")
            stream_fp.flush()
    elif s == LLMCallState.RKLLM_RUN_FINISH:
        if stream_fp:
            stream_fp.write(json.dumps({"type": "done"}) + "\\n")
            stream_fp.flush()

param = rkllm_binding.create_default_param()
param.model_path = MODEL.encode()
param.max_context_len = 4096
param.max_new_tokens = 512
param.top_k = 40
param.top_p = 0.9
param.temperature = 0.7
param.repeat_penalty = 1.2
ext = RKLLMExtendParam()
ext.base_domain_id = 1
ext.n_batch = 1
ext.enabled_cpus_num = 4
ext.enabled_cpus_mask = 0xF0
param.extend_param = ext

sys.stderr.write("Loading model...\\n")
sys.stderr.flush()
t0 = time.time()
handle = rkllm_binding.init(param, cb)
sys.stderr.write("Model loaded in %.1fs\\n" % (time.time() - t0))
sys.stderr.flush()

with open(RESP, "w") as f:
    f.write(json.dumps({"status": "ready"}))

last_mtime = 0
while True:
    time.sleep(0.1)
    if not os.path.exists(REQ):
        continue
    mtime = os.path.getmtime(REQ)
    if mtime <= last_mtime:
        continue
    last_mtime = mtime
    with open(REQ) as f:
        raw = f.read()
    try:
        req = json.loads(raw)
    except:
        req = {"prompt": raw}
    prompt = req.get("prompt", "")
    stream_mode = req.get("stream", False)

    token_count = 0
    current_output = []

    if stream_mode:
        # Open stream file for token-by-token output
        if os.path.exists(STREAM):
            os.unlink(STREAM)
        stream_fp = open(STREAM, "w")

    t1 = time.time()
    inp = rkllm_binding.create_rkllm_input(RKLLMInputType.RKLLM_INPUT_PROMPT, prompt=prompt)
    ip = RKLLMInferParam()
    ip.mode = RKLLMInferMode.RKLLM_INFER_GENERATE.value
    rkllm_binding.run(handle, inp, ip, None)
    gen_time = time.time() - t1

    if stream_fp:
        stream_fp.close()
        stream_fp = None

    # Use callback-collected tokens for non-streaming; stream file is a fallback.
    full = "".join(current_output)
    full = re.sub(r"<think[\\s\\S]*?</think>", "", full)
    full = re.sub(r"<think[\\s\\S]*$", "", full)
    for _tok in ("<|im_end|>", "<|endoftext|>", "<|im_start|>"):
        full = full.replace(_tok, "")
    if not full and os.path.exists(STREAM):
        with open(STREAM) as f:
            for line in f:
                try:
                    obj = json.loads(line.strip())
                    if obj.get("type") == "token":
                        full += obj.get("content", "")
                except:
                    pass

    with open(RESP, "w") as f:
        f.write(json.dumps({"text": full.strip(), "gen_s": round(gen_time, 2), "tokens": token_count}, ensure_ascii=False))
'''.replace("WORKDIR", WORKDIR).replace("MODEL_PATH", MODEL).replace(
    "REQUEST_PATH", REQUEST_FILE).replace("RESPONSE_PATH", RESPONSE_FILE).replace(
    "STREAM_PATH", STREAM_FILE)

    with open(RUNNER_SCRIPT, "w") as f:
        f.write(code)


def start_llm():
    global _proc, _ready
    if _paused:
        _ready = False
        return
    if _proc and _proc.poll() is None:
        return

    write_runner()

    for f in [REQUEST_FILE, RESPONSE_FILE, STREAM_FILE]:
        if os.path.exists(f):
            os.unlink(f)

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = LIB + ":" + env.get("LD_LIBRARY_PATH", "")

    _proc = subprocess.Popen(
        [PYTHON, RUNNER_SCRIPT],
        stdout=subprocess.DEVNULL,
        stderr=open("/home/youyeetoo/backend/data/llm_runner.err", "ab", buffering=0),
        env=env,
    )

    deadline = time.time() + 120
    while time.time() < deadline:
        if os.path.exists(RESPONSE_FILE):
            with open(RESPONSE_FILE) as f:
                content = f.read().strip()
            if "ready" in content:
                _ready = True
                print("[LLM] Ready", flush=True)
                return
        time.sleep(0.5)
    print("[LLM] Timeout", flush=True)


def stop_llm():
    global _proc, _ready
    _ready = False
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _proc.kill()
            try:
                _proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
    _proc = None


def llm_generate(prompt: str) -> dict:
    global _proc, _ready
    if _paused:
        return {"error": "LLM paused for OCR"}
    if not _ready or not _proc or _proc.poll() is not None:
        start_llm()
    if not _ready:
        return {"error": "LLM not ready"}

    with _lock:
        for f in [RESPONSE_FILE, STREAM_FILE]:
            if os.path.exists(f):
                os.unlink(f)
        with open(REQUEST_FILE, "w") as f:
            f.write(json.dumps({"prompt": prompt, "stream": False}))

        deadline = time.time() + 120
        while time.time() < deadline:
            if os.path.exists(RESPONSE_FILE):
                with open(RESPONSE_FILE) as f:
                    content = f.read().strip()
                if content:
                    try:
                        result = json.loads(content)
                        if "text" in result:
                            return result
                    except:
                        pass
            time.sleep(0.1)
        return {"error": "LLM timeout"}


def llm_generate_stream(prompt: str):
    """Streaming: yield SSE events as tokens arrive."""
    global _proc, _ready
    if _paused:
        yield "data: " + json.dumps({"error": "LLM paused for OCR"}) + "\n\n"
        return
    if not _ready or not _proc or _proc.poll() is not None:
        start_llm()
    if not _ready:
        yield "data: " + json.dumps({"error": "LLM not ready"}) + "\n\n"
        return

    with _lock:
        for f in [RESPONSE_FILE, STREAM_FILE]:
            if os.path.exists(f):
                os.unlink(f)
        with open(REQUEST_FILE, "w") as f:
            f.write(json.dumps({"prompt": prompt, "stream": True}))

        # Poll stream file for tokens
        last_pos = 0
        deadline = time.time() + 120
        while time.time() < deadline:
            if os.path.exists(STREAM_FILE):
                with open(STREAM_FILE, "r") as sf:
                    sf.seek(last_pos)
                    new_data = sf.read()
                    last_pos = sf.tell()

                if new_data:
                    for line in new_data.strip().split("\n"):
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            if obj.get("type") == "token":
                                piece = obj["content"]
                                # 同时给 text 与 OpenAI 的 choices[].delta，
                                # 简化客户端与 OpenAI 客户端都能直接消费
                                yield "data: " + json.dumps({
                                    "text": piece,
                                    "choices": [{"index": 0, "delta": {"content": piece},
                                                 "finish_reason": None}],
                                }, ensure_ascii=False) + "\n\n"
                            elif obj.get("type") == "done":
                                # Read final result from response file
                                time.sleep(0.1)
                                if os.path.exists(RESPONSE_FILE):
                                    with open(RESPONSE_FILE) as rf:
                                        result = json.loads(rf.read().strip())
                                    yield "data: " + json.dumps({"text": "", "done": True, "gen_s": result.get("gen_s", 0), "tokens": result.get("tokens", 0)}, ensure_ascii=False) + "\n\n"
                                yield "data: [DONE]\n\n"
                                return
                        except:
                            pass
            time.sleep(0.05)
        yield "data: " + json.dumps({"error": "timeout"}) + "\n\n"


@app.on_event("startup")
def startup():
    start_llm()


@app.get("/health")
def health():
    if _paused:
        return {"status": "paused"}
    return {"status": "ready" if _ready else "loading"}


@app.post("/admin/pause")
def pause_for_ocr():
    global _paused
    with _lock:
        _paused = True
        stop_llm()
    return {"status": "paused"}


@app.post("/admin/resume")
def resume_after_ocr():
    global _paused
    _paused = False
    threading.Thread(target=start_llm, daemon=True).start()
    return {"status": "loading"}


@app.post("/v1/completions")
async def completions(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "")
    stream = body.get("stream", False)
    if not prompt:
        return JSONResponse({"error": "prompt required"}, status_code=400)

    if stream:
        return StreamingResponse(
            llm_generate_stream(prompt),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = llm_generate(prompt)
        if "error" in result:
            return JSONResponse(result, status_code=500)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    # Qwen / DeepSeek-R1-Distill 系列使用 ChatML 模板，模板不对会导致模型不停止并退化
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        parts.append("<|im_start|>%s\n%s<|im_end|>\n" % (role, content))
    parts.append("<|im_start|>assistant\n")
    prompt = "".join(parts)

    if stream:
        def sse_stream():
            for event in llm_generate_stream(prompt):
                yield event
        return StreamingResponse(sse_stream(), media_type="text/event-stream")

    try:
        result = llm_generate(prompt)
        if "error" in result:
            return JSONResponse({"error": result["error"]}, status_code=500)
        return {"choices": [{"message": {"role": "assistant", "content": result["text"]}, "finish_reason": "stop"}]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
