#!/usr/bin/env python3
"""DeepSeek RKLLM inference server - stdin/stdout based.
Runs as a standalone process, communicates via JSON lines on stdin.
Uses os.dup2 to redirect C-level stdout during inference.
"""
import os
import sys
import json
import time

os.chdir("/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm")
sys.path.insert(0, ".")
os.environ["RKLLM_LOG_LEVEL"] = "1"

import rkllm_binding
from rkllm_binding import (
    RKLLMParam, RKLLMExtendParam, RKLLMInferParam,
    RKLLMInferMode, RKLLMInputType, LLMCallState,
)

# MODEL_PATH = "/home/youyeetoo/rkllm_model_zoo/DeepSeek-R1-Distill-Qwen-1.5B_W8A8_RK3588.rkllm"  # REMOVED: 1.5B model disabled
RESPONSE_FILE = "/tmp/llm_response.json"

handle = None
out_text = ""
ttft = 0
t_start = 0


def callback(result, userdata, state):
    global out_text, ttft, t_start
    if state == LLMCallState.RKLLM_RUN_NORMAL:
        if not out_text:
            ttft = time.time() - t_start
        out_text += result.contents.text.decode("utf-8", errors="replace")


def write_response(data):
    with open(RESPONSE_FILE, "w") as f:
        f.write(json.dumps(data, ensure_ascii=False))
        f.flush()


def generate(prompt):
    global out_text, ttft, t_start
    out_text = ""
    ttft = 0
    t_start = time.time()

    inp = rkllm_binding.create_rkllm_input(
        RKLLMInputType.RKLLM_INPUT_PROMPT, prompt=prompt
    )
    infer_p = RKLLMInferParam()
    infer_p.mode = RKLLMInferMode.RKLLM_INFER_GENERATE.value

    rkllm_binding.run(handle, inp, infer_p, None)

    total = time.time() - t_start
    return {"text": out_text.strip(), "ttft_s": round(ttft, 3), "total_s": round(total, 3)}


def main():
    global handle
    param = rkllm_binding.create_default_param()
    param.model_path = MODEL_PATH.encode()
    ext = RKLLMExtendParam()
    ext.base_domain_id = 1
    param.extend_param = ext

    sys.stderr.write("# Loading DeepSeek-R1-1.5B...  # REMOVED\n")
    sys.stderr.flush()
    t0 = time.time()
    handle = rkllm_binding.init(param, callback)
    sys.stderr.write("Model loaded in %.1fs\n" % (time.time() - t0))
    sys.stderr.flush()

    # Signal ready
    write_response({"status": "ready"})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            prompt = req.get("prompt", "")
            result = generate(prompt)
            write_response(result)
        except Exception as e:
            write_response({"error": str(e)})


if __name__ == "__main__":
    main()
