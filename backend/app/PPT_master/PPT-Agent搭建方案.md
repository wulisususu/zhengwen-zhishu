# 在 INnet_agent 后端新搭建「PPT 生成 Agent」实施方案

> 目标：复用现有 **FastAPI + OpenClaw(PI Agent)** 框架，新增一个 PPT 生成 agent（`pptgen`），
> 让用户通过后端接口提交主题/素材，由 agent 推理 + 后端驱动 ppt-master 脚本，产出原生可编辑 `.pptx`。
>
> **模型后端**：用户稍后配置的 **GLM-5.2**（智谱，OpenAI 兼容）。
> **部署形态**：后端与 agent 跑在 RK3588 板端（`192.168.0.11`），模型走网络（GLM-5.2 云端）。
>
> <span style="color:red">**【安全红线】本方案中除 Step 5（main.py 追加 1 行 import + 1 行 include_router）外，
> 所有操作均为&#8203;新增文件/目录，绝不修改、删除、覆盖任何已有文件。未列出的文件一律不碰。**</span>

---

## 0. 前提与现状（已实地核查，含关键校正）

| 项目 | 实际情况 |
|---|---|
| 后端根目录 | `/home/youyeetoo/INnet_agent/backend/`（RK3588 板端） |
| Web 框架 | **FastAPI** (`app/main.py`，`:8000`，`uvicorn` 2 workers) |
| Agent 框架 | **OpenClaw / PI Agent**（npm 全局 CLI，`~/.npm-global/bin/openclaw`） |
| 现有 Agent | `chat`(:18790)、`doc`(:18791) |
| Agent 主配置 | **`openclaw.json`**（定义 agents/gateway/models/skills/plugins），不是 `models.json` |
| Agent 启动方式 | `OPENCLAW_CONFIG_PATH=... OPENCLAW_STATE_DIR=... nohup openclaw gateway --port PORT --bind loopback` |
| Agent API | `/v1/responses`（SSE 流式），`/health`（健康检查） |
| Agent 鉴权 | `Authorization: Bearer <PI_AGENT_TOKEN>`，env 变量 `PI_AGENT_TOKEN` |
| Agent 的 LLM | 由 `openclaw.json` 的 `models.providers` 定义。doc agent 指向 `http://192.168.10.212:8081/v1`（35B） |
| 后端调 agent 的客户端 | `app/services/pi_agent_client/base_client.py`：`PiAgentClient(base_url, timeout, auth_token)` |
| 后端调 agent 的 payload | **必须含 `model` 字段**：`{"model": "openclaw/<agent_id>", "input": ..., "stream": True}` |
| Pipeline 模板 | `app/docs_pipeline/`（LangGraph StateGraph + SSE，但其 `core.py` 用独立模型服务器 :8002/:8093，不走 OpenClaw agent。**router/runner/graph/state/SSE 模式仍完全可复用**） |
| 已预留空目录 | `app/PPT-master/` 已建好（空） |

> **重要校正（vs 初版方案）**：
> 1. Agent 的主配置文件是 **`openclaw.json`**（不是 `models.json` 或 `AGENTS.md`）。
> 2. `docs_pipeline` 的 `core.py` 调用独立模型服务器（`:8002` + `:8093`），不走 OpenClaw agent。
>    这恰好让 PPT 方案更简洁——只需一个 pptgen agent，不需要多模型链。

---

## 1. 复用关系图（已修正）

```
用户 ──HTTP/SSE──> FastAPI :8000
                    │  app/PPT-master/router.py   POST /api/v1/ppt-master/generate
                    ▼
                 LangGraph pipeline (runner / nodes / graph / state)
                    │
                    ├── 调 pptgen agent   PiAgentClient → :18792, /v1/responses
                    │    payload: {"model": "openclaw/pptgen", "input": ..., "stream": True}
                    │    鉴权: Bearer <PI_AGENT_TOKEN>
                    │    agent 只做 LLM 推理/规划/出 SVG —— 不执行脚本
                    │
                    └── subprocess 跑 ppt-master 脚本
                         ├── project_manager.py init
                         ├── svg_quality_checker.py
                         ├── total_md_split.py → finalize_svg.py → svg_to_pptx.py
                         └── 产出 exports/<name>_<timestamp>.pptx
                              ▲
                    GLM-5.2 (智谱云端)   ← openclaw.json models.providers 配置
```

