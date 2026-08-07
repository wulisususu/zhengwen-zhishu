#!/bin/bash



# ===========================================================================
# restart_backend.sh — INnet_agent 后端 + OpenClaw Agent 重启脚本
# 用法:
#   ./restart_backend.sh              → 重启后端 (8000)
#   ./restart_backend.sh --agent      → 重启 OpenClaw Agent (18790/18791)
#   ./restart_backend.sh --all        → 全部重启 (后端 + Agent)
#   ./restart_backend.sh --install    → 安装 systemd 开机自启
# ===========================================================================
set -euo pipefail

# API-triggered restarts inherit nohup's environment, which has no user DBus
# session. Always target the current Unix user's systemd user manager.
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=\${XDG_RUNTIME_DIR}/bus"

# ── 路径常量 ───────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/backend"
VENV_DIR="/home/youyeetoo/rkllm_model_zoo/funasr_env"
RKLLM_LIB="/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm/lib"
LOG_DIR="${BACKEND_DIR}/data"
OPENCLAW_BIN="/home/youyeetoo/.npm-global/bin/openclaw"
OPENCLAW_WORKDIR="/home/youyeetoo"

BACKEND_PORT=8000
CHAT_AGENT_PORT=18790
DOC_AGENT_PORT=18791
LLM_3B_PORT=8004
LLM_3B_MODEL="/home/youyeetoo/rkllm_model_zoo/Qwen2.5-3B-Instruct RKLLM/Qwen2.5-3B-Instruct.rkllm"
MINICPM_WORKDIR="/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm"

# ── 颜色 ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }

