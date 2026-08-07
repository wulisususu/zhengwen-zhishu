#!/usr/bin/env python3
"""Inference worker — subprocess-isolated so SIGSEGV only kills this process.

Reads JSON request from stdin, outputs JSON result to stdout.
Exit 0 = success, exit 1 = error.
"""
import sys, json, time, os
os.environ["RKLLM_LOG_LEVEL"] = "0"

_RKLLM_DIR = "/home/youyeetoo/rkllm_model_zoo/qwen2.5-3b-rkllm"
sys.path.insert(0, _RKLLM_DIR)
from rkllm_binding import *

MODEL_PATH = "/home/youyeetoo/rkllm_model_zoo/Qwen2.5-3B-Instruct RKLLM/Qwen2.5-3B-Instruct.rkllm"
MAX_CTX = 2048
MAX_NEW = 2048


def do_inference(prompt: str, max_tokens: int) -> dict:
    out = []
    done = [False]
    err = [False]

    def cb(r, u, s):
        if s == LLMCallState.RKLLM_RUN_NORMAL:
            out.append(r.contents.text.decode(errors="replace"))
        elif s == LLMCallState.RKLLM_RUN_FINISH:
            done[0] = True
        elif s == LLMCallState.RKLLM_RUN_ERROR:
            err[0] = True; done[0] = True

    p = create_default_param()
    p.model_path = MODEL_PATH.encode()
    p.max_context_len = MAX_CTX
    p.max_new_tokens = min(max_tokens, MAX_NEW)
    p.top_k = 1; p.top_p = 0.8; p.temperature = 0.1
    p.repeat_penalty = 1.05; p.skip_special_token = True
    e = RKLLMExtendParam(); e.base_domain_id = 0; p.extend_param = e

    h = init(p, cb)
    ip = RKLLMInferParam()
    ip.mode = RKLLMInferMode.RKLLM_INFER_GENERATE.value
    ri = create_rkllm_input(RKLLMInputType.RKLLM_INPUT_PROMPT, prompt=prompt)

    t0 = time.time()
    run(h, ri, ip, None)        # ← SIGSEGV kills only this worker
    elapsed = time.time() - t0

    try: destroy(h)
    except Exception: pass

    if err[0]:
        return {"error": "Inference error"}
    return {"result": "".join(out), "elapsed": round(elapsed, 2)}


def main():
    try:
        request = json.loads(sys.stdin.read())
    except Exception as e:
        print(json.dumps({"error": f"Invalid request: {e}"}))
        sys.exit(1)

    prompt = request.get("prompt", "")
    max_tokens = request.get("max_tokens", 256)
    result = do_inference(prompt, max_tokens)

    # Print JSON marker line — parent finds this among C lib noise
    print("__JSON_RESULT__" + json.dumps(result, ensure_ascii=False))
    sys.exit(1 if "error" in result else 0)


if __name__ == "__main__":
    main()
