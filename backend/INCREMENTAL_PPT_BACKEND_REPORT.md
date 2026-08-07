# PPT 后端逐页工作流第一阶段实施报告

日期：2026-07-19  
基线：`main@e33a09a997c45d6f6f7c5de1003a41bea3ffb79c`  
上线版本：`main@c962943c4533952a87e5aa896bbd9b11322243e5`  
结论：**通过**

## 1. 实施范围与兼容策略

本阶段采用独立端点承载逐页工作流，没有改变生产 Legacy Adapter 的请求模型、事件名或终态载荷。

- 保留：`POST /api/v1/ppt-master/generate`
- 新增：`POST /api/v1/ppt-master/generate-incremental`
- 新增：`GET /api/v1/ppt-master/tasks/{task_id}`
- Legacy 仍发送 `progress/spec/validate/done/fallback`。
- 新旧生成入口仅共享已批准的单 worker 全局/单用户并发闸门。
- 本阶段未增加取消、重放、持续对话或前端业务编排。

增量任务采用后台 producer。SSE 客户端断开不会直接取消任务；事件先写 SQLite，再交给 SSE consumer。单页失败会继续处理后续页，已完成页保留在任务快照和登记文件中。

## 2. API 与事件契约

### 2.1 创建增量任务

`POST /api/v1/ppt-master/generate-incremental`

请求：

```json
{
  "user_input": "string",
  "page_count": 4,
  "page_format": "ppt169",
  "sources": [],
  "request_id": "client-idempotency-key"
}
```

约束：

- 强制 JWT。
- `page_count` 为 1～12。
- 请求体上限 64 KiB。
- `sources` 必须为空；路径、URL 和 `file://` 均不会进入工作流。
- `request_id` 或 `Idempotency-Key` 必填；同用户重复键返回 409 和原 `task_id`，不重复调用模型。
- 全局并发 1、单用户并发 1；超限返回 429 和 `Retry-After: 5`。
- 任务超时 900 秒；子进程沿用进程组超时和进程树清理。

### 2.2 标准 SSE envelope

每个事件均包含：

```json
{
  "event_id": "evt_...",
  "event_type": "slide.completed",
  "task_id": "pptinc_...",
  "project_id": "pptproj_...",
  "sequence": 4,
  "timestamp": "2026-07-19T00:00:00Z",
  "data": {}
}
```

正式里程碑：

1. `planning.started`
2. `planning.completed`
3. `slide.started`
4. `slide.completed`
5. `slide.failed`
6. `validation.completed`
7. `export.ready`
8. `task.completed`
9. `task.failed`

`planning.completed.data`：

```json
{
  "page_count": 4,
  "outline": [{"index": 1, "title": "..."}],
  "design_summary": {"preview": "..."}
}
```

`slide.completed.data`：

```json
{
  "slide_id": "...:slide:1",
  "index": 1,
  "title": "...",
  "status": "completed",
  "preview_file_id": 123,
  "preview_url": "/api/v1/files/123/download",
  "thumbnail_file_id": 123,
  "thumbnail_url": "/api/v1/files/123/download"
}
```

第一版缩略图复用安全登记的 SVG；未返回服务器路径或未登记资源。

`export.ready.data.final_file` 与 `task.completed.data.final_file`：

```json
{
  "file_id": 456,
  "download_url": "/api/v1/files/456/download",
  "size": 25206,
  "sha256": "...",
  "valid": true,
  "validation_result": {
    "passed": true,
    "warnings": [],
    "errors": [],
    "blocking_errors": []
  }
}
```

### 2.3 查询任务

`GET /api/v1/ppt-master/tasks/{task_id}`

- 强制 JWT 和 owner 匹配；其他用户与不存在任务统一返回 404。
- 使用现有统一响应 envelope：`code/message/data/trace_id`。
- `data` 返回 `status`、`sequence`、`page_count`、`outline`、`completed_slides`、`current_slide`、`errors`、`metrics`、`final_file` 和时间戳。

## 3. 数据库变化

新增两张表；没有修改或删除既有业务列、索引或行：

### `ppt_incremental_tasks`

- `task_id`（主键）
- `project_id`
- `user_id`
- `request_id`
- `status`
- `sequence`
- `page_count`
- `outline_json`
- `completed_slides_json`
- `current_slide_json`
- `errors_json`
- `metrics_json`
- `final_file_json`
- `created_at`
- `updated_at`
- 唯一约束：`(user_id, request_id)`

### `ppt_incremental_events`

- `event_id`（主键）
- `task_id`
- `user_id`
- `sequence`
- `event_type`
- `payload_json`
- `timestamp`
- 唯一约束：`(task_id, sequence)`

