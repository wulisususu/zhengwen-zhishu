# INnet Agent AI Box

一个面向内网服务器与边缘设备的多能力 AI 工作台，整合了 **AI 对话、文件解析、知识库、文档生成、PPT 生成与编辑、ASR 语音识别、TTS 语音合成、视觉理解/OCR** 等能力。

> **当前项目状态**
>
> 该仓库已包含主要业务源码与 PPT 模板资源，但当前版本仍带有生产服务器路径和硬件环境耦合，更适合二次开发或同构服务器迁移。要做到任意 Linux 服务器克隆后“一键启动”，请先完成本文“部署前必须处理的问题”中的四项整改。

## 主要能力

- Web 工作台：登录、会话、文件上传、知识库、模型设置与系统状态。
- AI 对话：支持本地模型、外部 OpenAI 兼容 API 与 OpenClaw/PI Agent 链路。
- 文档处理：文件解析、知识检索、普通文档生成和 SSE 流式文档生成。
- PPT 工作台：PPT 生成、增量生成、模板填充、原生增强、在线编辑、媒体管理和动画配置。
- 多模态：MiniCPM-V 视觉理解/OCR、Paraformer ASR、Piper 或外部服务 TTS。
- 边缘推理：包含 RK3588 上 RKLLM/RKNN 服务的接入代码与启动脚本。

## 技术栈

| 模块 | 技术 |
|---|---|
| 前端 | Vue 3、Vite、TypeScript、Pinia、Vue Router、Tailwind CSS |
| 后端 | FastAPI、Uvicorn、SQLAlchemy、SQLite、Pydantic |
| 文档/PPT | python-pptx、PyMuPDF、Mammoth、OpenPyXL、Pillow 等 |
| 本地推理 | RKLLM、RKNN、llama.cpp、MiniCPM-V、Paraformer、Piper |
| Agent | OpenClaw / PI Agent |

## 架构概览

```text
浏览器
  │
  ├── Vue/Vite 前端 :3000
  │       │
  │       └── /api/* 反向代理
  │
  └── FastAPI 主后端 :8000
          ├── SQLite / 上传文件 / 生成结果
          ├── RKLLM 主模型服务 :8001            （可选，RK3588）
          ├── Qwen3 轻量模型服务 :8002          （可选）
          ├── MiniCPM-V 视觉服务 :8003          （可选，RK3588）
          ├── OpenClaw Chat Agent :18790        （可选）
          ├── OpenClaw Document Agent :18791    （可选）
          └── OpenClaw Medical Agent :18792     （可选）
```

## 目录结构

```text
.
├── frontend/                         # Vue/Vite 前端
│   ├── src/                          # 页面、组件、状态管理和 PPT 工作台
│   ├── public/                       # 正式静态资源
│   ├── package.json
│   └── vite.config.js
├── backend/                          # FastAPI 后端
│   ├── app/
│   │   ├── routers/                  # 登录、会话、文件、知识库、ASR、TTS 等 API
│   │   ├── services/                 # 模型、Agent、文档和多模态服务
│   │   ├── docs_pipeline/            # SSE 文档生成链路
│   │   ├── minicpm_pipeline/         # MiniCPM 文档/视觉链路
│   │   ├── PPT_master/               # PPT 生成、编辑、模板、动画能力
│   │   └── templates/                # DOCX 等业务模板
│   ├── config.example.yaml           # 后端配置示例
│   ├── .env.example                  # 后端环境变量示例
│   ├── requirements.txt              # 基础依赖；当前尚未覆盖全部可选能力
│   └── run.py                        # FastAPI 启动入口
└── README.md
```

## 端口说明

| 端口 | 服务 | 是否必须 | 对外开放建议 |
|---:|---|---|---|
| `3000` | Vue/Vite 前端 | 是 | 可由 Nginx 对外提供 |
| `8000` | FastAPI 主 API | 是 | 建议仅由 Nginx 转发，或限制来源 |
| `8001` | RKLLM 主模型服务 | 否 | 仅监听内网/localhost |
| `8002` | Qwen3 轻量模型或备用路由 | 否 | 仅监听 localhost |
| `8003` | MiniCPM-V 视觉服务 | 否 | 仅监听 localhost |
| `18790` | OpenClaw Chat Agent | 否 | 仅监听 localhost |
| `18791` | OpenClaw Document Agent | 否 | 仅监听 localhost |
| `18792` | OpenClaw Medical Agent | 否 | 仅监听 localhost |

