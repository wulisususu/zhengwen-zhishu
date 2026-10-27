# InNet_box · 政务办公智能体 / 端侧 AI 平台

> **源码状态：2026-10-27**。本文基于 `main` 当前实现整理，不把演示数据、配置选项或历史部署记录等同于已上线能力。核心政务入口是 `/gov`；原有聊天、文档、知识库、语音与 PPT 模块仍保留在同一仓库。

InNet_box 是采用 **FastAPI + Vue 3** 的智能办公平台。当前重点是“政策依据检索与问答 → 公文起草 → 双层审校 → 人工送审/退回/批准 → 内部 DOCX 导出”。政务功能使用 SQLite 持久化文稿、政策与审核记录，并提供可选的模型服务、OpenClaw 智能体及 PDF 解析适配器。

**重要边界：**
- **不是正式电子公文发文系统**：当前导出的是带标记的内部草稿；正式发文权限、签章和放行流程未实现。人工批准不等于正式发文许可。
- **角色入口不是身份认证**：访问者可以直接选择“起草人”或“审核人”。这是比赛/演示入口，不能用于真实多用户权限隔离或直接暴露在不可信网络。
- **不默认承诺数据不出域**：政务初稿生成、政策问答等通过可配置的 OpenAI 兼容模型 API；示例配置为 `model.mode: cloud_allowed`，调用公网模型意味着请求内容出网。只有配置并核实内网/离线链路、网络策略后，才能作出相应部署声明。

## 功能现状

| 模块 | 当前实现 | 关键限制 |
| --- | --- | --- |
| 政务工作台 `/gov` | 起草、保存、刷新恢复、材料关联、送审、退回、批准、历史记录；后端 SQLite 持久化及版本冲突保护 | 角色入口共用角色账号；不可作为生产身份认证 |
| 通知起草与审校 | 通知字段/版记/表格、模型初稿、规则校验 + `gongwen-kit` 格式机检、问题定位、批准前重检、内部 DOCX | 双层自动审校仅覆盖“通知”；需要安装 Node 与 `gongwen-kit` |
| 其他公文文种 | 请示、报告、函、纪要可按既有流程生成内部草稿 | 不具备“通知”的完整双层自动审校；仍需人工审核 |
| 政策库 `/gov/library` | 政策导入、条款切分/检索、来源/版本/状态、人工作废或现行核验、引用到文稿 | 新导入政策默认为未核验，不自动认定为现行有效 |
| 政策问答 `/gov/policy-qa` | 基于已入库条款检索，证据不足时不强行下结论；支持条款引用与原文定位、SSE 接口 | 内容受政策库覆盖范围和模型可用性限制；需人工核验 |
| 政策 PDF | 政策导入支持逐页解析、物理页码与 SHA-256 来源定位；扫描/混合页走原 OCR 路径 | OpenDataLoader 仅在 `policy_pdf.engine: opendataloader` 时启用；普通文件解析链路不随之切换 |
| 旧业务模块 | 对话/文档工作流、OpenClaw、知识库、ASR/TTS、PPT 工作台和增量处理模块代码仍在 | 部分依赖外部模型、独立进程、模板或特定硬件；不能仅凭代码推断服务正在运行 |
| 规划功能 | `/gov/summary`、`/gov/audit-log` 页面占位 | 不是完整的长文总结产品或集中审计日志系统 |

> **测试与部署情况**：仓库有后端 pytest、前端 Vitest、浏览器用例及 2026-10-26 的集成验收记录（见下文）。这些记录证明各自注明的测试范围，不代表每次提交后都做过完整生产环境复测。

## 主要业务流程

```text
选择角色（演示入口 /entry）
   ├─ 起草人：创建通知 → 编辑要素/正文/材料 → 保存
   │           ├─ 生成初稿（需可用模型 API）
   │           ├─ 政策条款检索与引用
   │           ├─ 双层审校（规则 + gongwen-kit）
   │           └─ 提交审核 → 根据退回意见修改 → 重新提交
   └─ 审核人：查看送审文稿 → 退回 / 批准
                                └─ 通知批准前后端重新审校并复核政策依据

已保存文稿 → 导出带“内部草稿”标识的 DOCX
                           × 不支持正式发文、签章或例外放行
```

