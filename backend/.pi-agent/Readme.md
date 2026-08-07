# PI Agent 双模块改造 — 最新项目框架与改动报告

> 服务器：`youyeetoo@192.168.1.20`
> 后端：`/home/youyeetoo/backend/` | 前端：`/home/youyeetoo/web/`
> 报告日期：2026-07-13 16:30（第八次更新 — 版本固化）

---

## 一、改造总览

### 新增端口

| Agent | 端口 | 状态 |
|-------|------|------|
| **openclaw-gateway** | **:18789** | ✅ **运行中** (systemd) |
| **chat-agent** | **:18790** | ✅ **运行中** |
| **doc-agent** | **:18791** | ✅ **运行中** |
| 35B 模型(primary) | `192.168.10.212:8081` | 🔴 可主动关闭以测试降级 |
| 0.6B 模型(fallback) | `127.0.0.1:8088` | ✅ 本地 llama-server |
| 35B 模型(Ollama) | `192.168.10.212:21434` | ❌ **已彻底移除**（代码+配置清理） |

### 降级模型（2026-07-13 新增）

| 模型 | 端口 | 用途 | 上下文 |
|------|------|------|--------|
| Qwen3-0.6B-Q4_K_M.gguf | 127.0.0.1:8088 | 自动降级目标 | 6144 tokens |
| llama-server | pid 动态 | 本地推理服务 | `-c 6144 --threads 4` |

### 新增目录结构

```
backend/
├── .pi-agent/                          ← PI Agent 工作空间（新增）
│   ├── chat/                           ← Chat Agent 配置
│   │   ├── AGENTS.md, SOUL.md, ...     ← Agent 人格定义
│   │   ├── openclaw.json               ← Gateway 配置（端口:18790）
│   │   ├── openclaw.config.ts           ← TypeScript 配置
│   │   ├── models.json                  ← 模型配置
│   │   ├── skills/                      ← 4 个 skill
│   │   │   ├── conversation-title/
│   │   │   ├── kb-search/
│   │   │   ├── summarize/
│   │   │   └── find-skills/
│   │   ├── tools/tool-registry.json     ← 工具注册表
│   │   └── state/                       ← 运行时状态（sessions、devices）
│   │
│   └── doc/                            ← Document Agent 配置
│       ├── AGENTS.md, SOUL.md, ...     ← Agent 人格定义
│       ├── openclaw.json               ← Gateway 配置（端口:18791）
│       ├── openclaw.config.ts           ← TypeScript 配置
│       ├── models.json                  ← 模型配置
│       ├── skills/                      ← 6 个 skill
│       │   ├── doc-gen/
│       │   ├── long-document-chunking/
│       │   ├── word-formatting/
│       │   ├── document-skills-docx/
│       │   ├── claude-office-docx/
│       │   └── official-document-writing/
│       ├── tools/tool-registry.json     ← 工具注册表
│       └── state/                       ← 运行时状态（sessions、devices）
│
├── app/services/pi_agent_client/       ← Python 客户端模块（新增）
│   ├── __init__.py                      ← 模块导出（8 个符号）
│   ├── base_client.py                   ← 基础客户端（HTTP/SSE、健康检查、超时重试）
│   ├── chat_client.py                   ← Chat Agent 客户端（:18790，OpenAI 格式）
│   ├── doc_client.py                    ← Document Agent 客户端（:18791，/v1/responses 格式）
│   └── degradation.py                   ← 降级决策链（双级降级）
│
├── scripts/
│   ├── start-pi-agent.sh               ← 启动脚本（同时启动 :18790 + :18791）
│   └── stop-pi-agent.sh                ← 停止脚本
│
├── tests/
│   ├── test_pi_agent_integration.py     ← 集成测试（5 项）
│   └── test_pi_agent_degradation.py     ← 降级链路测试（6 项）
│
├── data/
│   ├── pi-agent-chat.pid                ← chat-agent PID 文件
│   ├── pi-agent-doc.pid                 ← doc-agent PID 文件
│   ├── pi-agent-chat.log                ← chat-agent 日志
│   └── pi-agent-doc.log                 ← doc-agent 日志
│
├── app/routers/conversations.py         ← 修改（新增 PI Agent 分支）
└── app/routers/conversations.py.bak.*  ← 备份文件
```