> **8003 端口冲突提醒**：当前 `backend/start_all.sh` 把 `8003` 用作 MiniCPM-V 服务，而 `frontend/vite.config.js` 又默认把 `/api/v1/docs-pipeline` 转发到 `8003`。主后端实际已经在 `8000` 注册 `/api/v1/docs-pipeline/generate`。普通部署应设置 `VITE_DOCS_BACKEND_PROXY=http://127.0.0.1:8000`，或直接把 Vite 默认值改为 `8000`。

## 部署前必须处理的问题

### 1. 立即轮换已经进入 Git 的凭据

仓库中发现硬编码的 Bearer Token/API Key，至少涉及：

- `backend/app/services/openclaw_gateway.py`
- `backend/app/children_medical/.pi/extensions/providers.ts`
- 多个 `backup`/`.bak` 历史文件

请先在对应服务端撤销并重新生成凭据，然后改为环境变量读取。仅删除当前文件不等于从 Git 历史中清除，公开仓库还应使用 `git filter-repo` 或 BFG 清理历史后强制推送。

### 2. 补齐完整 Python 依赖清单

根目录 `backend/requirements.txt` 只覆盖基础 API 依赖，代码还使用了 `httpx`、`requests`、`python-docx`、`docxtpl`、`reportlab`、`pdfplumber`、`pypdf`、`PyMuPDF`、`langgraph`、`sentence-transformers`、`faiss`、`librosa`、`onnxruntime`、`funasr` 等依赖。

建议从可运行的生产虚拟环境导出一份经过验证的锁定清单：

```bash
python -m pip freeze > requirements.lock.txt
```

然后在干净环境中重新安装并验证，避免直接把生产环境中无关包全部提交。

### 3. 消除生产服务器绝对路径

当前约有 40 多个正式源码/脚本文件写死了 `/home/youyeetoo/...`，包括上传目录、模型目录、知识库目录、日志目录和启动脚本。建议统一改为：

- 项目路径：基于 `Path(__file__)` 计算。
- 数据目录：`AI_BOX_DATA_DIR`。
- 模型目录：`AI_BOX_MODEL_DIR`。
- 日志目录：`AI_BOX_LOG_DIR`。
- 上传目录：`AI_BOX_UPLOAD_DIR`。
- Agent 状态目录：`AI_BOX_AGENT_STATE_DIR`。

在完成代码改造前，部署到其他目录时只能修改源码、修改脚本，或建立兼容软链接。

### 4. 修正前端文档代理端口

开发模式建议在 `frontend/.env` 中明确配置：

```dotenv
VITE_PPT_BACKEND_PROXY=http://127.0.0.1:8000
VITE_DOCS_BACKEND_PROXY=http://127.0.0.1:8000
```

## 快速启动：基础 Web + FastAPI

以下流程适用于先启动前端和主 API。PPT、本地模型、ASR/TTS、视觉识别等功能仍需根据后文补齐对应依赖和服务。

### 环境要求

- Linux 服务器；本地 RKLLM/RKNN 推理需要 RK3588 或兼容环境。
- Python 3.11 建议与生产环境保持一致。
- Node.js 24；仓库 `frontend/.nvmrc` 已指定版本。
- npm。
- 建议至少 4 GB 内存；启用本地模型时按模型实际需求增加。

### 1. 获取项目

```bash
git clone <your-repository-url>
cd innet-agent-ai-box
```

### 2. 配置并启动后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r app/PPT_master/skill/ppt-master/requirements.txt
cp config.example.yaml config.yaml
cp .env.example .env
mkdir -p data/uploads data/generated_docs
python run.py
```

默认主 API：`http://127.0.0.1:8000`；健康检查：`curl http://127.0.0.1:8000/api/v1/health`。

### 3. 配置并启动前端

```bash
cd frontend
nvm use
npm ci
cp .env.example .env
npm run dev
```

访问：`http://<服务器IP>:3000`

## 完整能力部署

### RKLLM 主模型服务（可选）

- 推荐端口：`8001`。
- 当前代码主要引用 Qwen2.5-3B-Instruct RKLLM。
- `backend/app/services/llm_server.py` 提供 `GET /health`、`POST /v1/completions`、`POST /v1/chat/completions`。

### Qwen3 轻量模型服务（可选）

- 推荐端口：`8002`。
- 供轻量问答、路由或备用推理使用，可通过 `LLM_06B_SERVICE_URL`、`QWEN_BASE_URL` 等配置覆盖。