# ── 函数: 杀进程 ───────────────────────────────────────────────────────────
kill_port() {
    local port=$1 name=$2
    local pids=$(ss -tlnp 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K[0-9]+' | sort -u)
    if [ -z "$pids" ]; then
        warn "${name} (端口 ${port}) 未运行，跳过"
        return 0
    fi
    for pid in $pids; do
        log "停止 ${name} (PID: ${pid}, 端口: ${port})..."
        kill -TERM "$pid" 2>/dev/null || true
        # 等最多 10 秒
        for i in $(seq 1 10); do
            if ! kill -0 "$pid" 2>/dev/null; then
                log "${name} 已停止"
                break
            fi
            sleep 1
        done
        # 还没死就强杀
        if kill -0 "$pid" 2>/dev/null; then
            warn "强制终止 ${name} (PID: ${pid})"
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
}

# ── 函数: 清理缓存 ─────────────────────────────────────────────────────────
clean_pycache() {
    log "清理 Python __pycache__..."
    find "${BACKEND_DIR}" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    find "${BACKEND_DIR}" -name '*.pyc' -delete 2>/dev/null || true
    log "缓存已清理"
}

# ── 函数: 启动后端 ─────────────────────────────────────────────────────────
start_backend() {
    log "──────────────────────────────────────"
    log "启动 INnet_agent 后端 (端口 ${BACKEND_PORT})"
    log "──────────────────────────────────────"

    # Let systemd own production restarts; do not race Restart=always.
    if systemctl is-active --quiet innet_backend.service 2>/dev/null || systemctl is-enabled --quiet innet_backend.service 2>/dev/null; then
        info "检测到 innet_backend.service，交由 systemd 重启"
        systemctl restart innet_backend.service
        log "等待后端就绪..."
        for i in $(seq 1 30); do
            if curl -sf --connect-timeout 3 "http://127.0.0.1:${BACKEND_PORT}/api/v1/health" > /dev/null 2>&1; then
                log "✅ 后端已就绪 (systemd，耗时 ~$((i*2))s)"
                return 0
            fi
            sleep 2
        done
        err "systemd 后端启动超时，请检查: journalctl -u innet_backend"
        return 1
    fi

    # 确保日志目录存在
    mkdir -p "${LOG_DIR}"

    # 杀掉旧进程
    kill_port "${BACKEND_PORT}" "后端"

    # 清理缓存
    clean_pycache

    # 激活虚拟环境
    if [ ! -f "${VENV_DIR}/bin/activate" ]; then
        err "虚拟环境未找到: ${VENV_DIR}"
        exit 1
    fi
    source "${VENV_DIR}/bin/activate"
    info "虚拟环境: ${VENV_DIR}"

    # 环境变量
    export LD_LIBRARY_PATH="${RKLLM_LIB}:${LD_LIBRARY_PATH:-}"
    export LLM_06B_SERVICE_URL="${LLM_06B_SERVICE_URL:-http://127.0.0.1:8003}"
    export BACKEND_INTERNAL_SERVICE_TOKEN="${BACKEND_INTERNAL_SERVICE_TOKEN:-change-me-internal-service-token}"
    export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

    # 加载 .env
    if [ -f "${BACKEND_DIR}/.env" ]; then
        # 安全加载 .env (跳过无效 bash 变量名)
        while IFS=''= read -r env_key env_val; do
            if [[ "$env_key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
                export "$env_key=$env_val"
            fi
        done < "${BACKEND_DIR}/.env"
        info "已加载 .env"
    fi

    # 启动
    cd "${BACKEND_DIR}"
    nohup python scripts/run.py > "${LOG_DIR}/server.log" 2>&1 &
    BACKEND_PID=$!
    log "后端 PID: ${BACKEND_PID}"

    # 等待健康检查
    log "等待后端就绪..."
    for i in $(seq 1 30); do
        if curl -sf --connect-timeout 3 "http://127.0.0.1:${BACKEND_PORT}/api/v1/health" > /dev/null 2>&1; then
            log "✅ 后端已就绪 (耗时 ~$((i*2))s)"
            return 0
        fi
        sleep 2
    done

    err "后端启动超时，请检查日志: ${LOG_DIR}/server.log"
    return 1
}

# ── 函数: 重启 OpenClaw Agent ──────────────────────────────────────────────
restart_openclaw_agent() {
    log "──────────────────────────────────────"
    log "重启 OpenClaw Agent (18790/18791)"
    log "──────────────────────────────────────"

    info "使用 systemd user service 管理 Agent"

    # 停止现有服务
    systemctl --user stop openclaw-chat.service openclaw-doc.service 2>/dev/null || true
    sleep 1

    # 清除失败状态（避免因重试次数过多被 systemd 拒绝）
    systemctl --user reset-failed openclaw-chat.service openclaw-doc.service 2>/dev/null || true

    # 启动
    systemctl --user start openclaw-chat.service openclaw-doc.service
    if [ $? -ne 0 ]; then
        err "systemd 启动失败，查看 journalctl --user -u openclaw-chat -u openclaw-doc"
        return 1
    fi

    # 等待就绪
    log "等待 Agent 就绪..."
    for i in $(seq 1 30); do
        local chat_ok=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://127.0.0.1:${CHAT_AGENT_PORT}/health" 2>/dev/null || echo "000")
        local doc_ok=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://127.0.0.1:${DOC_AGENT_PORT}/health" 2>/dev/null || echo "000")
        if [ "$chat_ok" = "200" ] && [ "$doc_ok" = "200" ]; then
            log "✅ OpenClaw Agent 已就绪 (Chat: ${CHAT_AGENT_PORT}, Doc: ${DOC_AGENT_PORT})"
            return 0
        fi
        sleep 2
    done

    warn "Agent 启动超时，Chat=${chat_ok:-?}, Doc=${doc_ok:-?}"
    return 1
}
# ── 函数: 启动 3B RKLLM 模型 (8004) ───────────────────────────────────────
start_3b_model() {
    log "──────────────────────────────────────"
    log "启动 Qwen2.5-3B RKLLM 模型 (端口 ${LLM_3B_PORT})"
    log "──────────────────────────────────────"

    kill_port "${LLM_3B_PORT}" "3B RKLLM"

    if [ ! -f "${LLM_3B_MODEL}" ]; then
        err "3B 模型文件未找到: ${LLM_3B_MODEL}"
        return 1
    fi

    source "${VENV_DIR}/bin/activate"
    export LD_LIBRARY_PATH="${RKLLM_LIB}:${LD_LIBRARY_PATH:-}"

    cd "${BACKEND_DIR}"
    nohup python app/services/llm_server.py > "${LOG_DIR}/llm_3b_8004.log" 2>&1 &
    local PID=$!
    log "3B RKLLM PID: ${PID}"

    # 等模型加载 (RKLLM NPU 模型加载较慢)
    log "等待 3B 模型加载 (NPU, 约 2-5 分钟)..."
    for i in $(seq 1 90); do
        local status=$(curl -s --connect-timeout 3 "http://127.0.0.1:${LLM_3B_PORT}/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
        if [ "$status" = "ready" ]; then
            log "✅ 3B RKLLM 已就绪 (耗时 ~$((i*3))s)"
            return 0
        fi
        sleep 3
    done
    warn "3B 模型启动超时，请检查日志: ${LOG_DIR}/llm_3b_8004.log"
    return 1
}

# ── 函数: 安装 systemd 开机自启 ─────────────────────────────────────────────
install_systemd() {
    log "──────────────────────────────────────"
    log "安装 systemd 开机自启服务"
    log "──────────────────────────────────────"

    local SERVICE_NAME="innet_backend"
    local SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    local SERVICE_3B_NAME="innet_3b"
    local SERVICE_3B_FILE="/etc/systemd/system/${SERVICE_3B_NAME}.service"

    # ── 后端服务 ──
    sudo tee "${SERVICE_FILE}" > /dev/null << SYSTEMD_EOF
[Unit]
Description=INnet Agent Backend (8000)
After=network.target

[Service]
Type=simple
User=youyeetoo
WorkingDirectory=${BACKEND_DIR}
Environment="PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin"
Environment="VIRTUAL_ENV=${VENV_DIR}"
Environment="LD_LIBRARY_PATH=${RKLLM_LIB}"
Environment="LLM_06B_SERVICE_URL=http://127.0.0.1:8003"
Environment="BACKEND_INTERNAL_SERVICE_TOKEN=change-me-internal-service-token"
Environment="HF_ENDPOINT=https://hf-mirror.com"
ExecStart=${VENV_DIR}/bin/python ${BACKEND_DIR}/scripts/run.py
Restart=always
RestartSec=5
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF

    # ── 3B RKLLM 模型服务 ──
    sudo tee "${SERVICE_3B_FILE}" > /dev/null << SYSTEMD_EOF
[Unit]
Description=INnet Qwen2.5-3B RKLLM (8004)
After=network.target

[Service]
Type=simple
User=youyeetoo
WorkingDirectory=${BACKEND_DIR}
Environment="PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin"
Environment="VIRTUAL_ENV=${VENV_DIR}"
Environment="LD_LIBRARY_PATH=${RKLLM_LIB}"
ExecStart=${VENV_DIR}/bin/python ${BACKEND_DIR}/app/services/llm_server.py
Restart=always
RestartSec=10
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF

    log "已创建: ${SERVICE_FILE}"
    log "已创建: ${SERVICE_3B_FILE}"

    sudo systemctl daemon-reload
    log "systemd 已重新加载"

    sudo systemctl enable "${SERVICE_NAME}"
    sudo systemctl enable "${SERVICE_3B_NAME}"
    log "已启用开机自启: ${SERVICE_NAME} + ${SERVICE_3B_NAME}"

    # 显示状态说明
    echo ""
    info "════════════════════════════════════════════"
    info "  systemd 服务管理命令:"
    info "════════════════════════════════════════════"
    info "  后端:  sudo systemctl restart innet_backend"
    info "  3B模型: sudo systemctl restart innet_3b"
    info "  状态:  sudo systemctl status innet_backend innet_3b"
    info "  日志:  sudo journalctl -u innet_backend -f"
    info "  禁用:  sudo systemctl disable innet_backend innet_3b"
    info "════════════════════════════════════════════"
}

# ── 主入口 ─────────────────────────────────────────────────────────────────
main() {
    local mode="${1:---backend}"

    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   INnet_agent 后端管理脚本 v1.0          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
    echo ""

    case "${mode}" in
        --backend)
            start_backend
            ;;
        --agent)
            restart_openclaw_agent
            ;;
        --3b)
            start_3b_model
            ;;
        --all)
            start_backend
            echo ""
            start_3b_model
            echo ""
            restart_openclaw_agent
            ;;
        --install)
            install_systemd
            ;;
        --help|-h)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --backend     重启后端 API (端口 ${BACKEND_PORT})    [默认]"
            echo "  --agent       重启 OpenClaw Agent (端口 ${CHAT_AGENT_PORT}/${DOC_AGENT_PORT})"
            echo "  --3b          启动 Qwen2.5-3B RKLLM 模型 (端口 ${LLM_3B_PORT})"
            echo "  --all         全部重启 (后端 + 3B + Agent)"
            echo "  --install     安装 systemd 开机自启"
            echo "  --help        显示此帮助"
            ;;
        *)
            err "未知选项: ${mode}"
            echo "使用 --help 查看帮助"
            exit 1
            ;;
    esac

    echo ""
    log "════════════════════════════════════════════"
    log "  完成! 当前服务状态:"
    log "════════════════════════════════════════════"
    echo ""
    echo "  端口        服务                     状态"
    echo "  ────────   ──────────────────────    ──────────"
    for entry in \
        "${BACKEND_PORT}:后端 API" \
        "${CHAT_AGENT_PORT}:OpenClaw Chat Agent" \
        "${DOC_AGENT_PORT}:OpenClaw Doc Agent" \
        "8004:Qwen2.5-3B RKLLM" \
        "8003:MiniCPM Vision (冷启动)" \
        "8002:Qwen3-0.6B LLM" \
        "3000:前端 (Vite)"; do
        port="${entry%%:*}"
        label="${entry##*:}"
        if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
            printf "  %-8s   %-25s ${GREEN}● 运行中${NC}\n" "${port}" "${label}"
        else
            printf "  %-8s   %-25s ${RED}○ 未运行${NC}\n" "${port}" "${label}"
        fi
    done
    echo ""
}

main "$@"