---

## 二、PI Agent 客户端架构

### 2.1 模块依赖关系

```
app/services/pi_agent_client/
├── __init__.py        ← 导出 8 个符号：PiAgentClient, health_check,
│                          call_chat_agent, call_doc_agent,
│                          chat_with_degradation, doc_with_degradation,
│                          _use_pi_agent_chat, _use_pi_agent_doc
│
├── base_client.py     ← 依赖 httpx（异步 HTTP/SSE）
│   ├── AgentUnavailable    异常类
│   ├── AgentTimeout        异常类
│   ├── health_check()      异步健康检查（3s 超时，30s 缓存）
│   └── PiAgentClient      基类
│       ├── is_healthy()        带缓存健康检查
│       ├── post_json()        POST JSON 请求
│       └── post_sse_stream()  POST SSE 流式（异步生成器）
│
├── chat_client.py     ← 依赖 base_client
│   └── call_chat_agent()     → POST :18790/v1/responses（SSE 流）
│
├── doc_client.py      ← 依赖 base_client
│   └── call_doc_agent()      → POST :18791/v1/responses（SSE 流）
│
└── degradation.py     ← 依赖 base_client + chat_client + doc_client
    ├── _use_pi_agent_chat()      ← Feature Flag: PI_AGENT_CHAT
    ├── _use_pi_agent_doc()       ← Feature Flag: PI_AGENT_DOC
    ├── chat_with_degradation()   ← 双级降级链
    └── doc_with_degradation()    ← 双级降级链
```

### 2.2 Chat 自动降级链（v7 — 固化版本）

```
所有 Chat 请求 → conversations.py L747 (唯一入口，PI_AGENT_CHAT=1)
  │
  └─ chat_with_degradation()
       │
       ├─ ① _is_35b_reachable() — TCP 探测 5 次（2s 超时, 1.5s 间隔）
       │
       ├─ 35B 可达 ──→ PI Agent Chat (:18790) → 失败 → PCW (:8099) → llm_client
       │
       └─ 35B 不可达 ──→ 跳过 PI Agent/PCW，直接 _ollama_generate_with_fallback()
                              │
                              ├─ 35B (8081/v1) OpenAI-compatible → 失败 → 重试 4 次
                              ├─ ↓ 全部失败 → _local_small_generate()
                              │     ├─ 0.6B (:8088) bare prompt, ≤1500 chars
                              │     ├─ timeout → 自动重试 3 次 (5s 间隔)
                              │     ├─ 503(繁忙) → 等待 5s 重试
                              │     └─ 断连 → _restart_06b_model() 自动重启 + 重试
                              └─ ↓ 3 次全失败 → "[错误] ..."
```

**v7 变更（2026-07-13 16:30 固化）：**

| 变更 | 说明 |
|------|------|
| ✅ 0.6B 鲁棒性 | 3 次重试 / 503 繁忙处理 / 超时等待 / 断连自动重启 |
| ✅ timeout 30s | 从 12s 提高到 30s，覆盖冷启动 |
| ✅ 孤儿进程根治 | `fuser -k 8000/tcp` 替代 pkill；`start_clean.sh` 每次启动前强制清理 |
| ✅ PI_AGENT_CHAT 固化 | .env + start.sh + health-check.sh 统一为 1 |
| ✅ 缓存隔离 | `start_clean.sh` 每次启动前 `find -delete __pycache__ + .pyc` |
| ✅ 版本备份 | `backups/FROZEN-20260713/` 归档全部关键文件 |

**v5 变更（2026-07-13 11:30）：**

| 变更 | 说明 |
|------|------|
| ❌ 移除 Cloud DashScope | 不再使用云端兜底，完全本地自愈 |
| ❌ 移除 21434 Ollama | 代码+配置 0 残留，35B 唯一入口 8081 |
| ✅ 断链重试 | 35B 失败后重试 3-5 次（1.5s 间隔），避免瞬时抖动触发降级 |
| ✅ 0.6B 自愈 | `_restart_06b_model()` — 0.6B 挂了自动 kill+重启+等待就绪+重试 |
| ✅ 规则兜底优先 | `_local_reply`/`_general_short_fallback` 拦截简单问候，减少模型调用 |

