#!/bin/bash
set -euo pipefail
# Auto-start backend services: RKLLM server (8001), MiniCPM vision (8003),
# backend API (8000), PI Agent chat (18790), PI Agent doc (18791).
# Qwen3-0.6B router remains on :8002 and is managed separately.

echo "Starting LLM server on port 8001..."
cd /home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm
export LD_LIBRARY_PATH=/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm/lib:$LD_LIBRARY_PATH
nohup .venv/bin/python3 /home/youyeetoo/backend/app/services/llm_server.py > /home/youyeetoo/backend/data/llm_server.log 2>&1 &
echo "LLM server PID: $!"

echo "Waiting for LLM model to load..."
sleep 20

echo "Starting MiniCPM persistent visual service on port 8003..."
cd /home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm
export MINICPM_SERVICE_PORT=8003
nohup .venv/bin/python3 /home/youyeetoo/backend/app/services/minicpm_vision_service.py 8003 > /home/youyeetoo/backend/data/minicpm_vision_service.log 2>&1 &
echo "MiniCPM visual service PID: $!"

echo "Piper TTS is loaded on demand by backend."

echo "Preloading embedding model..."
cd /home/youyeetoo/backend
source /home/youyeetoo/rkllm_model_zoo/funasr_env/bin/activate
export HF_ENDPOINT=https://hf-mirror.com
export LD_LIBRARY_PATH=/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm/lib:$LD_LIBRARY_PATH
nohup python -c "from app.kb.embedding import get_embedding_model; get_embedding_model(); print('Embedding model loaded')" > /home/youyeetoo/backend/data/kb_init.log 2>&1 &
echo "Embedding model preloading started"

echo "Starting backend on port 8000..."
cd /home/youyeetoo/backend
source /home/youyeetoo/rkllm_model_zoo/funasr_env/bin/activate
export LD_LIBRARY_PATH=/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm/lib:$LD_LIBRARY_PATH
export LLM_06B_SERVICE_URL=http://127.0.0.1:8003
export BACKEND_INTERNAL_SERVICE_TOKEN="${BACKEND_INTERNAL_SERVICE_TOKEN:-change-me-internal-service-token}"
nohup python run.py > /home/youyeetoo/backend/data/server.log 2>&1 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

echo "Waiting for backend to be ready before starting PI Agents..."
for i in $(seq 1 30); do
  if curl -sf --connect-timeout 3 http://127.0.0.1:8000/api/v1/health > /dev/null 2>&1; then
    echo "  Backend ready after ${i}x2=$((i*2))s"
    break
  fi
  sleep 2
done
if ! curl -sf --connect-timeout 3 http://127.0.0.1:8000/api/v1/health > /dev/null 2>&1; then
  echo "  WARNING: Backend not ready after 60s — starting PI Agents anyway..."
fi

echo "Starting PI Agents (chat-agent :18790 + doc-agent :18791)..."
export PATH="$HOME/.npm-global/bin:$PATH"
export PI_AGENT_TOKEN="${PI_AGENT_TOKEN:-pi-agent-local-token}"
export PI_AGENT_CHAT=1
export PI_AGENT_DOC=1
BACKEND_DIR="/home/youyeetoo/backend"
OPENCLAW_CONFIG_PATH="$BACKEND_DIR/.pi-agent/chat/openclaw.json" OPENCLAW_STATE_DIR="$BACKEND_DIR/.pi-agent/chat/state" nohup openclaw gateway --port 18790 --bind loopback \
  > /home/youyeetoo/backend/data/pi-agent-chat.log 2>&1 &
CHAT_AGENT_PID=$!
echo "  chat-agent PID: $CHAT_AGENT_PID"
echo "$CHAT_AGENT_PID" > /home/youyeetoo/backend/data/pi-agent-chat.pid
OPENCLAW_CONFIG_PATH="$BACKEND_DIR/.pi-agent/doc/openclaw.json" OPENCLAW_STATE_DIR="$BACKEND_DIR/.pi-agent/doc/state" nohup openclaw gateway --port 18791 --bind loopback \
  > /home/youyeetoo/backend/data/pi-agent-doc.log 2>&1 &
DOC_AGENT_PID=$!
echo "  doc-agent PID: $DOC_AGENT_PID"
echo "$DOC_AGENT_PID" > /home/youyeetoo/backend/data/pi-agent-doc.pid

echo "All services started!"
echo "  LLM Server:    http://0.0.0.0:8001"
echo "  Qwen3-0.6B Router:http://127.0.0.1:8002"
echo "  MiniCPM Vision: http://127.0.0.1:8003"
echo "  Backend:       http://0.0.0.0:8000"
echo "  PI Chat Agent: http://127.0.0.1:18790"
echo "  PI Doc Agent:  http://127.0.0.1:18791"
echo "  Piper TTS:     /home/youyeetoo/models/piper/zh_CN-huayan-medium.onnx"
echo "  Frontend:      http://0.0.0.0:3000"
