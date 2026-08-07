# InNet_box — 端侧 AI 智能体平台

> 部署硬件：RK3588 开发板 | 操作系统：Linux (Ubuntu/Debian) | 目标 IP：192.168.0.117

---

## 目录

- [1. 系统概述](#1-系统概述)
- [2. 整体架构](#2-整体架构)
- [3. 目录结构](#3-目录结构)
- [4. 后端 (backend)](#4-后端-backend)
  - [4.1 技术栈](#41-技术栈)
  - [4.2 配置文件](#42-配置文件)
  - [4.3 子模块](#43-子模块)
  - [4.4 服务依赖](#44-服务依赖)
- [5. 前端 (web)](#5-前端-web)
  - [5.1 技术栈](#51-技术栈)
  - [5.2 关键文件](#52-关键文件)
  - [5.3 代理配置](#53-代理配置)
  - [5.4 环境变量](#54-环境变量)
- [6. 服务端口映射](#6-服务端口映射)
- [7. 启动指南](#7-启动指南)
  - [7.1 全链路启动](#71-全链路启动)
  - [7.2 分步启动](#72-分步启动)
  - [7.3 验证服务状态](#73-验证服务状态)
- [8. 运维与调试](#8-运维与调试)
  - [8.1 日志](#81-日志)
  - [8.2 常用命令](#82-常用命令)
  - [8.3 systemd 服务](#83-systemd-服务)
  - [8.4 性能与资源管理](#84-性能与资源管理)
- [9. 聊天链路与降级策略](#9-聊天链路与降级策略)
  - [9.1 聊天全路径](#91-聊天全路径)
  - [9.2 双路径降级机制](#92-双路径降级机制)
  - [9.3 OpenClaw 配置详情](#93-openclaw-配置详情)
  - [9.4 35B 不可达场景分析](#94-35b-不可达场景分析)
- [10. 已知问题与限制](#10-已知问题与限制)
  - [10.1 35B 外部模型不可达 (关键)](#101-35b-外部模型不可达-关键)
  - [10.2 start_all.sh 因 `set -u` 提前退出](#102-start_allsh-因-set--u-提前退出)
  - [10.3 MiniCPM 依赖修复历史](#103-minicpm-依赖修复历史)
  - [10.4 前端开发模式依赖代理](#104-前端开发模式依赖代理)
  - [10.5 符号链接兼容](#105-符号链接兼容)
  - [10.6 30s 无反馈等待 (关键)](#106-30s-无反馈等待-关键)

---

## 1. 系统概述

InNet_box 是一个部署在 RK3588 端侧设备上的 AI 智能体平台，提供 **对话 (Chat)**、**文档生成 (Document Generation)**、**PPT 生成**、**知识库检索**、**语音输入/润色** 等能力。前后端分离，后端集成多路本地模型推理和云端大模型兜底。

---

## 2. 整体架构

```
┌───────────────────────────────────────────────────────────────┐
│                        浏览器 (用户)                            │
│             http://192.168.0.11:3000                          │
└──────────────────────┬────────────────────────────────────────┘
                       │ /api/* (Vite 开发代理)
                       ▼
┌──────────────────────────────────────────────┐
│          前端 — Vue 3 + Vite :3000            │
│  · Chat / 文档 / PPT / 知识库 / 语音         │
│  · axios(baseURL: /api/v1)                   │
│  · 代理: /api → localhost:8000               │
│        /api/v1/docs-pipeline → localhost:8003 │
└──────────────────────┬────────────────────────┘
                       │ POST /api/v1/conversations/{id}/messages
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│            后端 — FastAPI :8000                                   │
│  · `conversations.py` → `chat_with_degradation()`                │
│  · 其他路由: ASR/TTS/知识库/PPT/文档                              │
│  · 健康检查 GET /api/v1/health                                   │
└───────────────┬──────────────────────────────────────────────────┘
                │ PI_AGENT_CHAT=1
                ▼
┌──────────────────────────────────────────────────────────────────┐
│                ↓ ↓ ↓  聊天降级双路径  ↓ ↓ ↓                       │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Path 1: OpenClaw Chat Agent (:18790) — 30s 超时             │  │
│  │                                                              │  │
│  │  health_check → ✅ → _stream_pi_chat()                       │  │
│  │    → call_chat_agent() → 18790 /v1/responses                │  │
│  │    → OpenClaw 内部模型降级:                                  │  │
│  │      ├─ primary: 35B (192.168.10.212:8081)  ❌ 不可达        │  │
│  │      └─ fallback: 0.6B (127.0.0.1:8088)     ⏸️ paused        │  │
│  │    → 30s 无首 token → asyncio.TimeoutError → 触发降级        │  │
│  └──────────────┬─────────────────────────────────────────────┘  │
│                 │ 30s 超时                                        │
│                 ▼                                                │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Path 2: Direct Local Model (bypass OpenClaw)               │  │
│  │                                                              │  │
│  │  _local_small_generate(content, max_tokens=512)             │  │
│  │    → POST http://127.0.0.1:8002/v1/chat/completions        │  │
│  │    → 裸 prompt, 无 system prompt / tools 上下文              │  │
│  │    → 0.6B 模型 (8002) 直接回复, context 不溢出               │  │
│  │    → 最终 fallback: "AI 服务暂不可用"                          │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘

本地模型服务:
:5101           :8002           :8003           :8088              :18790 / :18791
MeloTTS        Qwen3-0.6B      MiniCPM         Qwen2.5-1.5B       OpenClaw Agent
语音合成       llama-server    视觉文档          RKLLM (paused)     网关 (systemd)
(CPU)          (CPU 运行)                                                      primary: 35B
                                                                               fallback: 0.6B-8088

外部 35B: 192.168.10.212:8081 ❌ 不可达 (无 10 网段)
```

### 网络拓扑说明

| 网段 | 说明 |
|------|------|
| 192.168.0.0/24 | 本机所在局域网 (192.168.0.11) |
| 192.168.10.0/24 | 原 35B 大模型所在网段 **当前不可达** |

---

## 3. 目录结构

```
/home/youyeetoo/InNet_box/
├── README.md               # 项目说明（本文件）
├── .gitignore              # Git 忽略规则
├── restart_backend.sh      # 后端 + OpenClaw Agent 统一管理脚本
│
├── backend/                # 后端 (FastAPI + Uvicorn)
│   ├── app/                #   - 主应用代码
│   │   ├── PPT_master/     #     * PPT 生成技能
│   │   ├── docs_pipeline/  #     * 文档生成管线
│   │   ├── kb/             #     * 知识库 (Embedding / 向量检索)
│   │   ├── services/       #     * 服务 (LLM / MiniCPM 视觉 / 文档)
│   │   │   └── pi_agent_client/
│   │   │       └── degradation.py  ← 聊天降级核心逻辑
│   │   └── ...其他模块
│   ├── scripts/            #   - 运维脚本 (启停 / 健康检查 / 修复补丁)
│   │   ├── run.py          #     * 后端入口 (systemd ExecStart 指向)
│   │   ├── start_all.sh    #     * 一键启动
│   │   ├── start_clean.sh  #     * 干净启动
│   │   ├── start_llm.sh    #     * 单独启动 LLM
│   │   ├── run_pipeline.py #     * 独立文档管线服务 (:8003)
│   │   ├── standalone_docs_pipeline.py  # * 独立管道服务
│   │   ├── python_chat_workflow.py      # * PCW 工作流 (:8099)
│   │   └── fixes/          #     * 历史修复补丁
│   ├── docs/               #   - 设计文档 / 报告 / 验收证据
│   ├── tests/              #   - 后端测试
│   ├── config.example.yaml #   - 配置示例 (部署时复制为 config.yaml)
│   ├── .env.example        #   - 环境变量示例 (部署时复制为 .env)
│   ├── requirements.txt    #   - Python 依赖
│   └── .pi-agent/          #   - PI Agent 配置 (chat / doc / children_medical)
│       └── chat/
│           └── openclaw.json  ← OpenClaw 模型路由配置
│
└── web/                    # 前端 (Vue 3 + Vite)
    ├── src/                #   - 源码
    │   ├── components/     #     * 组件 (ChatMode / DocumentMode / ComposerBar …)
    │   ├── views/          #     * 页面 (LoginPage / PptHostPage …)
    │   ├── stores/         #     * Pinia 状态管理
    │   ├── features/       #     * 功能模块 (PPT workbench)
    │   └── api.js          #     * axios 客户端 (baseURL: /api/v1)
    ├── public/             #   - 静态资源
    ├── docs/               #   - 文档 / 报告
    ├── tests/              #   - 前端测试
    ├── deployment/         #   - systemd 服务文件
    ├── vite.config.js      #   - Vite 配置 (host/port/proxy)
    ├── package.json        #   - npm 依赖与脚本
    ├── index.html          #   - HTML 入口
    └── start.sh            #   - 前端启动脚本
```

> 说明：`data/`、`service_logs/`、`release/` 等运行时/发布产物目录已从仓库中移除，部署时由启动脚本自动创建或按需生成。
---

## 4. 后端 (backend)

### 4.1 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI (Python 3) |
| 运行方式 | Uvicorn (单 worker) |
| 数据库 | SQLite (`data/app.db`) |
| HTTP 客户端 | requests |
| 文档解析 | mammoth / python-docx / PyMuPDF |
| 配置格式 | YAML |

### 4.2 配置文件

**`config.yaml`** (实际位置 `~/.config/ai-box/backend/config.yaml`):

```yaml
server:                 # 服务绑定
  host: 0.0.0.0
  port: 8000
database:               # 数据库 (SQLite)
  url: sqlite:///data/app.db
jwt:                    # JWT 鉴权
  secret: <secret>
  algorithm: HS256
  expire_minutes: 1440
asr:                    # 语音识别
  model_dir: /home/youyeetoo/rkllm_model_zoo/mqw-tools/paraformer_onnx
llm:                    # 大模型配置
  prompt_model_url: http://127.0.0.1:8088
  local_small_model_api_url: http://127.0.0.1:8088/v1/chat/completions
  local_small_model_name: Qwen3-0.6B-Q4_K_M.gguf
  ollama_base_url: http://192.168.10.212:8081/v1   # ← 35B (10网段不可达)
  cloud_base_url: https://dashscope.aliyuncs.com/compatible-mode  # 云端兜底
  cloud_model: qwen-plus
knowledge:              # 知识库
  enabled: true
openclaw:               # OpenClaw 智能体网关
  enabled: true
  gateway_base_url: http://127.0.0.1:18789
  gateway_token: <token>
  document_model: openclaw/docgen        # 文档生成 Agent
  chat_model: openclaw/default           # 对话 Agent
  pediatric_medical_qa_model: openclaw/children-qa  # 儿童医疗问答
  knowledge_model: openclaw/default      # 知识库 Agent
  voice_input_model: openclaw/voice-input # 语音输入 Agent
polish:                 # 语音润色
  api_url: http://127.0.0.1:8088/v1/chat/completions
python_chat_workflow:   # PCW 工作流 (已关闭)
  enabled: false
feature_flags:          # 功能开关
  show_ppt: true
  show_table: false
  show_agents: true
```

**`.env`** (实际位置 `~/.config/ai-box/backend/.env`):

```
DESKTOP_INTERNAL_TOKEN=...
OPENCLAW_GATEWAY_TOKEN=...
PI_AGENT_TOKEN=...
PI_AGENT_CHAT=1
PI_AGENT_DOC=1
```

### 4.3 子模块

| 模块路径 | 功能 |
|----------|------|
| `app/main.py` | FastAPI 应用入口、路由注册 |
| `app/services/llm_server.py` | RKLLM 本地推理服务 (:8001) |
| `app/services/minicpm_vision_service.py` | MiniCPM 视觉文档服务 (:8003) |
| `app/services/pi_agent_client/degradation.py` | **聊天降级核心**: 30s PI Agent → direct local model |
| `app/services/pi_agent_client/chat_client.py` | OpenClaw Chat Agent 客户端 |
| `app/services/pi_agent_client/doc_client.py` | OpenClaw Doc Agent 客户端 |
| `app/services/llm_client.py` | LLM 客户端 - 含 `_local_small_generate()` 直调本地模型 |
| `app/kb/` | 知识库 (Embedding 模型预加载 / 向量检索) |
| `app/PPT_master/` | PPT 生成 (模板匹配 / SVG 编辑 / 版式渲染) |
| `app/docs_pipeline/` | 文档生成管线 (Markdown → 格式文档) |
| `.pi-agent/chat/` | PI Agent Chat 配置 (OpenClaw + 模型路由) |
| `.pi-agent/doc/` | PI Agent Doc 配置 (OpenClaw) |
| `.openclaw/` | OpenClaw 核心配置 (backup 插件 / 自定义 backend) |

### 4.4 服务依赖

```
后端 :8000
 ├── :8002 (Qwen3-0.6B llama.cpp, Path 2 直接调用)
 ├── :5101 (MeloTTS 语音合成, CPU, 独立服务)
 ├── :8003 (MiniCPM Visual, 文档视觉解析)
 ├── :8088 (Qwen2.5-1.5B RKLLM, paused)
 ├── :18790 (OpenClaw Chat Agent, Path 1 入口)
 ├── :18791 (OpenClaw Doc Agent)
 └── 可选 :8081 (35B 外部模型, 当前不可达)
```

> 注意：PCW (`:8099`) 已关闭,`python_chat_workflow.enabled=false`。聊天仅走 degradation.py 定义的双路径。

---

## 5. 前端 (web)

### 5.1 技术栈

| 组件 | 技术 |
|------|------|
| 框架 | Vue 3 (Composition API) |
| 构建工具 | Vite 5 |
| 路由 | vue-router |
| 状态管理 | Pinia |
| HTTP | axios (baseURL: `/api/v1`) |
| 样式 | TailwindCSS |
| PPT 工作台 | Vue 组件 + 适配器模式 |

### 5.2 关键文件

| 文件 | 功能 |
|------|------|
| `vite.config.js` | Vite 配置 (开发服务器 host/port/proxy) |
| `src/api.js` | axios 实例 (`baseURL: '/api/v1'`) |
| `src/components/ChatMode.vue` | 对话界面 (含 SSE 流解析) |
| `src/components/DocumentMode.vue` | 文档生成界面 |
| `src/views/PptHostPage.vue` | PPT 工作台宿主页 |
| `src/views/KnowledgeFileSearchView.vue` | 知识库文件搜索 |
| `src/views/LoginPage.vue` | 登录页 |
| `src/components/ComposerBar.vue` | 底部输入栏 |
| `src/stores/chat.js` | 对话状态 (Pinia) |
| `src/features/ppt-workbench/` | PPT 工作台适配器 (支持 Legacy / Mock 模式) |

### 5.3 代理配置 (`vite.config.js`)

```javascript
server: {
  host: '0.0.0.0',      // 绑定所有网卡, 局域网可访问
  port: 3000,
  proxy: {
    '/api/v1/docs-pipeline': {
      target: 'http://localhost:8003',  // → MiniCPM Visual
      changeOrigin: true,
    },
    '/api': {
      target: 'http://localhost:8000',  // → 后端 FastAPI
      changeOrigin: true,
    },
  },
}
```

> ⚠️ **重要**:Vite 代理仅在 **dev 模式** (`npm run dev`) 下生效。若使用 `vite preview` 或直接提供 `dist/` 静态文件, `/api` 请求将因缺少代理而 404。生产部署需要在前端加一层反向代理 (如 nginx)。

### 5.4 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VITE_PPT_MASTER_BASE_URL` | PPT 生成服务基 URL (覆盖同源代理) | `window.location.origin` |
| `VITE_PPT_MASTER_PAGE_COUNT` | PPT 默认页数 | `8` |

`src/features/ppt-workbench/adapters/LegacyPptMasterAdapter.ts` 中后端保底地址为 `http://192.168.0.11:8000`。

---

## 6. 服务端口映射

| 端口 | 服务名 | 绑定地址 | 当前状态 | 说明 |
|------|--------|----------|----------|------|
| **3000** | 前端 Vite Dev Server | 0.0.0.0 | ✅ 运行 | HTTP 200, 前端入口 |
| **8000** | 后端 FastAPI | 0.0.0.0 | ✅ 运行 | 主 API, 健康检查通过 |
| **5101** | MeloTTS 语音合成 | 127.0.0.1 | ✅ 运行 | 独立 TTS 服务, CPU 推理 |
| **8002** | Qwen3-0.6B Router (llama-server) | 127.0.0.1 | ✅ 运行 | CPU 运行, Path 2 直调目标 |
| **8003** | MiniCPM Visual 文档视觉 | 127.0.0.1 | ✅ 运行 | 文档 OCR / 图片理解 |
| **8088** | Qwen2.5-1.5B RKLLM (NPU) | 0.0.0.0 | ⏸️ Paused | 暂停以释放 NPU 给 8003 |
| **8099** | PCW Python Chat Workflow | — | ❌ 已停 | `python_chat_workflow.enabled=false` |
| **18790** | OpenClaw Chat Agent | 127.0.0.1 | ✅ Live | Path 1 入口 (systemd user) |
| **18791** | OpenClaw Doc Agent | 127.0.0.1 | ✅ Live | 文档智能体 (systemd user) |
| **18081** | 旧平台 Legacy (ks_web_backend) | 0.0.0.0 | ✅ 运行 | 独立项目, 未改动 |

> 8088 的 `paused` 状态是设计行为 — 1.5B 模型在 RK3588 NPU 上会与 MiniCPM 8003 竞争 NPU 资源,因此通过 `/admin/pause` 暂停释放。需要时可通过 `/admin/resume` 恢复。

---

## 7. 启动指南

### 7.1 全链路启动

一键启动 (后端全家桶 + 模型 + PI Agent):

```bash
cd /home/youyeetoo/InNet_box/backend
bash scripts/start_all.sh
```

启动前端 (开发模式):

```bash
cd /home/youyeetoo/InNet_box/web
npm run dev
```

> 注意：`start_all.sh` 包含 `set -u`,若 `LD_LIBRARY_PATH` 未定义会提前退出。参见 [10.2](#102-start_allsh-因-set--u-提前退出)。

### 7.2 分步启动

若 `start_all.sh` 失败,可按以下顺序分别启动:

| 步骤 | 命令 | 服务 |
|------|------|------|
| 1 | `cd /home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm` <br> `export LD_LIBRARY_PATH=./lib:$LD_LIBRARY_PATH` <br> `nohup .venv/bin/python3 /home/youyeetoo/InNet_box/backend/app/services/llm_server.py > /home/youyeetoo/InNet_box/backend/data/llm_server.log 2>&1 &` | RKLLM 8001 (可选, 当前用 8088) |
| 2 | `cd /home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm` <br> `export MINICPM_SERVICE_PORT=8003` <br> `nohup .venv/bin/python3 /home/youyeetoo/InNet_box/backend/app/services/minicpm_vision_service.py 8003 > ... &` | MiniCPM 8003 |
| 3 | `cd /home/youyeetoo/InNet_box/backend` <br> `source /home/youyeetoo/rkllm_model_zoo/funasr_env/bin/activate` <br> `export LD_LIBRARY_PATH=...` <br> `export BACKEND_INTERNAL_SERVICE_TOKEN=change-me-internal-service-token` <br> `nohup python scripts/run.py > ... &` | 后端 FastAPI 8000 |
| 4 | `systemctl --user restart openclaw-chat.service` | Chat Agent 18790 |
| 5 | `systemctl --user restart openclaw-doc.service` | Doc Agent 18791 |
| 6 | `cd /home/youyeetoo/InNet_box/web && npm run dev` | 前端 3000 |

### 7.3 验证服务状态

```bash
# 查看所有端口监听
ss -ltnp | grep -E ':3000|:8000|:8002|:8003|:8088|:18790|:18791'

# 逐一健康检查
curl -s http://127.0.0.1:8000/api/v1/health       # 后端
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/  # 前端 (应为 200)
curl -s http://127.0.0.1:8002/health               # Qwen3-0.6B Router
curl -s http://127.0.0.1:8003/health               # MiniCPM Visual
curl -s http://127.0.0.1:8088/health               # 1.5B RKLLM (paused 正常)
curl -s http://127.0.0.1:18790/health              # Chat Agent
curl -s http://127.0.0.1:18791/health              # Doc Agent
```

---

## 8. 运维与调试

### 8.1 日志

所有服务日志统一存放于部署机的 `service_logs/`（运行时生成，不在仓库内）:

| 日志文件 | 对应服务 |
|----------|----------|
| `backend_8000.log` | 后端 FastAPI |
| `frontend_3000.log` | 前端 Vite Dev Server |
| `qwen3_0_6b_8002.log` | Qwen3-0.6B Router |
| `minicpm_visual_8003.log` | MiniCPM Visual |
| `qwen_1_5b_8088.log` | 1.5B RKLLM |
| `start_all_*.log` | 启动日志 |

实时查看:

```bash
tail -f /home/youyeetoo/InNet_box/service_logs/backend_8000.log
tail -f /home/youyeetoo/InNet_box/service_logs/frontend_3000.log
```

### 8.2 常用命令

```bash
# 查看服务状态 (一目了然)
ss -ltnp | grep -E ':3000|:8000|:8002|:8003|:8088|:18790|:18791|:18081'

# 查看 OpenClaw 智能体状态
systemctl --user status openclaw-chat.service openclaw-doc.service --no-pager -l

# 重启后端
lsof -ti tcp:8000 | xargs kill
cd /home/youyeetoo/InNet_box/backend && source funasr_env/bin/activate && python scripts/run.py &

# 重启 OpenClaw Agent
systemctl --user restart openclaw-chat.service
systemctl --user restart openclaw-doc.service

# 暂停/恢复 1.5B RKLLM (NPU 释放/占用)
curl -X POST http://127.0.0.1:8088/admin/pause
curl -X POST http://127.0.0.1:8088/admin/resume

# 查看 OpenClaw 日志
journalctl --user -u openclaw-chat.service --no-pager -n 50
journalctl --user -u openclaw-doc.service --no-pager -n 50

# 测试聊天全路径 (用 Internal Token)
TOKEN="change-me-internal-service-token"
curl -s -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"你好"}'

# 查看磁盘/内存 (RK3588 资源有限)
df -h
free -h
```

### 8.3 systemd 服务

OpenClaw Chat / Doc Agent 使用 **user-level systemd 服务**:

```
~/.config/systemd/user/openclaw-chat.service
~/.config/systemd/user/openclaw-doc.service
```

管理方式:

```bash
systemctl --user start   openclaw-chat.service   # 启动
systemctl --user stop    openclaw-chat.service   # 停止
systemctl --user restart openclaw-chat.service   # 重启
systemctl --user enable  openclaw-chat.service   # 开机自启
```

> 后端 FastAPI 和前端 Vite 当前以 nohup 方式运行,未注册 systemd 服务。若需开机自启,建议为其创建 systemd service 或使用 supervisor。

### 8.4 性能与资源管理

RK3588 是 ARM 端侧芯片,资源有限(NPU/内存):

- **NPU 竞争**:MiniCPM (8003) 和 RKLLM (8088) 共享 NPU,同时运行可能互相拖慢。当前方案是 8088 默认 pause,8003 稳定后再 resume。
- **Qwen3-0.6B (8002)** 运行在 CPU (llama.cpp GGUF),不占用 NPU,独立运行。
- **35B 外部模型**(192.168.10.212:8081)若可访问,可大幅提升复杂文档/PPT 的生成质量,但 10 网段目前不可达,系统已自动降级为本地 0.6B 模型。
### 8.5 TTS 语音合成服务

TTS 使用独立的 **MeloTTS 服务**（:5101），替代旧版 Piper TTS：

| 项目 | 说明 |
|------|------|
| 服务地址 | http://127.0.0.1:5101（独立 FastAPI 进程，CPU 推理） |
| 调用方式 | 后端 tts_service.py -> POST /tts 获取 audio_url -> GET /audio/{id} 拿 WAV |
| 后端接入 | POST /api/v1/tts/synthesize（JWT 鉴权） |
| 模型 | MeloTTS-Chinese（中文+英文混合，约 1.9GB） |
| 统一 venv | funasr_env（`/home/youyeetoo/rkllm_model_zoo/funasr_env`，由启动脚本引用） |
| 启动 | bash /home/youyeetoo/rkllm_model_zoo/melo_tts/start_melo_tts.sh |
| 验证 | curl -s http://127.0.0.1:5101/health -> {"state":"ready"} |

---

## 9. 聊天链路与降级策略

### 9.1 聊天全路径

```
浏览器发消息 POST /api/v1/conversations/{id}/messages
  → 前端 Vite 代理 → 后端 :8000
  → conversations.py send_message()
    → _use_pi_agent_chat() = True (PI_AGENT_CHAT=1)
    → workflow_type == "chat"
    → _pi_chat_sse_gen()  ← 内层生成器
      ├─ 等待图片解析 (如有附件) — 最多 60s
      └─ chat_with_degradation()  ← 降级入口
```

### 9.2 双路径降级机制

`degradation.py` → `chat_with_degradation()` 两条路径：

```
Path 1: PI Agent (OpenClaw 18790) ──────────────────────
  触发:  health_check(18790) 通过
  调用:  _stream_pi_chat() → OpenClaw /v1/responses
          → openclaw/chat agent
  超时:  10s 首 token (asyncio.wait_for, 5s × 2 次)
  心跳:  status:thinking "模型正在思考…" (5s 时)
  结果:  10s 内无 token → 触发 Path 2
  说明:  OpenClaw system prompt + tools 过大, 0.6B (4096 ctx) 撑不住
         35B 恢复后此路径正常 (< 3s 出首 token)

Path 2: 直连本地模型 (8002) ────────────────────────────
  触发:  Path 1 超时 / Agent 不可用
  调用:  _local_small_generate(content, max_tokens=512)
          → POST http://127.0.0.1:8002/v1/chat/completions
          → Qwen3-0.6B llama-server (CPU)
  Prompt: system: "你是AI聊天小助手，中科信创自研轻量模型。…" (~150 tokens)
          user: 用户原始消息 (≤1500 chars)
  配置:  config.yaml → llm.local_small_system_prompt
  结果:  0.3-0.5s 内返回, context 不溢出
  保底:  若也失败 → "AI 服务暂时不可用"

总体时序 (35B 不可达时):
  user → message_start → [thinking @5s] → [10s 超时]
  → status:degraded → token → done → [DONE]
  总耗时: ~11s (10s Path 1 超时 + 0.5s 本地模型)
```

### 9.3 图片附件等待机制

```
上传图片 → parse_task 后台创建 → MiniCPM OCR 异步执行
  ↓ 用户立即发消息
_pi_chat_sse_gen()
  ├─ attachment_bundle.pending 非空?
  │   ├─ YES → yield status:analyzing_image "正在分析图片内容…"
  │   │         每 2s poll get_attachment_bundle(include_visual=True)
  │   │         每 10s yield status:processing_ocr "(Ns)" 心跳
  │   │         最多等 60s
  │   │         完成后 → yield status:image_analyzed "图片分析完成: …"
  │   │         attachment_context = MiniCPM 视觉描述
  │   └─ NO  → 跳过
  └─ chat_with_degradation(attachment_context=<实际内容>)
```

### 9.4 SSE 心跳事件

| 节点 | 触发条件 | 事件 | 间隔 |
|------|---------|------|------|
| Path 1 等待首 token | 5s 无响应 | `status:thinking` | 单次 |
| MiniCPM OCR 等待 | 图片解析中 | `status:processing_ocr` | 每 10s |
| Doc 文档生成 | Agent 生成内容中 | `status:generating` | 每 10s |

所有心跳事件格式: `{type: "status", stage: "<stage>", message: "<描述>"}`

### 9.5 OpenClaw 配置

配置文件: `backend/.pi-agent/chat/openclaw.config.ts` / `doc/openclaw.config.ts`

```ts
providers: {
  openaiCompatible: {
    baseUrl: 'http://127.0.0.1:8002/v1',          // 当前唯一可用模型
    model: 'Qwen3-0.6B-Q4_K_M.gguf',
  },
}
```

> 注: 原配置含 35B primary (192.168.10.212:8081) 和 8088 fallback，
> 已于 2026-07-20 全部迁移到 8002 端口。历史备份由 git 历史承载。

### 9.6 模型端口清理 (2026-07-20)

| 端口 | 旧用途 | 当前状态 |
|------|--------|---------|
| 8088 | Qwen2.5-1.5B / qwen_api_server | ❌ 已禁用 (qwen_api_server.py.disabled) |
| 8002 | llama-server Qwen3-0.6B | ✅ 唯一模型端口 |
| 8003 | MiniCPM Vision | ✅ OCR 视觉服务 |
| 18790 | OpenClaw Chat Agent | ✅ (provider 指向 8002) |
| 18791 | OpenClaw Doc Agent | ✅ (provider 指向 8002) |

DeepSeek 1.5B RKLLM 本地 NPU 模型已注释 (llm_server.py / llm_service.py / llm_runner.py)。

---

## 10. 已知问题与限制

### 10.1 35B 外部模型不可达 (关键)

- **问题**: 35B 模型在 192.168.10.212:8081，本机 (192.168.0.11) 不在 10 网段。
- **影响**: Path 1 (OpenClaw) 必然超时 10s → 降级到 Path 2 本地 0.6B。
- **当前方案**: Path 2 直连 8002，0.5s 响应。35B 恢复后 Path 1 自动生效。

### 10.2 端口 8088 完全移除

- 原 qwen_api_server.py (8088) 已禁用 (.disabled)，全部 8088 引用已迁移到 8002。
- 涉及 12 个文件的修改，历史版本见 git 历史。

### 10.3 MiniCPM 依赖修复历史

- 本机 MiniCPM venv 缺少 opencv (cv2)，已通过 `apt install python3-opencv` + 软连接解决。

### 10.4 前端开发模式依赖代理

- 前端 `npm run dev` 模式依赖 Vite 代理 (`/api` → `localhost:8000`)。
- 若需生产部署，应在 nginx 中配置反向代理。

### 10.5 路径说明

- 本仓库所有脚本/配置中的路径已统一为 `/home/youyeetoo/InNet_box`，不再依赖符号链接。
- 部署到新机器时，如需更换部署目录，请同步替换代码与配置中的 `/home/youyeetoo/InNet_box` 前缀（约 5 处核心路径，见审计报告）。

### 10.7 MeloTTS 首次启动加载慢

- MeloTTS 首次启动需加载 MeloTTS-Chinese checkpoint（约 200MB）及两个 BERT 模型，CPU 上约需 30-60s。
- 加载期间 /health 返回 state: starting，/tts 返回 503。
- 加载完成后 /health 切换为 state: ready。建议在 start_all.sh 中等待 health 就绪后再启用后端。
- 若缺失依赖（如 proces、nltk、num2words 等），会报 ModuleNotFoundError，批量安装即可。
- 源服务器为 192.168.0.14:5101，可在 0.14 确认模型正常后再同步到 0.117。

---

## 11. 运维管理

### 11.1 restart_backend.sh

统一管理脚本，位于项目根目录: `./restart_backend.sh`

```bash
./restart_backend.sh              # 重启后端 (8000)
./restart_backend.sh --agent      # 重启 OpenClaw Agent (18790/18791)
./restart_backend.sh --all        # 全部重启
./restart_backend.sh --install    # 安装 systemd 开机自启
```

### 11.2 systemd 服务

服务名: `innet_backend` (开机自启已启用)

```bash
sudo systemctl restart innet_backend   # 重启后端
sudo systemctl status innet_backend    # 查看状态
sudo journalctl -u innet_backend -f    # 实时日志
```

### 11.3 历史备份

仓库已不再保留独立备份目录，所有历史版本通过 git 提交历史回溯。

---

> **首次启动参考**: 2026-07-16 的部署全记录曾存放于 `release/logs/service-start-record-20260716.md`，现该目录已随仓库整理移除；部署要点见本文档第 7 节。

部署要点详见第 7 节「启动指南」与第 8 节「运维与调试」。