**关键设计决策：**

| 决策 | 原因 |
|------|------|
| 不自动重启 35B | 35B 是远程模型，重启权限和稳定性不在本机控制 |
| 重试再降级 | 避免网络瞬时抖动误触发降级，提升用户体验 |
| 0.6B 自动重启 | 0.6B 是本机进程，挂了可快速自愈 |
| bare prompt 防 OOM | 零系统提示词 + ≤1500 字符 + max 512 tokens |
| 移除 Cloud | 仅本地自愈，不依赖外部 API |

**代码位置：**
- `app/services/llm_client.py`:
  - `_ollama_generate_with_fallback()` — 35B 调用 + 重试 + 降级
  - `_local_small_generate()` — 0.6B bare prompt 调用
  - `_restart_06b_model()` — 0.6B 自动重启
- `app/services/pi_agent_client/degradation.py`:
  - `chat_with_degradation()` — SSE 降级链入口
  - `_is_35b_reachable()` — TCP 探测，5 次重试

### 2.2b Document 降级链（不变）

```
doc_with_degradation():
  ① PI Agent doc (:18791) → ② docs_pipeline (0.6B+3B)
```

### 2.3 SSE 格式对齐

`degradation.py` 中的辅助函数完全对齐 `conversations.py` 已有格式：

| 辅助函数 | 对齐来源 | 行号参考 |
|---------|---------|---------|
| `_sse_frame(payload)` | `_sse_event(json_module, payload)` | L425 |
| `_wrap(workflow, intent, payload)` | `_workflow_event(workflow, intent, payload)` | L122 |

---

## 三、conversations.py 修改点

### 3.1 新增导入（line ~9）

```python
from app.services.pi_agent_client.degradation import (
    chat_with_degradation,
    doc_with_degradation,
    _use_pi_agent_chat,
    _use_pi_agent_doc,
)
```

### 3.2 Chat 分支 PI Agent 路径（~line 24）

```python
if _use_pi_agent_chat():
    # → 走 PI Agent + 降级链
    async for sse_frame in chat_with_degradation(...):
        yield sse_frame
```

### 3.3 Document 分支 PI Agent 路径（~line 84）

```python
if _use_pi_agent_doc():
    # → 走 PI Agent + 降级链
    async for sse_frame in doc_with_degradation(...):
        yield sse_frame
```

---

## 四、PI Agent 工作空间配置

### 4.1 Chat Agent（:18790）

| 配置项 | 值 |
|--------|-----|
| 端口 | 18790 |
| Agent ID | `chat` |
| Primary 模型 | `Qwen3.5-35B-A3B-UD-Q4_K_XL.gguf` @ `192.168.10.212:8081` |
| Fallback 模型 | `Qwen3-0.6B-Q4_K_M.gguf` @ `127.0.0.1:8088` |
| 降级策略 | 35B 连接失败 → OpenClaw model fallback → 0.6B |
| Skills（3）⚠️ kb-search 已禁用 | conversation-title, summarize, find-skills |
| 工具（2） | kb_search → `/api/v1/internal/kb/search` |
| | local_small_model → `/api/v1/internal/local-small/generate` |
| 插件 | backend-bridge → `http://127.0.0.1:8000` |

> **修复记录**：kb-search skill 被禁用（`skills.entries.kb-search.enabled: false`），原因是模型不支持原生 function calling（`supportsTools: false`），agent 退化为文本式 tool call，导致原始 XML `<tool_call>` 泄露到前端 SSE 输出中。

### 4.2 Document Agent（:18791）

| 配置项 | 值 |
|--------|-----|
| 端口 | 18791 |
| Agent ID | `doc` |
| 模型 | `Qwen3.5-35B-A3B-UD-Q4_K_XL.gguf` @ `192.168.10.212:8081` |
| Skills（6） | doc-gen, long-document-chunking, word-formatting, document-skills-docx, claude-office-docx, official-document-writing |
| 插件 | backend-bridge → `http://127.0.0.1:8000` |
| Agent 超时 | **120s**（已修复，原默认 30s 短于 35B 推理时间 15-26s） |

