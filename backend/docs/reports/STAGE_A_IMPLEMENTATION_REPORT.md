# PPT-master 阶段 A 实施报告

日期：2026-07-17
结论：**通过阶段 A 验收**。生产服务已部署为单 Uvicorn worker，受控 1 页 PPT 冒烟、授权下载、越权拒绝、幂等、并发拒绝、结构校验、超时进程树清理和日志脱敏全部通过。未扩展 Dyad 式业务功能。

## 1. 基线与回滚保障

- 确认基线：`main@e692086acde4fb81b36c12a418580a2f55e2e179`。
- 创建注释 tag：`stage-a-baseline-20260717-e692086a`。
- 阶段分支：`codex/stage-a`；实施通过后以 `--ff-only` 快进到 `main`。
- 项目外备份目录权限为 `700`，备份文件权限为 `600`。备份包括：Git/进程/端口记录、关键配置哈希、启动命令、迁移前数据库一致性副本、停止服务后的 SQLite backup、日志、运行 journal 和可恢复的演示 PPTX。
- 基线父进程为 PID `149890`，当时存在两个 Uvicorn worker；阶段 A 最终父进程为 PID `190955`，仅一个 `python run.py` 进程监听 8000。
- 原有演示 PPTX 已移动至项目外可恢复备份，没有永久删除。
- 非中断式回滚演练通过：基线应用可导入并注册 74 条路由；恢复副本 `PRAGMA integrity_check=ok`，文件记录为 593；演练临时目录已安全删除，证据归档保留为权限 `600` 的项目外文件。

## 2. Git 提交

以下为阶段 A 实施提交；本报告自身的交付提交不计入实现提交列表。

| 类别 | Commit | 说明 |
|---|---|---|
| security | `64c2eeb0` | 拒绝 sources，增加 SVG/XML 资源安全门 |
| file-download | `7e49ab8c` | 文件登记、所有权与授权下载 |
| validation | `36b0a933` | 结构化 SVG/PPTX 阻断校验 |
| concurrency | `ae04e53e` | 单机并发、SQLite 幂等、超时与配额 |
| review-fix | `2735eba2` | 补齐 MIME、校验和、权限及 CSS/XML 安全边界 |
| security | `2ac38769` | 取消跟踪运行身份、配置备份和内置虚拟环境 |
| security | `2e8e5144` | PPT 专用运行环境迁移到项目外 |
| security | `78da4ba8` | 取消跟踪 SQLite `-shm/-wal` |
| security | `a03bbd73` | 启动日志不再输出运行配置路径 |
| smoke-test | `489bc242` | 两用户生产冒烟脚本与脱敏证据 |

## 3. 修改文件清单

业务与基础设施源码（不展开列出被移除的 6,234 个虚拟环境文件及历史敏感备份）：

- 配置与启动：`.gitignore`、`.env.example`、`config.example.yaml`、`app/config.py`、`run.py`
- 数据模型与迁移：`app/models.py`、`app/database.py`
- PPT 入口与执行：`app/PPT_master/router.py`、`runner.py`、`nodes.py`、`state.py`
- 新增安全与控制：`app/PPT_master/security.py`、`validation.py`、`admission.py`、`subprocesses.py`
- 文件服务：`app/routers/files.py`、`app/services/artifact_service.py`
- 测试：`tests/test_ppt_stage_a_{security,artifacts,validation,concurrency,subprocesses}.py`
- 冒烟与证据：`scripts/stage_a_smoke.py`、`evidence/stage-a-smoke-redacted.json`
- 设计与计划：`docs/superpowers/specs/2026-07-17-ppt-stage-a-design.md`、`docs/superpowers/plans/2026-07-17-ppt-stage-a.md`
- 从当前 Git 树移除：真实 `.env/config.yaml`、配置备份、运行身份文件、6 个 SQLite journal、项目内 `.venv_pptm`。这些内容没有被复制到项目目录。

总变更路径 6,294 个，其中 6,234 个是被取消跟踪的项目内虚拟环境文件；实施源码、测试与文档为小范围独立修改。

## 4. 安全修复结果

- `sources` 只允许空数组；本地路径、URL 和 `file://` 均在请求模型阶段以结构化 422 拒绝。
- SVG/XML 安全门拒绝 DTD、实体、脚本、事件处理器、`foreignObject`、XML stylesheet、CSS `@import`、外部 URL、`file://`、绝对路径、路径穿越、未登记资源及符号链接逃逸。
- 后处理前再次校验项目内资源；产物登记和下载都重新解析真实路径、检查允许根目录和符号链接组件。
- 当前 Git 树密钥模式扫描为 0 命中；历史审计确认 31 个敏感路径分布在 16 个历史 commit 中。依照授权，没有重写 Git 历史。
- JWT 已本机轮换；运行 `.env/config.yaml`、三份身份文件和 PPT 专用环境已迁移至项目外。配置、身份、数据库和日志为 `600`，运行/项目目录为 `700`。
- 检测到 9 个第三方凭据槽位，需要在第三方控制台人工轮换；代码和文件治理已完成，未因此阻塞部署，也未在本报告输出名称或值。
- 新阶段 A 日志扫描：密钥 0、服务器绝对路径 0、敏感文件名 0。

