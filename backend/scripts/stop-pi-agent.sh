#!/bin/bash
# PI Agent 停止脚本
set -e

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$BACKEND_DIR/data"

echo "=== Stopping PI Agents ==="

for AGENT in chat doc; do
  PID_FILE="$LOG_DIR/pi-agent-$AGENT.pid"
  if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
      echo "Stopping $AGENT-agent (PID $PID)..."
      kill "$PID" 2>/dev/null || true
      sleep 1
      kill -9 "$PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  fi
done

# 确保端口释放
fuser -k 18790/tcp 2>/dev/null || true
fuser -k 18791/tcp 2>/dev/null || true

echo "=== PI Agents stopped ==="