---

## 五、Feature Flag 控制

| 环境变量 | 默认值 | 作用 |
|---------|--------|------|
| `PI_AGENT_CHAT` | `false` | `true` 时 Chat 走 PI Agent 主路径 |
| `PI_AGENT_DOC` | `false` | `true` 时 Document 走 PI Agent 主路径 |

```bash
# 开启
export PI_AGENT_CHAT=true
export PI_AGENT_DOC=true

# 回滚
export PI_AGENT_CHAT=false
export PI_AGENT_DOC=false
```

---

## 六、全部测试结果

### 6.1 集成测试（test_pi_agent_integration.py）

| 测试 | 状态 | 说明 |
|------|------|------|
| `test_conversations_module_syntax` | ✅ | AST 语法正确 |
| `test_pi_agent_client_module_loads` | ✅ | 模块导入正常 |
| `test_feature_flag_defaults_off` | ✅ | 默认关闭 |
| `test_feature_flags_independent` | ✅ | 独立控制 |
| `test_app_main_loads` | ⏭️ skip | 依赖 ML 模块 |

### 6.2 降级链路测试（test_pi_agent_degradation.py）

| 测试 | 状态 | 说明 |
|------|------|------|
| `test_health_check_unreachable` | ✅ | 不可达返回 False |
| `test_health_check_timeout` | ✅ | 超时返回 False |
| `test_default_disabled_chat` | ✅ | 默认关闭 |
| `test_default_disabled_doc` | ✅ | 默认关闭 |
| `test_env_enabled_chat` | ✅ | 环境变量控制 |
| `test_chat_degradation_fallback` | ⚠️ 需更新 | 降级目标改为 PCW，非 llm_client |
| `test_doc_degradation_pipeline` | ⚠️ 需更新 | 降级目标改为 docs_pipeline 仅 |

---

## 七、Git 提交记录

```
1257805 backup: Phase 4 验收完成 — PI Agent 改造全流程验证通过
27c6187 test: Phase 3 - 集成测试通过，Feature Flag 默认关闭
6393dc3 feat: Phase 3 - conversations.py Document 分支添加 PI Agent 主路径
eabd873 feat: Phase 3 - conversations.py Chat 分支添加 PI Agent 主路径
5228642 backup: Phase 3 前快照
83f75a9 fix: 更新 35B 模型名 + 重启 agent
343c6df test: Phase 2 - 降级链路单元测试
bed8efd feat: Phase 2 - chat_client + doc_client 完成
d24f4b2 feat: Phase 2 - degradation fallback chain (Task 8)
1675b4e feat: Phase 2 - pi_agent_client base 模块
8b982e4 feat: Phase 1 PI Agent startup — openclaw.json configs + health checks
a56cac6 feat: Phase 1 - PI Agent 启动/停止脚本
e88814e feat: Phase 1 - doc-agent skills + tools 配置
940e2f3 feat: Phase 1 - chat-agent skills + tools 配置
6e767ee feat: Phase 1 - 创建 PI Agent 工作空间目录结构
c49bf45 backup: 改造前基准快照
```

---

## 八、项目最新架构总图