迁移前置检查在生产数据库副本上连续执行两次：

- `PRAGMA integrity_check`：前后均为 `ok`
- 既有表行数：不变
- 新表：2 张、初始行数均为 0
- 上线后生产数据库完整性：`ok`

## 4. 安全与校验结果

- SVG 预览仅通过既有 `/api/v1/files/{file_id}/download` 下载。
- 登记时和下载时均校验 owner、有效期、允许根目录、文件类型、大小和 SHA-256。
- SVG 再次执行 XML/资源安全门，拒绝脚本、实体、`file://`、外部 URL、任意路径、路径穿越和符号链接逃逸。
- SVG/PPTX 文件权限为 600，项目目录为 700，登记有效期默认为 7 天。
- 每个候选页在 `slide.completed` 前运行与最终导出一致的 SVG 质量检查。
- 不兼容候选转为稳定修复码，最多进行 2 次模型修复；失败候选立即删除。
- 统计字段：`model_output_count`、`svg_xml_invalid_count`、`svg_validation_blocked_count`、`svg_validation_block_rate`、`model_repair_retry_count`。
- 最终 `blocking_errors` 非空时不会导出，也不会返回 `valid=true`。

真实验收期间发现并修复了一个延迟校验问题：模型曾产生 PPTX 转换器不支持的文本属性。修复后，质量门前移到逐页完成之前，并把归一化错误码反馈给模型；已有完成页没有丢失。

## 5. 真实 4 页事件证据

最终受控测试结果：**PASS**。

| 项目 | 结果 |
|---|---:|
| `planning.started` → `task.completed` | 13 个事件 |
| sequence | 1～13 连续 |
| slide.completed | 1、2、3、4 |
| 第一页可预览 | 27.809 秒 |
| 全任务完成 | 99.337 秒 |
| 第一页快照中的已完成页 | 1 |
| 第一页完成时后续页仍在生成 | 是 |
| owner 预览 / 下载 | 200 / 200 |
| 其他用户预览 / 下载 / 查询 | 404 / 404 / 404 |
| 未认证预览 / 下载 / 创建 | 401 / 401 / 401 |
| 非空 sources | 422 |
| 并发第二任务 | 429 |
| 重复幂等键 | 409，原 task_id，sequence 不变 |
| SVG XML 与资源安全 | 通过 |
| `validation_result.passed` | true |
| blocking errors | 0 |
| `svg_xml_invalid_count` | 0 |
| `svg_validation_block_rate` | 0.0 |
| PPTX ZIP/OOXML | 通过 |
| PPTX 页数 | 4 |
| 原生可编辑 shape/text | 通过 |
| PPTX 下载大小 | 25,206 bytes |

脱敏证据 JSON 权限为 600，SHA-256：

`617125d4e8a05d0be2f3ad97cd4d1c359039533965caa84aa17b86752ce367fc`

测试结束后已清理：10 个临时普通用户、5 个增量任务、63 个事件、7 个 Legacy 试验记录、27 个登记文件和 10 个临时项目目录。复查临时用户为 0；外部仅保留脱敏 JSON 和验收 PPTX。

## 6. Legacy 兼容验证

真实 1 页 Legacy 流：

`progress → progress → spec → progress → progress → progress → validate → progress → done`

`done` 键保持：

- `file_id`
- `download_url`
- `size`
- `sha256`
- `valid`
- `validation_result`

Legacy 返回中未发现服务器路径。最终文件下载和 OOXML 校验通过。原 `/generate` 路由、Pydantic 请求模型、事件桥和 runner 未被替换。

## 7. 部署与运行证据

- 部署方式：基线 tag + 外部权限 700 备份 + 数据库快照 + `git merge --ff-only`。
- 当前提交：`c962943c4533952a87e5aa896bbd9b11322243e5`。
- 旧 PID：190955；当前 PID：239575。
- 8000 端口 owner 数：1。
- 当前服务子进程数：0。
- 健康接口：200；OpenAPI：200；未认证 `/auth/me`：401。
- `.env` 目标文件权限：600；运行日志权限：600。
- 当前服务启动后的日志：JWT/密钥模式 0，服务器绝对路径模式 0。
- 生产数据库与回滚数据库快照完整性均为 `ok`。
- 原有未提交运行状态文件保持不变，未纳入本次提交。

最终合并版本回归：`85 passed in 4.25s`。

## 8. 修改文件清单