- 后端执行业务角色、所有权、状态与版本号校验；起草人不能批准自己的文稿，审核人不能代替起草人修改稿件。
- 文稿内容变更会使旧审校结果失效。通知批准时重新运行双层检查；政策引用状态也由后端复核。格式/引用不合格时禁止批准。
- 材料接口支持 `.txt`、`.md`、`.pdf`、`.docx`、`.xlsx`、`.csv`、`.pptx`、`.png`、`.jpg`、`.jpeg`（单文件上限 20 MiB）；**模型生成初稿目前直接读取的关联材料仅限 UTF-8 TXT/Markdown，每份最多 80,000 字节**。允许上传 PDF 并不代表模型生成已经读取 PDF 内容。
- 政策导入和人工核验由审核人或管理员操作；政策依据必须可追踪，未核验、失效与历史版本不得伪装成有效依据。

## 项目结构

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI 入口，注册业务路由
│   │   ├── gov/                   # 政务文稿、角色入口、材料、审批、导出
│   │   ├── policy/                # 条款级政策问答、检索与引用
│   │   ├── gongwen/               # 其他文种的既有公文排版
│   │   ├── routers/               # 登录、政策库、政务公文、文件等 API
│   │   ├── services/
│   │   │   ├── gongwen/           # gongwen-kit 桥接/规则/审校
│   │   │   ├── policy/            # 国务院政策检索、入库、版本与 PDF
│   │   │   ├── llm_chat.py        # 政务共用模型 API 客户端
│   │   │   └── model_policy.py    # 模型出口策略
│   │   ├── docs_pipeline/         # 历史文档生成流水线
│   │   ├── kb/                    # 知识库
│   │   └── PPT_master/            # PPT 服务
│   ├── config.example.yaml       # 后端配置模板
│   ├── .env.example              # 密钥/服务地址模板
│   ├── requirements.txt
│   ├── requirements-pdf.txt      # 政策 PDF 可选依赖
│   ├── scripts/run.py            # FastAPI 单 worker 入口
│   ├── third_party/README.md     # gongwen-kit 安装说明
│   └── tests/
├── web/
│   ├── src/features/gov-office/  # 政务页面、状态与 API 适配器
│   ├── src/features/ppt-workbench/
│   ├── src/views/                # 原业务页面
│   ├── vite.config.js
│   └── package.json
├── docs/                          # 角色入口与集成验收
└── restart_backend.sh             # 特定部署机的运维脚本
```

## 环境与依赖

- **后端**：Python 3（推荐与目标部署环境保持一致），FastAPI、Uvicorn、SQLAlchemy、SQLite；依赖见 `backend/requirements.txt`。大型知识库/PPT/视觉任务可能需要额外模型文件、系统程序或可选依赖。
- **前端**：Vue 3、Vue Router、Pinia、Vite 5、Tailwind CSS、Vitest。项目 `web/.nvmrc` 指定 **Node 24**。
- **通知双层审校/DOCX**：Node >= 18；按 `backend/third_party/README.md` 固定版本安装 `gongwen-kit`。该目录不随 Git 仓库交付；不能通过 `pip install -r requirements.txt` 获得。
- **政策 PDF 可选加速**：`opendataloader-pdf==2.5.15`、Java 11+；默认 `legacy` 不依赖它。实际硬件、字体及 OCR 依赖请按部署目标单独验收。
- **历史聊天/视觉/语音**：OpenClaw、MiniCPM、ASR、TTS 等可能是独立服务，并非启动 FastAPI 就全部自动可用。

## 本地开发启动

下面是从源码启动 API 与网页的**基础步骤**；不是一键恢复特定 RK3588 服务器上全部模型服务的脚本。

### 1. 安装后端与创建配置

```bash
git clone https://github.com/wulisususu/innet-agent-ai-box.git
cd innet-agent-ai-box

python3 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -r backend/requirements.txt