**核心决策**：后端 pipeline 用 `subprocess` 跑 ppt-master 的所有脚本（SVG→PPTX、图片、校验），
`pptgen` agent **只**负责 LLM 推理/规划/生成规范 SVG —— 沿用现有 `doc_client.py` → `PiAgentClient` → `/v1/responses` 的成熟调用链，
不依赖 OpenClaw 是否具备"自主执行 shell"能力。

---

## 2. 安全声明：哪些文件会被改动

| 操作类型 | 文件/目录 | 说明 |
|---|---|---|
| **新增** | `.pi-agent/pptgen/` 整体（openclaw.json, AGENTS.md, HEARTBEAT.md, IDENTITY.md, state/） | agent 工作区，完全新目录 |
| **新增** | `data/pi-agent-pptgen.log`, `data/pi-agent-pptgen.pid` | 运行时自动产生 |
| **新增** | `start_pptgen.sh` | 独立启动脚本，不修改 `start_all.sh` |
| **新增** | `app/PPT-master/` 下所有文件（router, runner, client, nodes, graph, state, sse_bridge, __init__, prompts/, skill/） | 后端模块，目录已存在但为空 |
| **仅追加 2 行** | `app/main.py` | 只加 import + include_router，不动已有代码 |
| **不修改** | `config.yaml`、`start_all.sh`、`.env`、`app/services/pi_agent_client/`、`app/docs_pipeline/`、`app/routers/`、`app/minicpm_pipeline/`、`.pi-agent/chat/`、`.pi-agent/doc/` … | **所有已有文件一律不动** |

---

## 3. 模型配置：GLM-5.2（配置文件为 `openclaw.json`）

GLM-5.2 走智谱 OpenAI 兼容端点。配置写在 `openclaw.json` 的 `models.providers` 段（非独立的 `models.json`）。

完整 `openclaw.json` 模板见 Step 1。

**api-key 接入点**：`openclaw.json` → `models.providers.glm5-zhipu.apiKey`。格式与现有 doc agent 把 key 写进配置的惯例一致。

---

## 4. 分步实施

### Step 1 — 新建 agent 工作区 `.pi-agent/pptgen/`

#### 1.1 创建目录

```bash
cd /home/youyeetoo/INnet_agent/backend
mkdir -p .pi-agent/pptgen/state
```

#### 1.2 `openclaw.json`（★ 核心配置文件）

> 基于 doc agent 的 `openclaw.json` 改造。必须修改的地方标注了 `REPLACE_...`。

```json
{
  "agents": {
    "defaults": {
      "workspace": "/home/youyeetoo/backend/.pi-agent/pptgen",
      "model": {
        "primary": "glm5-zhipu/glm-5.2"
      },
      "timeoutSeconds": 300
    },
    "list": [
      {
        "id": "pptgen",
        "name": "pptgen",
        "workspace": "/home/youyeetoo/backend/.pi-agent/pptgen",
        "agentDir": "/home/youyeetoo/backend/.pi-agent/pptgen",
        "model": "glm5-zhipu/glm-5.2",
        "skills": [],
        "skillsLimits": {
          "maxSkillsPromptChars": 0
        },
        "description": "PI PPT Agent — presentation generation with ppt-master workflow",
        "tools": {
          "profile": "minimal"
        }
      }
    ]
  },
  "gateway": {
    "mode": "local",
    "auth": {
      "mode": "token",
      "token": {
        "source": "env",
        "provider": "default",
        "id": "PI_AGENT_TOKEN"
      }
    },
    "port": 18792,
    "bind": "loopback",
    "tailscale": {
      "mode": "off",
      "resetOnExit": false
    },
    "http": {
      "endpoints": {
        "chatCompletions": {
          "enabled": true
        },
        "responses": {
          "enabled": true
        }
      }
    },
    "controlUi": {
      "allowInsecureAuth": true,
      "dangerouslyDisableDeviceAuth": true
    }
  },
  "session": {
    "dmScope": "per-channel-peer"
  },
  "tools": {},
  "models": {
    "mode": "merge",
    "providers": {
      "glm5-zhipu": {
        "baseUrl": "https://open.bigmodel.cn/api/paas/v4",
        "api": "openai-completions",
        "models": [
          {
            "id": "glm-5.2",
            "name": "GLM-5.2 (Zhipu)",
            "contextWindow": 131072,
            "maxTokens": 8192,
            "input": ["text"],
            "cost": {
              "input": 0,
              "output": 0,
              "cacheRead": 0,
              "cacheWrite": 0
            },
            "reasoning": false,
            "compat": {
              "supportsTools": true,
              "supportsStore": false,
              "supportsStrictMode": false,
              "supportsUsageInStreaming": false,
              "supportsDeveloperRole": false
            }
          }
        ],
        "apiKey": "REPLACE_WITH_GLM_API_KEY",
        "timeoutSeconds": 900
      }
    }
  },
  "plugins": {
    "entries": {
      "backend-bridge": {
        "enabled": true,
        "config": {
          "baseUrl": "http://127.0.0.1:8000",
          "serviceToken": "change-me-internal-service-token",
          "traceDir": "/home/youyeetoo/backend/.pi-agent/pptgen/state"
        }
      }
    },
    "load": {
      "paths": [
        "/home/youyeetoo/backend/.openclaw/plugins/backend-bridge"
      ]
    }
  }
}
```