## 5. 数据库与文件登记方案

在现有 `files` 表上执行可重复的只增量迁移：

- `owner_user_id INTEGER`
- `project_id TEXT`
- `task_id TEXT`
- `real_path TEXT`
- `mime_type TEXT`
- `size INTEGER`
- `sha256 TEXT`
- `expires_at DATETIME`
- 复用原有 `created_at`

新增 `ppt_generation_requests` 表，以 `(user_id, request_id)` 唯一约束保存 `accepted/running/completed/failed` 状态、任务 ID、文件 ID、终态事件和终态载荷。

迁移前副本和实际迁移均为 `integrity_check=ok`；既有 `files` 记录保持 593 条，新增表初始为空。迁移只新增列、表和兼容回填，不删除表、列或业务行。`ArtifactService` 负责登记、所有权、允许根目录、有效期、大小/sha256 完整性、MIME、下载路径和过期清理。默认 PPT 产物有效期为 7 天；当前已提供清理方法，定时调度列入后续 P1。

## 6. API 契约变化

### `POST /api/v1/ppt-master/generate`

- 强制 JWT。
- 请求体上限 64 KiB；`user_input` 2–20,000 字符；`page_count` 1–12；`page_format` 仅 `ppt169/ppt43`。
- `sources` 必须为 `[]`。
- 必须提供合法 `request_id` 或 `Idempotency-Key`；两者同时存在时必须一致。
- 同一用户相同幂等键：运行中返回 409；完成或失败后直接重放终态，不重复调用模型。
- 全局忙返回 429 和 `Retry-After`；项目总配额超限返回 507；请求过大返回 413。

成功 SSE `done`：

```json
{
  "file_id": 594,
  "download_url": "/api/v1/files/594/download",
  "size": 14469,
  "sha256": "<sha256>",
  "valid": true,
  "validation_result": {
    "passed": true,
    "warnings": [],
    "errors": [],
    "blocking_errors": []
  }
}
```

`done` 不返回 `real_path/filepath/project_dir`。失败不会用 demo、部分导出或 fallback 文件伪装成功。

### `GET /api/v1/files/{file_id}/download`

- 强制 JWT；只接受 `file_id`，不接受路径参数。
- 只允许登记文件且校验所有者、有效期、允许根目录、符号链接、大小和 sha256。
- 非所有者与非法登记统一返回 404；过期返回 410；未认证返回 401。
- 返回登记 MIME、附件文件名、`nosniff` 和 `private, no-store`；响应不暴露真实路径。

## 7. Validation 语义

统一结果为 `passed/warnings/errors/blocking_errors`。`valid=true` 必须同时满足：文件存在且非符号链接、PPTX ZIP 可读、关键 OOXML 完整且 XML 可解析、页数符合预期、SVG 安全门通过、导出无阻断错误。任何 `blocking_errors` 都强制 `valid=false`，warning 不再等同 success。

## 8. 并发、超时和配额

- `run.py` 固定 `workers=1`；生产证据为一个 `python run.py` 和一个 8000 listener。
- 全局 PPT 并发 1，单用户并发 1。该内存 limiter 在单 worker 前提下等于部署全局限制；不得扩为多 worker。
- SQLite 幂等记录跨请求持久化，完成终态可重放。
- 任务总超时 900 秒；所有子进程使用独立进程组，超时/取消时先 TERM 再 KILL 整棵进程树。
- 单项目配额 200 MiB，所有 PPT 项目总配额 2 GiB；失败项目移除，只在项目外保留脱敏诊断。

限制：这是经批准的临时单节点方案，不支持多 Uvicorn worker 或多实例；下一阶段扩容前必须换成 Redis 计数/锁或独立任务 worker。

## 9. 生产冒烟证据

两个随机临时用户、1 页、`sources=[]`、`ppt169`、简单 AI 安全主题：