```
前端 :3000（Vue/Vite）
  ├─ /chat         → ChatPage.vue → ChatMode(workflow="chat")
  ├─ /document     → DocumentPage.vue → ChatMode(workflow="document")
  └─ /workspace    → WorkspacePage.vue → KnowledgeMode.vue + KnowledgeFileSearchView.vue
                            │
                            │ SSE
                            ▼
                 conversations.py（核心中枢）
                            │
              ┌─────────────┼─────────────┐
              │             │             │
         workflow=      workflow=     workflow=
         "chat"        "document"    "knowledge"
              │             │             │
              ▼             ▼             ▼
    ┌─────────────────────────────────────────┐
    │        PI Agent 客户端层（新增）          │
    │  app/services/pi_agent_client/           │
    │                                          │
    │  Chat: chat_with_degradation()           │
    │    ① PI Agent(:18790) → ② PCW(:8099)   │
    │                                          │
    │  Doc: doc_with_degradation()             │
    │    ① PI Agent(:18791) → ② docs_pipeline│
    └─────────────────────────────────────────┘
              │             │
              ▼             ▼
    ┌──────────────────┐  ┌────────────────────┐
    │ PI Agent chat    │  │ PI Agent doc       │
    │ :18790           │  │ :18791             │
    │ Agent ID: "chat" │  │ Agent ID: "doc"   │
    │ 4 skills +       │  │ 6 skills +         │
    │ 2 tools          │  │ backend-bridge     │
    │                  │  │                    │
    │ model: Qwen35B   │  │ model: Qwen35B     │
    │ @ 192.168.10.212  │  │ @ 192.168.10.212    │
    │ :8081            │  │ :8081              │
    └──────────────────┘  └────────────────────┘
              │                    │
              └────────┬───────────┘
                       ▼
             后端 Internal API（:8000）
        /internal/kb/search, /internal/local-small/generate
        /internal/document-render-docx
```

---

## 九、当前状态（2026-07-13 v7 固化版本）

### 端到端降级测试（2026-07-13 16:30 v7 固化）

| 测试项 | 结果 | 耗时 | 说明 |
|--------|------|------|------|
| 35B 连通性 | ❌ Connection refused | — | 主动关闭 |
| 35B 重试 | ✅ 4 次重试后放弃 | ~6s | 1.5s 间隔 × 4 次 |
| 降级到 0.6B | ✅ 返回代码回复 | ~3s | bare prompt, ≤1500 chars |
| 0.6B 自愈 | ✅ | ~10s | 被杀后自动重启恢复 |
| 21434 残留 | ✅ 0 引用 | — | grep 验证 |
| Cloud DashScope | ❌ 已移除 | — | 降级链中不再使用 |
| 规则兜底 | ✅ | <1s | "你好"等简单问候直接回复 |
| **总耗时** | **35B 断→0.6B 回复** | **~9s** | 6s 重试 + 3s 推理 |
| **PI Agent 统一路径** | ✅ | — | SSE 流式正常，`status:degraded` + token 流 |
| **重复分支消除** | ✅ | — | L1897/L2060 不再可达，无"异常无兜底"问题 |
| **0.6B 鲁棒性** | ✅ | 3次重试 | timeout/503/断连全覆盖 |
| **孤儿进程根治** | ✅ | — | `fuser -k` + `start_clean.sh` |
| **PI_AGENT_CHAT 固化** | ✅ | — | .env + start.sh + health-check.sh 全=1 |
| **版本备份** | ✅ | — | `backups/FROZEN-20260713/` |

### 改动文件清单（2026-07-13 v5 最终版）

| 文件 | 变更 | 状态 |
|------|------|------|
| `config.yaml` | `ollama_base_url` → `8081/v1`；0.6B local 配置 | ✅ |
| `llm_client.py` | 移除 Ollama API→OpenAI；新增 `_local_small_generate()`、`_restart_06b_model()`；4 个 fallback 函数加重试+降级；移除 Cloud DashScope 降级 | ✅ |
| `degradation.py` | `_is_35b_reachable()` 5 次重试；`chat_with_degradation()` 跳过 PI Agent 直走 llm_client | ✅ |
| `.openclaw/openclaw.json` | 新增 0.6B provider + fallback chain | ✅ |
| `.pi-agent/chat/openclaw.json` | 新增 0.6B provider + fallback + chat-fallback agent | ✅ |
| `.pi-agent/chat/models.json` | 新增 0.6B provider | ✅ |
| `Readme.md` | 新增第十节（进程管理/故障排查）；v5 降级链文档 | ✅ |
| 备份 | `backups/degradation-20260713-final/`（2 次更新） | ✅ |

### 调试教训（2026-07-13）

