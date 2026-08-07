#!/bin/bash
# PI Agent 启动脚本 — chat-agent :18790 + doc-agent :18791 + children-medical :18792
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
PI_AGENT_DIR="$BACKEND_DIR/.pi-agent"

export PATH="$HOME/.npm-global/bin:$PATH"

# 环境变量
export PI_AGENT_TOKEN="${PI_AGENT_TOKEN:-pi-agent-local-token}"

# 日志目录
LOG_DIR="$BACKEND_DIR/data"
mkdir -p "$LOG_DIR"

echo "=== Starting PI Agents ==="

# 先停掉旧进程
fuser -k 18790/tcp 2>/dev/null || true
fuser -k 18791/tcp 2>/dev/null || true
fuser -k 18792/tcp 2>/dev/null || true
fuser -k 8099/tcp 2>/dev/null || true
sleep 1

# 启动 chat-agent (:18790)
echo "Starting chat-agent on :18790 ..."
OPENCLAW_CONFIG_PATH="$PI_AGENT_DIR/chat/openclaw.json" OPENCLAW_STATE_DIR="$PI_AGENT_DIR/chat/state" nohup openclaw gateway --port 18790 --bind loopback > "$LOG_DIR/pi-agent-chat.log" 2>&1 &
CHAT_PID=$!
echo "chat-agent PID: $CHAT_PID"

# 启动 doc-agent (:18791)
echo "Starting doc-agent on :18791 ..."
OPENCLAW_CONFIG_PATH="$PI_AGENT_DIR/doc/openclaw.json" OPENCLAW_STATE_DIR="$PI_AGENT_DIR/doc/state" nohup openclaw gateway --port 18791 --bind loopback > "$LOG_DIR/pi-agent-doc.log" 2>&1 &
DOC_PID=$!
echo "doc-agent PID: $DOC_PID"

# 启动 children-medical (:18792)
echo "Starting children-medical on :18792 ..."
OPENCLAW_CONFIG_PATH="$PI_AGENT_DIR/children_medical/openclaw.json" OPENCLAW_STATE_DIR="$PI_AGENT_DIR/children_medical/state" nohup openclaw gateway --port 18792 --bind loopback > "$LOG_DIR/pi-agent-children-medical.log" 2>&1 &
MED_PID=$!
echo "children-medical PID: $MED_PID"

# 保存 PID
echo "$CHAT_PID" > "$LOG_DIR/pi-agent-chat.pid"
echo "$DOC_PID" > "$LOG_DIR/pi-agent-doc.pid"
echo "$MED_PID" > "$LOG_DIR/pi-agent-children-medical.pid"


# 启动 PCW (:8099) — Python Chat Workflow 降级服务
echo "Starting PCW on :8099 ..."
cd "$BACKEND_DIR"
source /home/youyeetoo/rkllm_model_zoo/funasr_env/bin/activate
nohup python python_chat_workflow.py > "$LOG_DIR/pcw.log" 2>&1 &
PCW_PID=$!
echo "pcw PID: $PCW_PID"
echo "$PCW_PID" > "$LOG_DIR/pi-agent-pcw.pid"


echo "=== PI Agents started ==="
echo "chat-agent:         http://127.0.0.1:18790 (PID $CHAT_PID)"
echo "doc-agent:          http://127.0.0.1:18791 (PID $DOC_PID)"
echo "children-medical:   http://127.0.0.1:18792 (PID $MED_PID)"