mkdir -p ~/.config/ai-box/backend
cp backend/config.example.yaml ~/.config/ai-box/backend/config.yaml
cp backend/.env.example ~/.config/ai-box/backend/.env
chmod 600 ~/.config/ai-box/backend/.env
```

启动前编辑 `~/.config/ai-box/backend/config.yaml`：
1. 填写**随机生成**的非空 `jwt.secret`（例如用 `python -c 'import secrets; print(secrets.token_urlsafe(48))'` 生成），不要提交密钥。
2. 根据部署网络明确选择 `model.mode`。示例配置使用 `cloud_allowed`，不是离线模式。
3. 配置 `policy`、`gongwen`、`policy_pdf` 的存储路径、工具路径及开关。默认政策数据存于 `backend/data/policy.db`。
4. 需要模型初稿/政策 AI 问答时，在 `.env` 中填写 `EXTERNAL_MODEL_BASE_URL`、`EXTERNAL_MODEL_NAME`、`EXTERNAL_MODEL_API_KEY`；未配置时不能假定生成可用。

`app/config.py` 默认优先读取 `~/.config/ai-box/backend/config.yaml` 和同目录 `.env`（文件存在时），也支持 `BACKEND_CONFIG_FILE`、`BACKEND_ENV_FILE`、`AI_BOX_CONFIG_DIR`。**注意**：`app/services/model_config.py` 的“设置页保存/同步 OpenClaw”路径仍含 `/home/youyeetoo/InNet_box` 等部署机专用常量；在其他机器不要直接套用设置页改模型配置，优先用显式环境变量并按源码校核。

业务用户数据库的实际路径由 `app/database.py` 中的 **`AI_BOX_DATA_DIR`**（默认 `backend/data/app.db`）决定；不要误以为更改 `config.yaml` 中 `database.url` 就能改变当前代码里的 SQLite 引擎路径。生产迁移请先备份两类数据库和上传材料。

### 2. 启动 API

```bash
cd backend
python scripts/run.py
```

默认监听 `0.0.0.0:8000`（可通过 `config.yaml -> server` 修改），使用单 Uvicorn worker。验证：

```bash
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/api/v1/gov/entry
```

第二个接口应返回角色入口配置；业务 API 需要角色会话 JWT。Swagger API 文档通常在 `http://127.0.0.1:8000/docs`。

> 后端入口会导入 PPT/文档/知识库等模块；若干净环境因额外可选库或系统工具缺失而无法启动，应根据缺失模块补齐实际依赖，而不是将“基础依赖安装完成”当作完整部署验收。

### 3. 启动前端

另开终端：

```bash
cd web
npm ci
npm run dev
```

开发入口：`http://127.0.0.1:3000/`（重定向到 `/gov`；未登录会进入 `/entry` 角色选择）。

Vite 开发代理：
- `/api` → `http://localhost:8000`（可由 `VITE_PPT_BACKEND_PROXY` 覆盖）
- `/api/v1/docs-pipeline` → `http://localhost:8003`（可由 `VITE_DOCS_BACKEND_PROXY` 覆盖；优先于通用 `/api`）

生产 `npm run build` 产物**不包含 Vite dev proxy**。部署 `dist/` 时，需要单独配置 `/api` 反向代理与 Vue history 路由回退。不要直接把绑定 `0.0.0.0` 的演示入口和宽松 CORS 后端公开到生产网络。

### 演示数据模式

前端默认使用真实 HTTP 后端，**网络失败不会自动切到 Mock**。需要独立展示静态流程时，显式设置 `VITE_GOV_OFFICE_MODE=demo` 后重新构建/启动；演示行为不等于后端已实现，也不能用于验证持久化或权限。

## 模型与数据出口

| `model.mode` | 本进程模型请求允许的目标 | 适用说明 |
| --- | --- | --- |
| `cloud_allowed` | 配置允许的 HTTP(S) 外部模型 | 可能将请求正文发往公网；示例模板默认使用此模式 |
| `intranet` | loopback + 私有网络地址 | 禁止本进程主动连接公网模型；不能据此证明所有子进程不出网 |
| `offline` | 仅本机 loopback | 不可访问远端模型时明确失败或由相应模块按规则返回无生成结果 |

`AI_BOX_MODEL_MODE` 可以覆盖 YAML 设置；若模式未配置，代码按 `intranet` 处理。策略是**应用层出口检查**，不是操作系统断网证明：OpenClaw 独立进程、第三方工具及外部政策 URL 抓取须另行审查，并在防火墙/路由层设置真实隔离。政策在线搜索只在配置及出口策略允许时工作；不允许联网时仍可使用已导入的本地政策库。

