#!/usr/bin/env python3
"""MiniCPM-V 2.6 OCR runner.

The RKLLM build can segfault when the vision encoder and LLM inference live in
one Python process. This runner follows the upstream multiprocessing pattern:
vision and LLM are loaded in separate processes, then the parent returns JSON.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from multiprocessing import Event, Process, Queue
from queue import Empty

WORKDIR = "/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm"
VISION_PATH = "model/vision_transformer.rknn"
LLM_PATH = "model/qwen.rkllm"
IMG_SIZE = 448
MAX_TOKENS = 512
logger = logging.getLogger(__name__)

# RKNN driver resource teardown is asynchronous. Give its page tables and DMA
# allocations time to settle before RKLLM requests the much larger 3B model.
try:
    NPU_RELEASE_SETTLE_SECONDS = max(
        0.0,
        min(30.0, float(os.getenv("MINICPM_NPU_RELEASE_SETTLE_SECONDS", "5"))),
    )
except ValueError:
    NPU_RELEASE_SETTLE_SECONDS = 5.0


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
            img = img.astype(np.float32)[np.newaxis, :, :, :]
            t0 = time.time()
            embed = encoder.inference(inputs=[img], data_type="float32", data_format="nhwc")[0].astype(np.float32)
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
        nonlocal token_count, output, started_at
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
            result_q.put({"error": embed_payload["error"]})
            continue

        output = []
        token_count = 0
        started_at = time.time()
        image_embed = embed_payload["embed"]
        rkllm_input = rkllm_binding.create_rkllm_input(
            RKLLMInputType.RKLLM_INPUT_MULTIMODAL,
            prompt=prompt,
            image_embed=image_embed,
        )
        infer_param = RKLLMInferParam()
        infer_param.mode = RKLLMInferMode.RKLLM_INFER_GENERATE.value
        rkllm_binding.run(handle, rkllm_input, infer_param, None)
        result_q.put({
            "text": "".join(output).strip(),
            "tokens": token_count,
            "vision_s": embed_payload.get("vision_s", 0),
            "llm_s": round(time.time() - started_at, 3),
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
        + instruction +
        "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def main() -> int:
    global MAX_TOKENS
    if len(sys.argv) < 2:
        print(json.dumps({"error": "image path is required"}, ensure_ascii=False))
        return 2
    image_path = sys.argv[1]
    user_prompt = sys.argv[2] if len(sys.argv) >= 3 else ""
    if len(sys.argv) >= 4:
        try:
            MAX_TOKENS = max(32, min(512, int(sys.argv[3])))
        except Exception:
            pass

    ready_q = Queue()
    image_q = Queue()
    embed_q = Queue()
    prompt_q = Queue()
    result_q = Queue()
    start_event = Event()
    vp = Process(target=_vision_process, args=(ready_q, image_q, embed_q, start_event))
    lp = Process(target=_llm_process, args=(ready_q, embed_q, prompt_q, result_q, start_event))

    def wait_until_ready(expected: str, proc: Process, timeout: float = 120) -> None:
        # Wait for one NPU runtime to finish loading before starting the next.
        deadline = time.time() + timeout
        observed: set[str] = set()
        while time.time() < deadline:
            try:
                observed.add(ready_q.get(timeout=2))
            except Empty:
                if not proc.is_alive():
                    raise RuntimeError(
                        f"MiniCPM {expected} process exited during startup "
                        f"(exit={proc.exitcode})"
                    )
                continue
            if expected in observed:
                return
        raise RuntimeError(
            f"MiniCPM {expected} model load timeout "
            f"(observed={','.join(sorted(observed)) or 'none'})"
        )

    try:
        # RKNN Vision and RKLLM both initialise shared NPU cores. Their model
        # loads must never overlap: Vision initialises first, then the LLM.
        vp.start()
        wait_until_ready("vision_ready", vp)

        # Run Vision alone, then release its NPU runtime before RKLLM loads.
        start_event.set()
        image_q.put(image_path)
        try:
            embed_payload = embed_q.get(timeout=120)
        except Empty:
            raise RuntimeError(
                "MiniCPM Vision inference timeout "
                f"(vision_alive={vp.is_alive()}, vision_exit={vp.exitcode})"
            )

        image_q.put("STOP")
        vp.join(timeout=10)
        if vp.is_alive():
            vp.terminate()
            vp.join(timeout=5)
        if vp.exitcode not in (0, None):
            raise RuntimeError(f"MiniCPM Vision exited after inference (exit={vp.exitcode})")

        if NPU_RELEASE_SETTLE_SECONDS:
            logger.info(
                "Waiting %.1fs for RKNN NPU resources to settle before loading RKLLM",
                NPU_RELEASE_SETTLE_SECONDS,
            )
            time.sleep(NPU_RELEASE_SETTLE_SECONDS)

        if isinstance(embed_payload, dict) and embed_payload.get("error"):
            print("###RESULT###" + json.dumps(embed_payload, ensure_ascii=False))
            return 1

        # The parent owns the embedding while no Vision runtime is alive, then
        # hands it to the LLM process. This prevents simultaneous NPU models.
        embed_q.put(embed_payload)
        lp.start()
        wait_until_ready("llm_ready", lp)

        prompt_q.put(build_prompt(user_prompt))
        try:
            result = result_q.get(timeout=240)
        except Empty:
            raise RuntimeError(
                "MiniCPM OCR inference timeout "
                f"(vision_exit={vp.exitcode}, llm_alive={lp.is_alive()}, "
                f"llm_exit={lp.exitcode})"
            )
        print("###RESULT###" + json.dumps(result, ensure_ascii=False))
        return 0 if not result.get("error") else 1
    except Exception as exc:
        print("###RESULT###" + json.dumps({"error": str(exc), "text": ""}, ensure_ascii=False))
        return 1
    finally:
        try:
            image_q.put("STOP")
            prompt_q.put("STOP")
        except Exception:
            pass
        for proc in (vp, lp):
            # lp is intentionally not started if Vision fails its NPU startup.
            if proc.pid is None:
                continue
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