> - `"skills": []` — 暂不加载预置 Skill。agent 的行为由 `AGENTS.md` 人设驱动，无需额外 Skill 包。
>   ppt-master 的规范/约束在 `AGENTS.md` 中描述即可。
> - `"apiKey": "REPLACE_WITH_GLM_API_KEY"` — 填入智谱控制台获取的 GLM-5.2 API Key。
> - 模型 id `glm-5.2` 以智谱控制台实际名称为准（控制台名不同时改 `models[0].id`）。

#### 1.3 `AGENTS.md`

```markdown
# PPT Generation Agent

你是 PPT 生成专家。根据用户主题或素材，按 PPT Master 规范产出演示文稿。

## 工作流程
1. 理解需求（主题/素材/页数/画幅），如有素材先提炼要点。
2. 产出设计规范（design_spec）：画幅、配色、字体、页数、每页结构。
3. 逐页产出**项目规范化 SVG**（遵循 ppt-master 的 SVG 中间语言：用无单位 px 字号、
   受限元素/属性集），每页一个完整 `<svg>`。
4. 输出结构化的「页面清单 + 每页 SVG 源码」供后端渲染。

## 重要约束
- 你**不直接执行脚本/写文件**；SVG 与规范由后端 pipeline 落盘并调用 ppt-master 脚本渲染。
- 严格遵循 ppt-master 的 SVG 规范（元素/属性/单位受限），不要用浏览器任意 SVG 写法。
- 不搜索知识库、不做语音处理。
```

#### 1.4 `HEARTBEAT.md`（空文件）

```bash
echo "" > .pi-agent/pptgen/HEARTBEAT.md
```

#### 1.5 `IDENTITY.md`

```markdown
# PPT Generation Agent
```

> 验证点：`ls .pi-agent/pptgen/` 应看到 `openclaw.json  AGENTS.md  HEARTBEAT.md  IDENTITY.md  state/`。

---

### Step 2 — 独立启动脚本 `start_pptgen.sh`

> <span style="color:red">**不修改 `start_all.sh`**。新建独立脚本，与现有 agent 完全隔离。</span>

```bash
#!/bin/bash
set -euo pipefail
# 启动 PI Agent pptgen :18792
# 用法: bash /home/youyeetoo/backend/start_pptgen.sh

export PATH="$HOME/.npm-global/bin:$PATH"
export PI_AGENT_TOKEN="${PI_AGENT_TOKEN:-pi-agent-local-token}"

BACKEND_DIR="/home/youyeetoo/backend"
mkdir -p "$BACKEND_DIR/.pi-agent/pptgen/state"

OPENCLAW_CONFIG_PATH="$BACKEND_DIR/.pi-agent/pptgen/openclaw.json" \
  OPENCLAW_STATE_DIR="$BACKEND_DIR/.pi-agent/pptgen/state" \
  nohup openclaw gateway --port 18792 --bind loopback \
  > "$BACKEND_DIR/data/pi-agent-pptgen.log" 2>&1 &

PID=$!
echo "$PID" > "$BACKEND_DIR/data/pi-agent-pptgen.pid"
echo "pptgen agent started on :18792, PID: $PID"
```

启动与停止：

```bash
# 启动
bash /home/youyeetoo/backend/start_pptgen.sh

# 停止
kill $(cat /home/youyeetoo/backend/data/pi-agent-pptgen.pid)

# 验证
curl -s http://127.0.0.1:18792/health && echo " OK" || echo " FAIL"
```