## 关键 API（统一前缀 `/api/v1`）

| 路径 | 用途 |
| --- | --- |
| `GET/POST /gov/entry` | 查询/选择演示起草人或审核人角色，获得 JWT |
| `/gov/documents`、`/gov/documents/{id}/...` | 文稿 CRUD、生成、审校、引用、送审、批准/退回、内部导出 |
| `/gov/materials` | 政务材料上传、关联及授权下载 |
| `/gov/policies`、`/gov/policies/search` | 政策库、状态核验与条款查询 |
| `/gov/notices/review`、`/gov/notices/export` | 独立结构化通知双层审校与内部 DOCX |
| `/gov/docx/check`、`/gov/docx/fix` | 外部 DOCX 格式检查、可选生成修订副本 |
| `/policy/search`、`/policy/qa`、`/policy/qa/stream` | 条款级检索、政策问答及 SSE |
| `/health` | 基础健康检查；仅反映 API 进程，不代表模型均已就绪 |

完整输入字段与响应以 FastAPI `/docs`、`backend/docs/policy-api.md`、`backend/docs/gongwen-api.md` 为准。

## 测试与验收

```bash
# 后端：从 backend 目录执行；pytest 为开发/测试工具
cd backend
python -m pytest tests/test_gov_role_entry.py tests/test_gov_basic_api.py tests/test_gov_gongwen_integration.py tests/test_gov_policy_integration.py -q

# 前端：从 web 目录执行
cd ../web
npm test           # Node 宿主测试 + Vitest
npm run build      # vue-tsc + Vite build
npm run test:browser  # 需要可启动的 Chromium/Chrome 环境
```

此处列出的是**建议执行的命令，不是本次文档修改产生的新测试通过报告**。历史集成证据：
- [角色入口与权限边界](docs/role-entry.md)
- [2026-10-26 完整集成验收](docs/superpowers/2026-10-26-full-integration-acceptance.md)
- [政策检索与导入验收](docs/superpowers/2026-10-26-policy-integration-acceptance.md)

## 已知限制与部署注意

1. **仅内部草稿**：正式发文、数字签章、完整审批授权、忽略问题/例外放行尚未提供；双层审校不代表公文合法合规认证。
2. **角色入口面向演示**：同一角色共用账户，无法区分不同实际起草人/审核人；需要真实使用时应改为组织身份认证、最小权限和网络访问控制。
3. **工具链不全即功能不可用**：`gongwen-kit`、Node、模型 API、政策库与 PDF/OCR 都需分别部署、健康检查。不能用单一 `/health` 证明全功能可用。
4. **PDF/材料能力边界**：政策 PDF 的逐页解析不等于任意文稿附件可直接参与模型生成；扫描页 OCR 质量需人工复核。OpenDataLoader 只作为政策 PDF 的显式可选引擎。
5. **旧脚本含硬编码部署路径**：`backend/scripts/start_all.sh`、`restart_backend.sh` 与部分模型配置引用特定 RK3588 主机/目录、端口或 systemd 服务。迁移机器前必须审查，不建议在新机器上无修改直接运行。
6. **模型出口需独立审计**：公网 API、OpenClaw provider、旧 PPT 生成等链路应分别检查；不能仅凭 `model.mode` 宣称“端侧完全离线、不出域”。
7. **旧模块测试与部署非同一范围**：历史验收重点是政务闭环，不能据此宣称所有 PPT、语音、OpenClaw 或旧业务分支在新环境都通过回归。

## 相关说明

- [政策接口契约](backend/docs/policy-api.md)
- [公文审校接口契约](backend/docs/gongwen-api.md)
- [gongwen-kit 独立安装](backend/third_party/README.md)
- [角色入口](docs/role-entry.md)
- [完整集成验收](docs/superpowers/2026-10-26-full-integration-acceptance.md)

---

项目仍在迭代。文档描述的是仓库中**可定位到的代码路径和明确的能力边界**；部署状态、外部服务连通性、模型效果与正式公文合规性需要在目标环境另行验证。