| 问题 | 根因 | 教训 |
|------|------|------|
| 改 degradation.py 不生效 | `python run.py` 不是 `uvicorn`，重启脚本匹配不到 | 先 `ps aux` 确认进程名 |
| 新进程启不来 | 旧 worker 残留锁死 SQLite | 杀进程后 `rm -f app.db-journal app.db-wal` |
| .env 改了不生效 | `setdefault` 不覆盖已有 env | `cat /proc/PID/environ` 确认 |
| 备份恢复丢失改动 | 回滚时覆盖了之前的 21434→8081 迁移 | 备份命名加上改动内容描述 |
| 0.6B auto-restart 端口错误 | `_restart_06b_model` 硬编码 8088，但有旧进程在 8002 | 重启前 `fuser -k` 确保端口释放 |
| 规则兜底拦截测试 | `_local_reply("你好")` 返回预置回复，掩盖模型降级问题 | 用非简单问候测试真实链路 |
| 多worker孤儿进程 | `workers=2` 杀master后worker变孤儿(PPID=1)继续占用端口 | `fuser -k 8000/tcp` 不用 pkill |
| cron覆盖.env | health-check.sh 设 `PI_AGENT_CHAT=true`，start.sh读.env=0 | 统一全部=1 |
| 缓存残留 | 系统Python和venv Python共享.pyc目录 | `start_clean.sh` 每次启动前 `find -delete` |

### 固化文件备份

```
backups/FROZEN-20260713/
├── llm_client.py          # 移除21434 + 0.6B鲁棒retry + OpenAI API
├── degradation.py         # _is_35b_reachable(5次) + _ollama_generate_with_fallback
├── conversations.py       # 1931行(原2139行) PI Agent唯一入口
├── config.yaml            # ollama→8081/v1, timeout=30s
├── .env                   # PI_AGENT_CHAT=1
├── start.sh → start_clean.sh
├── start_clean.sh         # 5步自动化重启脚本
├── openclaw-gateway.json  # 网关 fallback 链
└── openclaw-chat.json     # chat agent fallback 链
```

### 服务状态

| 服务 | 端口 | 状态 |
|------|------|------|
| FastAPI 后端 | 8000 | ✅ `python run.py` (2 workers) |
| 0.6B llama.cpp | 8088 | ✅ `llama-server -c 6144` |
| PCW | 8099 | ✅ `python python_chat_workflow.py` |
| OpenClaw Gateway | 18789 | ✅ systemd |
| PI Agent Chat | 18790 | ✅ `openclaw gateway --port 18790`（**主路径**） |
| PI Agent Doc | 18791 | ✅ `openclaw gateway --port 18791` |
| 35B 主模型 | 192.168.10.212:8081 | 🔴 可主动关闭测试降级 |
| Cloud DashScope | api.aliyuncs.com | ✅ qwen-plus |

### 启动命令（固化版本）

```bash
# ===== 唯一重启命令 — 自动杀孤儿+清缓存+验证 =====
bash /home/youyeetoo/backend/start_clean.sh

# start_clean.sh 执行流程:
#   1/5 杀孤儿进程 (fuser -k 8000/tcp)
#   2/5 清 Python 缓存 (find -delete __pycache__ *.pyc)
#   3/5 清数据库锁 (rm app.db-journal app.db-wal)
#   4/5 验证环境 (PI_AGENT_CHAT=1)
#   5/5 启动 + 等待就绪 (最多 60s)

# ===== 辅助命令 =====
# 启动 0.6B 降级模型
nohup /home/youyeetoo/llama.cpp-master/build/bin/llama-server   -m /home/youyeetoo/rkllm_model_zoo/Qwen3-0.6B/Qwen3-0.6B-Q4_K_M.gguf   --host 0.0.0.0 --port 8088 -c 6144 --threads 4 --jinja --reasoning off   > /tmp/llama-8088.log 2>&1 &

# 检查服务状态
curl -s http://127.0.0.1:8000/api/v1/health           # FastAPI 后端
curl -s http://127.0.0.1:8088/v1/chat/completions      # 0.6B 降级模型
curl -s http://192.168.10.212:8081/v1/models           # 35B 主模型

# 验证代码已加载（进程启动时间 > 文件修改时间）
ps -o lstart,pid -p $(ss -tlnp | grep ':8000' | grep -oP 'pid=\K\d+' | head -1)
stat -c '%y' /home/youyeetoo/backend/app/services/pi_agent_client/degradation.py

# 测试降级
curl -s -X POST http://127.0.0.1:8000/api/v1/chat   -H 'Content-Type: application/json'   -H 'Authorization: Bearer <token>'   -d '{"content":"低空经济是什么"}'
# 预期：0.6B 真实回复，非"这句话比较短..."
```


