#!/bin/bash
# 启动后健康自检 — 由 start_all.sh 末尾调用
set -e
echo ""
echo "=== 系统启动健康自检 ==="
sleep 5
HEALTH_RESP=$(curl -s -X POST http://127.0.0.1:8000/api/v1/health/detailed 2>/dev/null)
if [ -n "$HEALTH_RESP" ]; then
  VERDICT=$(echo "$HEALTH_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['verdict'])" 2>/dev/null)
  echo "  自检结果: $VERDICT"
  echo "$HEALTH_RESP" | python3 -m json.tool 2>/dev/null | head -30
else
  echo "  WARNING: 健康检查端点无响应"
fi
echo "=== 自检结束 ==="