> **依赖确认**：`openclaw` CLI 已安装在 `~/.npm-global/bin/openclaw`（Node.js ESM）。
> 若未安装或路径不同，先 `npm install -g openclaw`。

---

### Step 3 — 放置 ppt-master skill 文件到板端

把本地 `ppt-master-main/ppt-master-main/skills/ppt-master/` 整个目录拷到板端：

```bash
cd /home/youyeetoo/INnet_agent/backend
mkdir -p app/PPT-master/skill
# 从本地机器 scp 过来（示例，路径以实际为准）：
scp -r ppt-master-main/ppt-master-main/skills/ppt-master youyeetoo@192.168.0.11:/home/youyeetoo/INnet_agent/backend/app/PPT-master/skill/ppt-master
```

安装 ppt-master 的 Python 依赖到后端虚拟环境：

```bash
cd /home/youyeetoo/INnet_agent/backend
.venv/bin/pip install -r app/PPT-master/skill/ppt-master/requirements.txt
# 关键依赖：python-pptx, XlsxWriter, PyMuPDF, Pillow, numpy, flask(可选)
# aarch64 全部可装（PyMuPDF/Pillow/numpy 均有 aarch64 wheel）
```

> 脚本调用路径统一用绝对路径：
> `app/PPT-master/skill/ppt-master/scripts/svg_to_pptx.py` 等。

---

### Step 4 — 新建后端模块 `app/PPT-master/`（镜像 `docs_pipeline/` 的 LangGraph + SSE 模式）

> 注意：`docs_pipeline/core.py` 用的是独立模型服务器（`:8002`/`:8093`），不是 OpenClaw agent。
> 本模块的 `nodes.py` 改用 `client.py`（`PiAgentClient` → pptgen agent `:18792` / `/v1/responses`）。
> 但 **router / runner / graph / state / sse_bridge 的 LangGraph + SSE 模式完全照搬**。

目录结构（全部在已有的空目录 `app/PPT-master/` 下新增）：

```
app/PPT-master/
├── __init__.py        # 导出 router, run_pipeline_stream
├── router.py          # SSE 端点 POST /ppt-master/generate
├── client.py          # PiAgentClient → :18792, model="openclaw/pptgen"
├── runner.py          # LangGraph runner（astream → asyncio.Queue → SSE 生成器）
├── nodes.py           # 各步骤节点
├── state.py           # PipelineState(TypedDict) / initial_state
├── graph.py           # build_graph() → StateGraph + InMemorySaver
├── sse_bridge.py      # make_sse_event()（从 docs_pipeline 同文件照抄）
├── prompts/           # 可选：给 agent 用的约束提示词
└── skill/             # Step 3 已放置的 ppt-master 脚本目录
```

#### 4.1 `__init__.py`

```python
"""PPT-master — LangGraph-based PPT generation pipeline."""
from app.PPT-master.router import router
from app.PPT-master.runner import run_pipeline_stream
from app.PPT-master.state import PipelineState, initial_state

__all__ = [
    "router",
    "run_pipeline_stream",
    "PipelineState",
    "initial_state",
]
```

#### 4.2 `client.py`（★ 已修正：含 `model` 字段）

```python
"""PPT Agent 客户端 — 指向 pptgen(:18792)."""
import json
import logging
from typing import AsyncGenerator

from app.services.pi_agent_client.base_client import PiAgentClient, _clean_delta, AgentUnavailable

logger = logging.getLogger(__name__)

PPT_AGENT_URL = "http://127.0.0.1:18792"
_ppt_client = PiAgentClient(PPT_AGENT_URL, timeout=900)


def _parse_response_chunk(line: str) -> str | None:
    """解析 /v1/responses SSE chunk（照 doc_client.py 同逻辑）."""
    if not line.startswith("data: "):
        return None
    data_str = line[6:]
    if data_str == "[DONE]":
        return "__DONE__"
    try:
        obj = json.loads(data_str)
        evt = obj.get("type", "")
        if evt in ("response.error", "error", "response.failed"):
            err = obj.get("message", "") or obj.get("error", {}).get("message", "")
            logger.warning("pptgen SSE error: %s", err)
            return "__ERROR__"
        if evt == "response.output_item.added":
            item = obj.get("item", {})
            if item.get("type") == "function_call":
                return None
        if evt == "response.output_text.delta":
            return _clean_delta(obj.get("delta", ""))
        if evt in ("response.output_text.done", "response.completed"):
            return "__DONE__"
    except (json.JSONDecodeError, KeyError):
        pass
    return None


async def call_ppt_agent(
    content: str,
) -> AsyncGenerator[str, None]:
    """调用 pptgen agent，走 /v1/responses SSE 流。"""
    async for sse_line in _ppt_client.post_sse_stream(
        "/v1/responses",
        {
            "model": "openclaw/pptgen",    # ★ 必须（格式: openclaw/<agent_id>）
            "input": content,
            "stream": True,
        },
    ):
        text = _parse_response_chunk(sse_line)
        if text == "__DONE__":
            break
        if text == "__ERROR__":
            raise AgentUnavailable("pptgen agent returned error event")
        if text:
            yield text
```