### MiniCPM-V 视觉服务（可选）

- 推荐端口：`8003`。
- 需要 `vision_transformer.rknn`、`qwen.rkllm` 与 RKNNLite/RKLLM 运行库。

### ASR 与 TTS（可选）

- ASR API：`POST /api/v1/asr/recognize` 等；Paraformer 模型应通过部署脚本下载、复制或挂载。
- TTS API：`POST /api/v1/tts/synthesize`；Piper 模型可通过 `PIPER_MODEL`、`PIPER_CONFIG`、`PIPER_PYTHON` 配置。

### OpenClaw / PI Agent（可选）

| Agent | 默认端口 |
|---|---:|
| Chat Agent | `18790` |
| Document Agent | `18791` |
| Medical Agent | `18792` |

这些端口应只绑定 `127.0.0.1`，由主后端调用，不应直接暴露公网。

## 主要 API

所有主后端 API 默认以 `/api/v1` 开头。除健康检查、注册和登录外，多数业务接口需要 `Authorization: Bearer <access_token>`。

| 能力 | 主要路径 |
|---|---|
| 健康检查 | `GET /api/v1/health` |
| 注册/登录 | `/api/v1/auth/*` |
| 用户管理 | `/api/v1/users/*` |
| 会话与消息 | `/api/v1/conversations/*` |
| 文件上传与解析 | `/api/v1/files/*` |
| 知识库 | `/api/v1/knowledge/*` |
| ASR | `/api/v1/asr/*` |
| TTS | `/api/v1/tts/*` |
| 普通文档任务 | `/api/v1/documents/*` |
| SSE 文档生成 | `POST /api/v1/docs-pipeline/generate` |
| PPT 生成 | `POST /api/v1/ppt-master/generate` |
| PPT 编辑/导出 | `/api/v1/ppt-master/projects/*` |
| 系统设置 | `/api/v1/settings/*`、`/api/v1/system/*` |

## 配置文件

`backend/config.yaml` 应由 `backend/config.example.yaml` 复制生成；`jwt.secret` 与 `internal.service_token` 必须改为随机长字符串。可使用 `AI_BOX_CONFIG_DIR`、`BACKEND_CONFIG_FILE`、`BACKEND_ENV_FILE` 将真实配置放在仓库外。

## 数据与运行目录

以下内容属于运行状态，不应提交 Git：

```text
backend/data/
backend/output/
backend/projects/
backend/app/PPT_master/projects/
backend/.pi-agent/
frontend/node_modules/
frontend/dist/
```

## 生产部署建议

1. 前端执行 `npm run build`，由 Nginx 提供 `frontend/dist/`。
2. FastAPI 通过 systemd、Supervisor 或容器管理，不要使用 Vite 开发服务器作为长期生产服务。
3. Nginx 将 `/api/` 转发到 `127.0.0.1:8000`，模型、Agent 和数据库服务只绑定内网或 localhost。
4. 当前 `run.py` 固定 `workers=1`，不要直接增加多 worker，除非先把限流和任务状态迁移到共享存储。

## 模型文件

模型权重不应提交 Git。建议部署到统一目录，例如 `/opt/ai-box/models/`，并通过环境变量或配置文件引用。不要继续依赖个人用户目录。

## 仓库体积说明

`backend/app/PPT_master/skill/ppt-master/references/` 与 `templates/` 包含 PPT 生成流程所需的规则和模板资源，不能仅因为体积较大就直接删除。

## 安全要求

- 不提交 `.env`、`config.yaml`、JWT、API Key、访问令牌、私钥和本地证书。
- 所有示例密钥必须为空值或明显占位符。
- 生产环境不要使用 `allow_origins=["*"]` 与 `allow_credentials=True` 的宽松 CORS 组合，应限制到真实前端域名。

## 已知限制

- 部分启动脚本和业务代码写死 `/home/youyeetoo`。
- 根 `requirements.txt` 不是完整依赖锁定文件。
- `8003` 在前端代理与 MiniCPM 服务之间存在职责冲突。
- 仓库尚未提供 Docker Compose、统一安装脚本和数据库迁移流程。

## 开发检查

```bash
python -m compileall backend
cd frontend
npm ci
npm run typecheck
npm run build
```

## 贡献前检查

- 没有 `.bak`、`backup`、运行输出或验收截图。
- 没有真实 Token、API Key、密码、证书或服务器私有路径。
- `README`、`.env.example`、`config.example.yaml` 与代码保持同步。
