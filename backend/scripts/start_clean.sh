#!/bin/bash
# ============================================================
# 干净重启脚本 — 固化版本 2026-07-13
# 每次启动前强制清理缓存 + 杀孤儿进程，确保加载最新代码
# ============================================================
set -e

BACKEND_DIR="/home/youyeetoo/InNet_box/backend"
VENV_PYTHON="/home/youyeetoo/rkllm_model_zoo/funasr_env/bin/python"

echo "[start_clean] 1/5 杀孤儿进程..."
fuser -k 8000/tcp 2>/dev/null || true
sleep 2
ps aux | grep 'run.py' | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null || true
sleep 1

echo "[start_clean] 2/5 清理 Python 缓存..."
find "$BACKEND_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
find "$BACKEND_DIR" -name '*.pyc' -delete 2>/dev/null || true

echo "[start_clean] 3/5 清理数据库锁..."
rm -f "$BACKEND_DIR/data/app.db-journal" "$BACKEND_DIR/data/app.db-wal" 2>/dev/null || true

echo "[start_clean] 4/5 验证环境..."
export PI_AGENT_CHAT=1
export PI_AGENT_DOC=1

echo "[start_clean] 5/5 启动后端..."
cd "$BACKEND_DIR"
source /home/youyeetoo/rkllm_model_zoo/funasr_env/bin/activate
export LD_LIBRARY_PATH=/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm/lib:$LD_LIBRARY_PATH
export HF_ENDPOINT=https://hf-mirror.com
nohup "$VENV_PYTHON" scripts/run.py > "$BACKEND_DIR/data/server.log" 2>&1 &
BACKEND_PID=$!
echo "[start_clean] Backend PID: $BACKEND_PID"

echo "[start_clean] 等待就绪..."
for i in $(seq 1 30); do
    sleep 2
    if curl -sf http://127.0.0.1:8000/api/v1/health > /dev/null 2>&1; then
        echo "[start_clean] Backend healthy after ${i}x2=$((i*2))s"
echo "[start_clean] 6/6 重启 PI Agent (systemd)..."
systemctl --user restart openclaw-chat openclaw-doc
sleep 5
for port in 18790 18791 8099; do
    if ss -tlnp 2>/dev/null | grep -q ":${port}\b"; then
        echo "[start_clean]   Port $port OK"
    else
        echo "[start_clean]   WARNING: Port $port not listening"
    fi
done

        echo "[start_clean] DONE"
        exit 0
    fi
done
echo "[start_clean] ERROR: Backend failed to start within 60s"
exit 1
