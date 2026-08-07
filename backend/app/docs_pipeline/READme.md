---
name: document-generation-standalone
description: 独立 docs_pipeline 服务 — 8001 端口，无认证，调试专用
---

# 独立 docs_pipeline (端口 8001)

## 设计动机

主后端 8000 承载全功能（聊天、ASR、TTS、文档等），调试文档管线时容易因 3B 同步阻塞导致整个 event loop 卡死，影响其他服务。因此将 docs_pipeline 拆为独立进程，与主后端隔离运行，互不干扰。

## 整体架构

```
┌─────────────────────────────────────────────────────┐
│                   standalone_docs_pipeline.py        │
│                                                     │
│  FastAPI app (port 8001)                            │
│  ┌───────────────────────────────────────────────┐  │
│  │  自建路由（无认证）                             │  │
│  │  ├─ POST /api/v1/docs-pipeline/generate       │  │
│  │  ├─ GET  /api/v1/files/{id}/download          │  │
│  │  └─ GET  /api/v1/health                       │  │
│  └───────────────────────────────────────────────┘  │
│                         │                           │
│                         ▼                           │
│  ┌───────────────────────────────────────────────┐  │
│  │  复用现有 pipeline 逻辑（import app.docs_pipeline）│  │
│  │  ├─ runner.py   → run_pipeline_stream()       │  │
│  │  ├─ graph.py    → build_graph()               │  │
│  │  ├─ nodes.py    → 4 节点 LangGraph 函数        │  │
│  │  ├─ core.py     → 3B/0.6B 推理、prompt 加载    │  │
│  │  ├─ retry.py    → 重试+重启逻辑                │  │
│  │  └─ sse_bridge.py → SSE 格式化                │  │
│  └───────────────────────────────────────────────┘  │
│                         │                           │
│                         ▼                           │
│  ┌───────────────────────────────────────────────┐  │
│  │  复用主后端基础模块                             │  │
│  │  ├─ app.database   → SessionLocal (SQLite)     │  │
│  │  ├─ app.models     → File model (DOCX 记录)    │  │
│  │  └─ app.services   → markdown_to_docx 等       │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  前端挂载                                            │
│  ┌───────────────────────────────────────────────┐  │
│  │  StaticFiles ← app/docs_pipeline/static/       │  │
│  │  ├─ index.html                                │  │
│  │  ├─ app.js  (API_BASE = '/api/v1')            │  │
│  │  └─ style.css                                 │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
    ┌─────────┐   ┌──────────┐   ┌──────────┐
    │ 8093    │   │ 8002     │   │ SQLite   │
    │ 3B 正文  │   │ 0.6B 大纲 │   │ app.db   │
    │(共享)    │   │(共享)    │   │(共享)    │
    └─────────┘   └──────────┘   └──────────┘
```

## 与主后端 8000 的对比

```
主后端 8000:                               独立 8001:

main.py                                   standalone_docs_pipeline.py
├─ 14 个 router（auth/chat/asr/...）       ├─ 3 个路由（generate/download/health）
├─ middleware（CORS/JWT/...）              ├─ CORS only
├─ 全局依赖注入（get_current_user）          ├─ 无依赖注入
├─ app.mount("/doc-generate", static)      ├─ app.mount("/", static)
└─ uvicorn.run                             └─ uvicorn.run
```

**关键差异**：

| | 8000 主后端 | 8001 独立 |
|--|-----------|---------|
| 入口文件 | `run.py` → `app.main:app` | `standalone_docs_pipeline.py` |
| 路由数量 | 14 个 router | 3 个直定义路由 |
| 认证方式 | JWT (`get_current_user` 依赖注入) | 无 |
| 前端路径 | `/doc-generate/` | `/`（根路径） |
| 前端 API_BASE | 自动拼接前缀 | 默认 `/api/v1`（一致） |
| 进程隔离 | 与全功能共享 event loop | 独立 event loop |
| 相互影响 | 管线阻塞 → 全站瘫痪 | 管线阻塞 → 仅 8001 不可用 |

## 代码结构