---

## 十、后端进程管理与故障排查（2026-07-13）

### 10.1 进程启动机制

后端通过 `python run.py` 启动，**不是直接调 uvicorn**。

```
run.py 启动流程:
  1. python-dotenv 加载 .env → os.environ
  2. uvicorn.run("app.main:app", workers=2)
  3. 每个 worker 独立进程，共享 SQLite 数据库
```

| 启动脚本 | 用途 | 命令 |
|---------|------|------|
| `start_all.sh` | 全服务启动（LLM + MiniCPM + 后端 + PI Agent） | `bash start_all.sh` |
| `start.sh` | 仅启动后端（2 workers） | `bash start.sh` |
| `run.py` | 后端入口（uvicorn, 2 workers） | `python run.py` |

### 10.2 .env 加载机制（重要！）

```
加载顺序:
  1. shell 环境变量（最高优先级，setdefault 不覆盖）
  2. python-dotenv 加载 .env 文件（覆盖 os.environ 中不存在的 key）
  3. config.py _load_dotenv_if_present()（使用 setdefault，不覆盖已有值）

陷阱: 如果进程继承的 shell 环境已有 PI_AGENT_CHAT=1，
      .env 中的 PI_AGENT_CHAT=0 不会生效！
      → 必须在启动前 unset 或显式设置
```

### 10.3 干净重启步骤

```bash
# ===== 1. 彻底杀进程 =====
# 注意: 进程名是 "python run.py"，不是 "uvicorn"！
ps aux | grep 'run.py\|uvicorn' | grep -v grep
kill -9 $(ps aux | grep -E 'run.py|uvicorn.*app.main' | grep -v grep | awk '{print $2}')

# ===== 2. 确认端口释放 =====
ss -tlnp | grep 8000    # 应该为空
fuser /home/youyeetoo/backend/data/app.db  # 应该为空

# ===== 3. 清理数据库锁（如果有残留） =====
rm -f /home/youyeetoo/backend/data/app.db-journal
rm -f /home/youyeetoo/backend/data/app.db-wal

# ===== 4. 清理 Python 缓存（改过 .py 文件时必做） =====
find /home/youyeetoo/backend -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
find /home/youyeetoo/backend -name '*.pyc' -delete 2>/dev/null

# ===== 5. 重启 =====
cd /home/youyeetoo/backend && bash start.sh
# 或者只启动后端:
cd /home/youyeetoo/backend && nohup python run.py > data/server.log 2>&1 &

# ===== 6. 验证 =====
sleep 6
curl -s http://127.0.0.1:8000/api/v1/health

# ===== 7. 确认代码已加载（检查进程启动时间） =====
ps -o lstart,pid,comm -p $(ss -tlnp | grep ':8000' | grep -oP 'pid=\K\d+' | head -1)
stat -c '%y' /home/youyeetoo/backend/app/services/pi_agent_client/degradation.py
# 进程启动时间必须晚于 .py 文件修改时间！
```

### 10.4 常见故障排查

#### 故障 1: 修改代码后不生效

```bash
# 症状: curl 返回旧行为，但源文件已更新
# 根因: 进程启动时间早于文件修改时间

# 诊断:
ps -o lstart,pid -p $(ss -tlnp | grep ':8000' | grep -oP 'pid=\K\d+' | head -1)
ls -la /home/youyeetoo/backend/app/services/pi_agent_client/degradation.py
# 如果进程启动时间 < 文件修改时间 → 代码未加载！

# 修复: 干净重启（见 10.3）
```

#### 故障 2: Database is locked

```bash
# 症状: 启动报错 "sqlite3.OperationalError: database is locked"
# 根因: 旧进程未完全杀死，残留 worker 持有数据库锁

# 诊断:
fuser /home/youyeetoo/backend/data/app.db    # 显示持有锁的 PID
ps aux | grep python | grep -v grep           # 找残留进程

# 修复:
kill -9 $(fuser /home/youyeetoo/backend/data/app.db 2>/dev/null)
rm -f /home/youyeetoo/backend/data/app.db-journal
rm -f /home/youyeetoo/backend/data/app.db-wal
```