> 关键点：
> - `"model": "openclaw/pptgen"` 必须包含，值与 `openclaw.json` 的 `agents.list[].id` 对应。
> - 复用了 `_clean_delta` 清洗特殊 token（`<|endoftext|>` 等），与 doc/chat client 保持一致。
> - 鉴权由 `PiAgentClient._headers()` 自动加 `Authorization: Bearer <PI_AGENT_TOKEN>`。

#### 4.3 `state.py`

```python
"""PipelineState — PPT-master pipeline 全局状态."""
from typing import TypedDict, Annotated
import operator


class PipelineState(TypedDict, total=False):
    # === 输入 ===
    user_input: str
    page_count: int
    page_format: str
    sources: list[str]

    # === 节点输出 ===
    design_spec: str               # 设计规范 Markdown
    svg_pages: Annotated[list[dict], operator.add]  # 每页 SVG 资源列表
    current_page: int

    # === 导出 ===
    pptx_path: str
    pptx_size: int
    pptx_valid: bool

    # === 控制 ===
    status: str
    graceful_error: str | None
    task_id: str
    user_id: int


def initial_state(
    user_input: str,
    page_count: int = 8,
    page_format: str = "ppt169",
    sources: list[str] | None = None,
    task_id: str = "",
    user_id: int = 1,
) -> PipelineState:
    return PipelineState(
        user_input=user_input,
        page_count=page_count,
        page_format=page_format,
        sources=sources or [],
        design_spec="",
        svg_pages=[],
        current_page=1,
        pptx_path="",
        pptx_size=0,
        pptx_valid=False,
        status="starting",
        graceful_error=None,
        task_id=task_id,
        user_id=user_id,
    )
```

#### 4.4 `router.py`

```python
"""FastAPI router — PPT-master SSE endpoint."""
import logging
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.PPT-master.runner import run_pipeline_stream

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ppt-master"])


class PPTGenRequest(BaseModel):
    user_input: str = Field(..., min_length=2, description="主题或素材说明")
    page_count: int = Field(default=8, ge=1, le=30, description="页数")
    page_format: str = Field(default="ppt169", description="画幅，如 ppt169/ppt43")
    sources: list[str] = Field(default_factory=list, description="素材文件路径（可选）")


@router.post("/ppt-master/generate")
async def ppt_generate(req: PPTGenRequest, current_user=Depends(get_current_user)):
    """新建 PPT 生成任务，返回 SSE 流."""

    async def event_generator():
        async for sse in run_pipeline_stream(
            user_input=req.user_input,
            page_count=req.page_count,
            page_format=req.page_format,
            sources=req.sources,
            user_id=current_user.id,
        ):
            yield sse

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
```

#### 4.5 `sse_bridge.py`（照抄 `docs_pipeline/sse_bridge.py`）

```python
"""SSE bridge — graph events → SSE protocol."""
import json
import logging

logger = logging.getLogger(__name__)


def make_sse_event(event_type: str, data: dict) -> str:
    """Format a single SSE event string."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"
```

#### 4.6 `graph.py`

```python
"""LangGraph StateGraph 构建 — PPT-master pipeline."""
import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver

from app.PPT-master.state import PipelineState
from app.PPT-master.nodes import (
    parse_request_node,
    generate_spec_node,
    generate_svg_node,
    export_pptx_node,
)

logger = logging.getLogger(__name__)


def build_graph() -> StateGraph:
    builder = StateGraph(PipelineState)

    builder.add_node("parse_request", parse_request_node)
    builder.add_node("generate_spec", generate_spec_node)
    builder.add_node("generate_svg", generate_svg_node)
    builder.add_node("export_pptx", export_pptx_node)

    builder.set_entry_point("parse_request")
    builder.add_edge("parse_request", "generate_spec")
    builder.add_edge("generate_spec", "generate_svg")
    builder.add_edge("generate_svg", "export_pptx")
    builder.add_edge("export_pptx", END)

    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)
    logger.info("PPT-master graph compiled")
    return graph
```

