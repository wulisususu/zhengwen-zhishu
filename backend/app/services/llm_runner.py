#!/usr/bin/env python3
"""REMOVED: DeepSeek-R1-1.5B RKLLM inference (disabled) service.
Reads prompts from stdin (JSON), writes responses to a pipe file.
Model stays loaded between requests.
"""
import os
import sys
import json
import time

os.chdir("/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm")
sys.path.insert(0, ".")

# Response file path - manager reads from here
RESPONSE_FILE = "/tmp/llm_response.json"

import rkllm_binding
from rkllm_binding import (
    RKLLMParam, RKLLMExtendParam, RKLLMInferParam, RKLLMInferMode,
    RKLLMInputType, LLMCallState,
)

# MODEL_PATH = "/home/youyeetoo/rkllm_model_zoo/DeepSeek-R1-Distill-Qwen-1.5B_W8A8_RK3588.rkllm"  # REMOVED: 1.5B model disabled

handle = None
out_text = ""
ttft = 0
t_start = 0


def result_callback(result, userdata, state):
    global out_text, ttft, t_start
    if state == LLMCallState.RKLLM_RUN_NORMAL:
        if not out_text:
            ttft = time.time() - t_start
        out_text += result.contents.text.decode("utf-8", errors="replace")


def write_response(data):
    """Write JSON response to file."""
    with open(RESPONSE_FILE, "w") as f:
        f.write(json.dumps(data, ensure_ascii=False))


def load_model():
    global handle
    os.environ["RKLLM_LOG_LEVEL"] = "1"
    param = rkllm_binding.create_default_param()
    param.model_path = MODEL_PATH.encode()
    ext = RKLLMExtendParam()
    ext.base_domain_id = 1
    param.extend_param = ext

    sys.stderr.write("# Loading DeepSeek-R1-1.5B...  # REMOVED\n")
    sys.stderr.flush()
    t0 = time.time()
    handle = rkllm_binding.init(param, result_callback)
    sys.stderr.write("Model loaded in %.1fs\n" % (time.time() - t0))
    sys.stderr.flush()


def generate(prompt, max_tokens=256):
    global out_text, ttft, t_start
    out_text = ""
    ttft = 0
    t_start = time.time()

    rkllm_input = rkllm_binding.create_rkllm_input(
        RKLLMInputType.RKLLM_INPUT_PROMPT,
        prompt=prompt,
    )
    infer_param = RKLLMInferParam()
    infer_param.mode = RKLLMInferMode.RKLLM_INFER_GENERATE.value

    rkllm_binding.run(handle, rkllm_input, infer_param, None)

    total = time.time() - t_start
    return {
        "text": out_text.strip(),
        "ttft_s": round(ttft, 3),
        "total_s": round(total, 3),
    }


def main():
    load_model()

    # Signal ready via file
    write_response({"status": "ready"})

    # Read prompts from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            prompt = req.get("prompt", "")
            max_tokens = req.get("max_tokens", 256)
            result = generate(prompt, max_tokens)
            write_response(result)
        except Exception as e:
            write_response({"error": str(e)})


if __name__ == "__main__":
    main()