#### 故障 3: PI_AGENT_CHAT 环境变量不生效

```bash
# 症状: .env 改了但 `_use_pi_agent_chat()` 仍返回旧值
# 根因: shell 环境变量优先级高于 .env（setdefault 不覆盖）

# 诊断:
cat /proc/$(ss -tlnp | grep ':8000' | grep -oP 'pid=\K\d+' | head -1)/environ | tr ' ' '
' | grep PI_AGENT
grep PI_AGENT /home/youyeetoo/backend/.env
# 两边不一致 → 进程用的是 shell 继承的值

# 修复: 启动时显式设置
PI_AGENT_CHAT=0 python run.py &
```

#### 故障 4: 降级链路无响应

```bash
# 症状: 前端输入后无 AI 回复
# 根因: 35B 模型不可达 + 降级链路配置/代码问题

# 诊断步骤:
# 1. 检查 35B 连通性
timeout 3 bash -c 'echo > /dev/tcp/192.168.10.212/8081' && echo OK || echo DOWN

# 2. 检查 0.6B 降级模型
curl -s http://127.0.0.1:8088/v1/chat/completions   -H 'Content-Type: application/json'   -d '{"model":"Qwen3-0.6B-Q4_K_M.gguf","messages":[{"role":"user","content":"hi"}],"max_tokens":10}'

# 3. 检查 PI Agent 链路
curl -s http://127.0.0.1:18790/health
curl -s http://127.0.0.1:18789/health
curl -s http://127.0.0.1:8099/health

# 4. 直接测试 /api/v1/chat（绕过 PI Agent）
curl -s -X POST http://127.0.0.1:8000/api/v1/chat   -H 'Content-Type: application/json'   -H 'Authorization: Bearer <token>'   -d '{"content":"你好"}'

# 5. 直接测试 degradation.py（Python 环境）
cd /home/youyeetoo/backend && python3 -c "
import asyncio, sys
sys.path.insert(0, '.')
from app.services.pi_agent_client.degradation import chat_with_degradation
async def t():
    async for f in chat_with_degradation(content='你好', user_id=1, conversation_id=1, message_id=1):
        print(f[:120])
asyncio.run(t())
"

# 6. 检查 backend 日志
tail -50 /home/youyeetoo/backend/data/server.log
```

### 10.5 进程监控

```bash
# 查看所有相关进程
ps aux | grep -E 'run.py|uvicorn|llama-server|openclaw|python_chat' | grep -v grep

# 查看端口占用
ss -tlnp | grep -E '8000|8088|8099|18789|18790|18791'

# 查看数据库锁
fuser /home/youyeetoo/backend/data/app.db

# 查看进程启动时间
ps -o lstart,pid,comm -p $(ss -tlnp | grep ':8000' | grep -oP 'pid=\K\d+' | head -1)

# 查看进程环境变量
cat /proc/$(ss -tlnp | grep ':8000' | grep -oP 'pid=\K\d+' | head -1)/environ | tr ' ' '
'

# 查看 backend 日志
tail -f /home/youyeetoo/backend/data/server.log
tail -f /tmp/backend.log
```

### 10.6 服务端口速查表

| 端口 | 服务 | 启动方式 | 启动脚本 |
|------|------|---------|---------|
| 8000 | FastAPI 后端 | `python run.py` | `start.sh` / `start_all.sh` |
| 8088 | 0.6B llama.cpp | `llama-server` | 手动 nohup |
| 8099 | PCW Python Chat Workflow | `python python_chat_workflow.py` | `start-pi-agent.sh` |
| 18789 | OpenClaw Gateway (systemd) | `openclaw gateway --port 18789` | systemd |
| 18790 | PI Agent Chat | `openclaw gateway --port 18790` | `start-pi-agent.sh` / `start_all.sh` |
| 18791 | PI Agent Doc | `openclaw gateway --port 18791` | `start-pi-agent.sh` / `start_all.sh` |
| 192.168.10.212:8081 | 35B 主模型 | 远程 llama-server | 远程机器 |