#### 4.7 `runner.py`

```python
"""LangGraph pipeline runner — astream + asyncio.Queue → SSE generator."""
import asyncio
import logging
import uuid
from datetime import datetime

from app.PPT-master.state import PipelineState, initial_state
from app.PPT-master.graph import build_graph
from app.PPT-master.nodes import set_sse_queue
from app.PPT-master.sse_bridge import make_sse_event

logger = logging.getLogger(__name__)
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run_pipeline_stream(
    user_input: str,
    page_count: int = 8,
    page_format: str = "ppt169",
    sources: list[str] | None = None,
    task_id: str | None = None,
    user_id: int = 1,
):
    """运行 pipeline，yield SSE 事件字符串."""
    if task_id is None:
        task_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]

    state = initial_state(user_input, page_count, page_format, sources, task_id, user_id)
    graph = _get_graph()
    queue = asyncio.Queue(maxsize=4)
    set_sse_queue(queue)

    graph_task = asyncio.ensure_future(_run_graph(state, graph, queue))

    try:
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=900)
            if event is None:
                break
            if event["type"] in ("done", "fallback"):
                yield make_sse_event(event["type"], event["data"])
                break
            else:
                yield make_sse_event(event["type"], event["data"])
    except asyncio.TimeoutError:
        yield make_sse_event("fallback", {"message": "PPT 生成超时，请稍后重试"})
    finally:
        if not graph_task.done():
            graph_task.cancel()

    logger.info("PPT pipeline stream ended for task %s", task_id)


async def _run_graph(state: PipelineState, graph, queue: asyncio.Queue):
    try:
        config = {"configurable": {"thread_id": state["task_id"]}}
        async for chunk in graph.astream(state, config, stream_mode="updates"):
            for node_name, node_state in chunk.items():
                logger.debug("Node %s completed", node_name)
                status = node_state.get("status", "")
                if status == "done":
                    await queue.put({"type": "done", "data": node_state})
                    return
                elif status == "graceful_fallback":
                    await queue.put({"type": "fallback", "data": node_state})
                    return
        await queue.put({"type": "done", "data": state})
    except Exception as e:
        logger.exception("Graph execution failed: %s", e)
        await queue.put({"type": "fallback", "data": {"message": "服务繁忙，请稍后重试"}})
    finally:
        await queue.put(None)  # Sentinel
```

#### 4.8 `nodes.py`（pipeline 步骤骨架）