| 检查 | 结果 |
|---|---|
| 未认证生成 | 401 |
| 非法 page_count | 422 |
| 非空 sources（含 `file://`） | 422 |
| 同幂等键运行中重复提交 | 409 |
| 并发第二任务 | 429，未进入模型 |
| SSE | `progress/spec/validate/done` 完整；27.771 秒 |
| done 路径泄露 | 无；键仅为 file/download/size/hash/valid/validation |
| 用户 A 下载 | 200 |
| 用户 B 下载同一 file_id | 404 |
| 未认证下载 | 401 |
| 幂等重放 | 200；0.032 秒；同一 file_id |
| PPTX | ZIP/OOXML 完整、1 页、原生 DrawingML 文本与形状可编辑 |
| validation | passed=true，0 warnings/errors/blocking_errors，valid 一致 |
| 超时子进程 | 进程组测试通过，无遗留子进程 |
| 日志 | 密钥/绝对路径/敏感文件名均 0 命中 |

脱敏机器证据见 `evidence/stage-a-smoke-redacted.json`。PPTX 本体未提交 Git；项目外证据备份和本地下载副本的 sha256 与 `done` 一致。冒烟完成后，只删除了本次创建的 2 个测试用户、1 条幂等记录、1 条文件记录及对应 `pptgen_` 项目目录；证据 PPTX可从项目外备份恢复。

## 10. 测试与部署证据

- 阶段 A 专项测试：50 passed。
- 既有快速回归：19 passed, 1 skipped。
- 数据库：`integrity_check=ok`。
- HTTP：health 200、OpenAPI 200、未认证既有 `/auth/me` 401。
- 生产：单 `python run.py`、单 8000 listener、Git 工作树 clean。
- 权限：项目目录 700、数据库 600、日志 600、外部配置目标 600。

仓库全量测试收集仍有 5 个基线既存错误，来自重复备份测试模块名和缺失的 docs_pipeline 符号；与本次 PPT-master 修改无关，列为 P1 清理项。

## 11. 回滚步骤

紧急回滚使用基线 tag 和项目外数据库 backup，不重写 Git 历史：

1. 记录当前 PID/端口并优雅停止单 worker；确认 8000 已释放。
2. 对当前数据库做新的 SQLite backup，保留阶段 A 后新增数据。
3. 在项目外创建 700 的 detached baseline worktree，只检出基线代码；不要把历史 `.env/config.yaml` 当作运行密钥。
4. 将该 worktree 的 `.env/config.yaml` 和身份文件链接到现有项目外 600 配置；将基线预期的 `.venv_pptm` 链接到项目外 PPT 环境。
5. 用停止服务时保存的 `data_app.db.backup.db` 恢复该 worktree 数据库，执行 `integrity_check` 并确认 593 条基线文件记录。
6. 以原启动环境从 baseline worktree 启动；验证单/旧 worker 预期、8000、health、auth 和非 PPT 接口。
7. 若恢复服务仍失败，保持端口关闭并停止，不覆盖当前阶段 A 数据库，按“服务恢复失败”阻断条件上报。

该流程已非中断演练到“基线应用导入 + 路由装载 + 数据库 restore/integrity”层级；没有为演练中断当前健康生产服务。

## 12. 尚未处理的 P1/P2

### P1

- 在第三方控制台人工轮换 9 个历史暴露凭据槽位，更新项目外配置后重启；当前只完成文件治理。
- Git 历史仍含 31 个敏感路径/16 个 commit；历史重写需另行批准和协作窗口。
- 将 `ArtifactService.cleanup_expired()` 接入受控定时任务，并形成清理审计指标。
- 清理 5 个基线全量测试收集错误和历史备份测试文件。
- 审核并收敛旧文件服务的历史绝对路径兼容根，完成遗留文件迁移。
- 若恢复多 worker/多实例，先迁移到 Redis admission 或独立生成 worker。

### P2

- 监控生成耗时、429、超时、配额、校验阻断率和清理数量。
- 增加 artifact 下载审计、批量过期清理和容量告警。
- 为迁移和回滚增加 CI dry-run 与数据快照校验。

按阶段 A 边界，未增加逐页事件、取消、重放 UI、持续对话或前端正式联调。

## 13. 下一阶段 Legacy Adapter 联调建议

1. 旧前端统一生成入口适配 `request_id/Idempotency-Key`、`sources=[]` 和 409/429 重试提示。
2. SSE adapter 只消费现有 `progress/spec/validate/done/fallback`，不要在此时假设逐页事件。
3. 将旧“服务器路径”字段彻底替换为 `file_id + download_url`，下载请求携带用户 JWT。
4. UI 严格按 `validation_result` 展示 success/warning/failed；`blocking_errors` 不允许下载按钮显示为成功。
5. Legacy 素材先禁用；新素材链只设计 `asset_id`，禁止恢复路径/URL透传。
6. 联调前冻结本报告中的 API 契约，先做 adapter contract tests，再进入真实前端会话。
