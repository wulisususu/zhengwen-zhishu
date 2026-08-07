#!/usr/bin/env bash
# Safe compatibility wrapper: report only; no process killing, no session deletion.
set -euo pipefail
cd /home/youyeetoo/InNet_box/backend
source /home/youyeetoo/rkllm_model_zoo/funasr_env/bin/activate
exec python3 scripts/openclaw_health_report.py --hours 12 --deep