```python
"""LangGraph 节点函数 — PPT-master pipeline."""
import asyncio
import contextvars
import json
import logging
import os
import subprocess
import uuid
from pathlib import Path

from app.PPT-master.state import PipelineState
from app.PPT-master.client import call_ppt_agent

logger = logging.getLogger(__name__)

# ═══ SSE context ───
_sse_queue_ctx: contextvars.ContextVar = contextvars.ContextVar("sse_queue", default=None)

def set_sse_queue(queue: asyncio.Queue) -> None:
    _sse_queue_ctx.set(queue)

def get_sse_queue() -> asyncio.Queue | None:
    return _sse_queue_ctx.get(None)

async def _push_sse(event_type: str, data: dict) -> None:
    queue = get_sse_queue()
    if queue:
        await queue.put({"type": event_type, "data": data})

# ═══ 工具函数 ───
PROJECTS_ROOT = Path(__file__).resolve().parent.parent.parent  # backend/

def _abs_script(rel_path: str) -> str:
    """project-relative → absolute."""
    return str(PROJECTS_ROOT / rel_path)


# ═══ 节点 ───

async def parse_request_node(state: PipelineState) -> PipelineState:
    """Step 0: 解析请求，初始化项目目录."""
    name = f"pptgen_{uuid.uuid4().hex[:8]}"
    proj_dir = PROJECTS_ROOT / "app" / "PPT-master" / "projects" / name
    proj_dir.mkdir(parents=True, exist_ok=True)
    await _push_sse("progress", {"step": "parse", "project": name})
    return {
        **state,
        "status": "parsed",
        "task_id": state.get("task_id", name),
    }


async def generate_spec_node(state: PipelineState) -> PipelineState:
    """Step 1: 调 pptgen agent 产设计规范."""
    await _push_sse("progress", {"step": "spec", "message": "正在规划设计规范…"})
    prompt = f"请为以下内容规划 PPT 设计规范（画幅：{state['page_format']}，{state['page_count']} 页）：\n\n{state['user_input']}\n\n产出 design_spec：画幅、配色、字体、每页标题和结构要点。"
    spec_parts = []
    async for chunk in call_ppt_agent(prompt):
        spec_parts.append(chunk)
    spec = "".join(spec_parts)
    await _push_sse("spec", {"design_spec": spec[:500]})
    return {**state, "design_spec": spec, "status": "spec_done"}


async def generate_svg_node(state: PipelineState) -> PipelineState:
    """Step 2: 调 pptgen agent 逐页生规范 SVG."""
    total = state["page_count"]
    await _push_sse("progress", {"step": "svg", "current": 1, "total": total})
    prompt = (
        f"设计规范：\n{state['design_spec']}\n\n"
        f"请逐页产出项目规范化 SVG（共 {total} 页），每页一个完整 <svg viewBox='0 0 1280 720' ...>。"
        f"要求：无单位 px 字号、受限元素/属性集、项目色彩/字体一致。"
        f"以 JSON 数组输出，格式：[\n  {\"page\": 1, \"title\": \"...\", \"svg\": \"<svg ...>...</svg>\"},\n  ...\n]"
    )
    response_parts = []
    async for chunk in call_ppt_agent(prompt):
        response_parts.append(chunk)
    raw = "".join(response_parts)

    try:
        pages = json.loads(raw)
    except json.JSONDecodeError:
        pages = [{"page": 1, "title": "幻灯片", "svg": raw}]

    # 落盘 SVG 到项目目录
    proj_name = state.get("task_id", "default")
    svg_dir = PROJECTS_ROOT / "app" / "PPT-master" / "projects" / proj_name / "svg_output"
    svg_dir.mkdir(parents=True, exist_ok=True)
    for p in pages:
        fname = svg_dir / f"page_{p['page']:02d}.svg"
        fname.write_text(p.get("svg", ""), encoding="utf-8")

    await _push_sse("progress", {"step": "svg_done", "current": total, "total": total})
    return {**state, "svg_pages": pages, "status": "svg_done"}


async def export_pptx_node(state: PipelineState) -> PipelineState:
    """Step 3: subprocess 跑 ppt-master 脚本导出 PPTX."""
    proj_name = state.get("task_id", "default")
    proj_dir = PROJECTS_ROOT / "app" / "PPT-master" / "projects" / proj_name
    await _push_sse("progress", {"step": "export", "message": "正在导出 PPTX…"})

    try:
        # finalize_svg
        subprocess.run(
            ["python3", _abs_script("app/PPT-master/skill/ppt-master/scripts/finalize_svg.py"), str(proj_dir)],
            check=True, capture_output=True, timeout=300,
        )
        # svg_to_pptx
        subprocess.run(
            ["python3", _abs_script("app/PPT-master/skill/ppt-master/scripts/svg_to_pptx.py"), str(proj_dir)],
            check=True, capture_output=True, timeout=300,
        )
        # 找产出
        exports_dir = proj_dir / "exports"
        pptx_files = sorted(exports_dir.glob("*.pptx"), key=os.path.getmtime, reverse=True) if exports_dir.exists() else []
        pptx_path = str(pptx_files[0]) if pptx_files else ""
        pptx_size = os.path.getsize(pptx_path) if pptx_path else 0

        await _push_sse("done", {"pptx_path": pptx_path, "size": pptx_size, "valid": True})
        return {**state, "pptx_path": pptx_path, "pptx_size": pptx_size, "pptx_valid": bool(pptx_path), "status": "done"}
    except subprocess.CalledProcessError as e:
        logger.error("Export failed: %s", e.stderr.decode()[:500])
        await _push_sse("fallback", {"message": f"PPTX 导出失败: {e.stderr.decode()[:200]}"})
        return {**state, "pptx_valid": False, "status": "graceful_fallback"}
```

---

### Step 5 — 注册路由（`app/main.py` 仅追加 2 行）

> <span style="color:red">**只追加，不修改已有 import 和 include_router。追加位置紧跟在 `docs_pipeline` 相关行之后。**</span>

