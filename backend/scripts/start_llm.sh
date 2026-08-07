#!/bin/bash
# Start RKLLM inference server on RK3588 NPU
cd /home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm
source .venv/bin/activate
export LD_LIBRARY_PATH=/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm/lib:$LD_LIBRARY_PATH

python3 /home/youyeetoo/InNet_box/backend/app/services/llm_server.py \
    --model /home/youyeetoo/rkllm_model_zoo/DeepSeek-R1-Distill-Qwen-1.5B_W8A8_RK3588.rkllm \
    --port 8001