- `app/PPT_master/admission.py`
- `app/PPT_master/incremental_router.py`
- `app/PPT_master/incremental_runner.py`
- `app/PPT_master/incremental_slides.py`
- `app/PPT_master/incremental_store.py`
- `app/PPT_master/router.py`
- `app/models.py`
- `app/services/artifact_service.py`
- `docs/superpowers/plans/2026-07-19-incremental-ppt-workflow.md`
- `docs/superpowers/specs/2026-07-19-incremental-ppt-workflow-design.md`
- `scripts/cleanup_incremental_smoke.py`
- `scripts/incremental_migration_preflight.py`
- `scripts/incremental_ppt_smoke.py`
- `tests/test_incremental_smoke_helpers.py`
- `tests/test_ppt_incremental_api.py`
- `tests/test_ppt_incremental_runner.py`
- `tests/test_ppt_incremental_slides.py`
- `tests/test_ppt_incremental_store.py`
- `tests/test_ppt_stage_a_artifacts.py`

## 9. Git commit 列表

1. `328180f3` docs: design incremental PPT workflow
2. `898dcecf` docs: plan incremental PPT workflow implementation
3. `92fb8258` incremental-events: persist task milestones and snapshots
4. `67da151b` incremental-preview: register safe SVG slide artifacts
5. `fa5632cb` incremental-slides: generate and repair one safe SVG at a time
6. `d5967268` incremental-runner: stream durable planning and slide milestones
7. `0473ce29` incremental-api: add durable per-slide stream and task query
8. `eae39517` incremental-migration: add repeatable SQLite preflight
9. `316aa62c` incremental-smoke: verify four-slide streaming and Legacy compatibility
10. `686b98f6` incremental-validation: repair export-incompatible slides before completion
11. `2b34b958` incremental-repair: constrain SVG output and classify quality errors
12. `461dd4dd` incremental-smoke: persist named assertion evidence on failure
13. `33c4c6cb` incremental-smoke: distinguish namespaces and retry Legacy evidence
14. `c962943c` incremental-smoke: safely clean temporary users and artifacts

## 10. 回滚方案与演练

基线 tag：`incremental-ppt-baseline-20260719-e33a09a9`，对应基线 commit `e33a09a9`。项目外保留权限 600 的上线前 SQLite 快照。

非破坏性演练结果：从当前版本生成的反向补丁执行 `git apply -R --check`，结果为 **PASS**。

回滚步骤：

1. 记录并停止当前单 worker，确认 8000 已释放。
2. 核对基线 tag、当前 commit 和外部数据库快照完整性。
3. 对 `e33a09a9..HEAD` 执行 `git revert --no-commit`，只反转本阶段提交，然后提交 rollback；不要覆盖既有未提交运行状态文件。
4. 运行基线测试并以原虚拟环境、`workers=1` 启动。
5. 检查健康接口、端口 owner 和 Legacy 1 页流。
6. 新增两张表为加法变更，正常代码回滚可保留；旧代码不会读取它们。
7. 只有在明确接受丢弃上线后新增业务数据时，才恢复上线前 SQLite 快照；不得自动覆盖当前数据库。

## 11. 尚未处理的 P1/P2

- P1：多 worker / 多实例全局并发仍需 Redis 或独立任务 worker；当前依赖已批准的单 worker 部署。
- P1：任务与事件表尚未配置自动保留期、归档和批量清理调度。
- P1：SSE 断线后可查询快照，但尚未提供按 sequence 的事件补拉/恢复流。
- P1：缩略图第一版复用 SVG，尚未生成独立栅格缩略图。
- P2：单页生成当前顺序执行；尚未做安全的有限并行和调度公平性。
- P2：取消、事件重放、持续对话和多轮修改按范围约束继续冻结。
- P2：素材上传仍未开放；后续只能设计为登记 `asset_id`，不得恢复任意路径/URL 输入。

## 12. 下一阶段联调建议

前端应新增独立 Incremental Adapter，不修改已冻结 Legacy Adapter：

1. 收到 `planning.completed` 即展开工作台并用 outline 建立 4 个页面槽位。
2. 按 envelope 顶层 `sequence` 去重和排序，不以到达时间推断顺序。
3. `slide.completed` 后使用带 JWT 的 Blob 请求读取 `preview_url`；不要把 URL 直接交给无鉴权 `<img>`。
4. 刷新或断线后调用任务查询接口，用 `completed_slides/current_slide/final_file` 恢复 UI。
5. `slide.failed` 仅标记对应页；不得清空已完成页。
6. `export.ready` 可启用下载，`task.completed` 关闭运行态；`task.failed` 保留已完成页与错误摘要。
7. 联调先覆盖 sequence 去重、401/404/409/429、Blob URL 生命周期和 JWT 过期刷新，再考虑事件补拉协议。