**位置 1**（import 区，在 `from app.docs_pipeline import router as docs_pipeline_router` 行后追加 1 行）：
```python
from app.PPT-master import router as ppt_master_router
```

**位置 2**（路由注册区，在 `app.include_router(docs_pipeline_router, prefix=API)` 行后追加 1 行）：
```python
app.include_router(ppt_master_router,   prefix=API)
```

**重启后端使路由生效**：
```bash
# 查找并重启 uvicorn
kill $(lsof -ti:8000) 2>/dev/null
cd /home/youyeetoo/INnet_agent/backend && nohup python run.py > data/server.log 2>&1 &
# 验证新路由
curl -s http://127.0.0.1:8000/docs | grep -o ppt-master
```

---

## 5. API-key 接入点汇总

| 用途 | 是否必需 | 配置位置 |
|---|---|---|
| **GLM-5.2（PPT 推理生成）** | **必需** | `.pi-agent/pptgen/openclaw.json` → `models.providers.glm5-zhipu.apiKey` |
| ppt-master 生图（gpt-image-2 等） | 可选 | ppt-master 的 `.env`（`IMAGE_BACKEND` + 提供商 key） |
| 旁白 TTS / 图库搜索 | 可选 | ppt-master 的 `.env` |

> **最小可行配置 = 只填 GLM-5.2 的 key**，即可出纯文字/形状 PPT。生图/旁白是增强项。

---

## 6. 风险与注意（已校准）

1. **P0 修正**：Agent 主配置是 `openclaw.json`（不是 `models.json`）；client 调 agent 的 payload 必须含 `"model": "openclaw/pptgen"`；启动命令是 `openclaw gateway` 走 npm-global。
2. **P1 注意**：`PiAgentClient` 的 Bearer 鉴权依赖 `PI_AGENT_TOKEN` env 变量（`start_pptgen.sh` 已设）；`openclaw` CLI 在 `~/.npm-global/bin/`（需确认存在）。
3. **子网差异**：`192.168.10.212` vs `192.168.0.212`（以板端实际为准）。pptgen 用 GLM 云端不受影响。
4. **端口冲突**：`:18792` 需空闲（已用 18790/18791）。
5. **模型质量**：GLM-5.2 写规范 SVG 质量优于 35B，但复杂图表/版式仍可能需人工精修（ppt-master 固有特性）。
6. **无头确认**：agent 一次性产出 spec + SVG，pipeline 不卡交互确认。
7. **GLM 兼容性**：模型 id 以智谱控制台为准；若 `supportsTools` 行为差异，按 base_client 容错处理。
8. **`docs_pipeline/core.py` 用独立模型服务器**（:8002/:8093），不走 OpenClaw。PPT-master 模块用 `client.py` → pptgen agent 替代，架构更简单。
9. **已有文件安全**：start_all.sh、.env、config.yaml、app/services/pi_agent_client/、.pi-agent/chat/、.pi-agent/doc/ 等所有已有文件**一概不动**。

---

## 7. 落地顺序建议

### 第一阶段：验证 agent 能通（不涉及后端模块）
- [ ] Step 1 — 创建 `.pi-agent/pptgen/`（openclaw.json + AGENTS.md + HEARTBEAT + IDENTITY + state/）
- [ ] 填入 GLM-5.2 apiKey
- [ ] Step 2 — `bash start_pptgen.sh` 拉起，`curl :18792/health` 确认存活
- [ ] 手动 curl 对话验证（`curl -X POST :18792/v1/responses -H "Authorization: Bearer pi-agent-local-token" -d '{"model":"openclaw/pptgen","input":"你好"}:'`）

### 第二阶段：打通后端生成链
- [ ] Step 3 — 放 ppt-master skill 到板端 + `pip install` 依赖
- [ ] Step 4 — 部署 `app/PPT-master/` 下所有文件
- [ ] Step 5 — `main.py` 追加 2 行 + 重启后端
- [ ] 验证 `/api/v1/ppt-master/generate` 出现在 `/docs` Swagger
- [ ] 端到端：POST 主题 → SSE 推进度 → `exports/*.pptx` 产出 → PowerPoint/WPS 打开可编辑

### 第三阶段：集成到 `start_all.sh`（可选，稍后）
- [ ] 如果确认 agent 稳定后，把 `start_pptgen.sh` 的内容追加到 `start_all.sh` 末尾（独立新增段，不删不改已有内容）