```
backend/
├── standalone_docs_pipeline.py    ← 本服务唯一入口，~120 行
├── app/
│   ├── docs_pipeline/             ← 复用：pipeline 核心（不改动）
│   │   ├── runner.py              # run_pipeline_stream() — SSE 流生成
│   │   ├── graph.py               # LangGraph StateGraph 构建
│   │   ├── nodes.py               # 4 节点函数
│   │   ├── core.py                # 模型推理、prompt 管理
│   │   ├── retry.py               # 重试+3B 重启
│   │   ├── sse_bridge.py          # SSE 事件格式化
│   │   ├── state.py               # PipelineState
│   │   └── static/                # 前端三件套 (index.html/app.js/style.css)
│   ├── database.py                ← 复用：SQLite SessionLocal
│   ├── models.py                  ← 复用：File ORM model
│   └── services/                  ← 复用：
│       ├── markdown_to_docx.py    # Markdown → DOCX 渲染
│       └── document_service.py    # DOC_OUTPUT_DIR、模板
```

## standalone_docs_pipeline.py 设计要点

### 1. 路径注入

```python
_BACKEND_ROOT = Path(__file__).resolve().parent  # 即 backend/
sys.path.insert(0, str(_BACKEND_ROOT))           # 确保 import app.* 可用
```

不依赖 `pip install -e .`，脚本放在 `backend/` 根目录即可运行。

### 2. 绕过认证

主后端 `router.py` 中对 `/docs-pipeline/generate` 做了 `Depends(get_current_user)` 依赖注入。standalone 自行定义了不带 auth 的路由，直接调用 `run_pipeline_stream()` 并传入固定 `user_id=1`。

### 3. 文件下载

Pipeline 完成后，`runner.py` 会往 `app.db` 写入 `File` 记录（含 `filepath`、`filename`）。standalone 直接从 DB 查记录，返回 `FileResponse`：

```
done event ──→ _file_id ──→ GET /api/v1/files/{id}/download ──→ FileResponse
```

### 4. 前端挂载

前端代码 (`app.js`) 中 `API_BASE = '/api/v1'`，与 standalone 路由前缀一致，无需修改。FastAPI `StaticFiles(html=True)` 自动处理 SPA fallback。

### 5. 模型共享

3B (8093) 和 0.6B (8002) 是独立进程，8000 和 8001 均通过网络请求访问，因此**模型服务无感知**——谁调用都一样。唯一冲突：同时调用时排队争抢，可能导致超时重试。

## 已知问题

### 同步阻塞（P0）

`core.py` / `nodes.py` 使用 `requests.post()` 同步调用 3B API（每次 50~80s），阻塞 uvicorn event loop。推理期间 8001 所有请求无响应。

**与 8000 的改进**：虽然阻塞仍然存在，但影响范围已缩小到 8001 单独进程，不再拖垮整个后端。

### 3B 模型不稳定

RKLLM runtime 偶发 SIGSEGV，成功率约 60%。失败时自动回退 0.6B 或输出占位内容。

### 与 8000 抢 3B

两个服务共享 8093，同时请求互相干扰。调试时避免同时触发生成。

## 启停

```bash
# 启动
ssh youyeetoo@192.168.10.26 "cd /home/youyeetoo/backend && source /home/youyeetoo/rkllm_model_zoo/funasr_env/bin/activate && export HF_ENDPOINT=https://hf-mirror.com && nohup python standalone_docs_pipeline.py --port 8001 > /home/youyeetoo/backend/data/standalone_docs.log 2>&1 &"

# 停止
ssh youyeetoo@192.168.10.26 "pkill -f standalone_docs_pipeline"

# 状态
curl -s http://192.168.10.26:8001/api/v1/health

# 日志
ssh youyeetoo@192.168.10.26 "tail -f /home/youyeetoo/backend/data/standalone_docs.log"
```

## 前端

```
http://192.168.10.26:8001/          # 无需认证，打开即用
```

## 日志路径

| 日志 | 路径 |
|------|------|
| 独立服务 | `/home/youyeetoo/backend/data/standalone_docs.log` |
| 3B 模型 | `/home/youyeetoo/backend/data/qwen3b_server.log` |
| 文档输出 | `/home/youyeetoo/backend/data/generated_docs/*.docx` |
