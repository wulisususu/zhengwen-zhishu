#!/bin/bash
# 健康排查脚本启动器
# 用法: bash run_health_check.sh
set -e
cd /home/youyeetoo/INnet_agent/backend
source /home/youyeetoo/rkllm_model_zoo/funasr_env/bin/activate
export LD_LIBRARY_PATH=/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm/lib:$LD_LIBRARY_PATH
export PYTHONPATH=/home/youyeetoo/INnet_agent/backend:$PYTHONPATH
python3 /home/youyeetoo/INnet_agent/backend/scripts/health_check.py
