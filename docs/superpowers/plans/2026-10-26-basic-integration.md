# 政务基础功能联调 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 用真实 HTTP、登录和 SQLite 打通政务文稿、材料、人工审核、DOCX 下载，并接通现有生成服务。
**Architecture:** Vue 的 GovOfficeAdapter 增加 HTTP 实现；FastAPI /gov 路由使用现有 JWT 和用户表，增加独立文稿、材料关联、历史记录表。所有权限和版本检查在服务端执行。
**Tech Stack:** Vue 3、Pinia、TypeScript、FastAPI、SQLAlchemy、SQLite、python-docx。
**Spec:** docs/superpowers/specs/2026-10-26-basic-integration-design.md（用户于 2026-10-26 确认）。

## Global Constraints

- 政务工作台为主，旧功能先保留，删除前列清单。
- 分支 feat/basic-integration；不改 main、不合并或 push，不混入 T1—T3。
- 禁止生产失败回退 Mock；不伪装自动审校或政策服务已接入。
- 正式发文权限默认 false；只验收内部草稿真实导出。
- 工作区数据与运行端口隔离；测试账号不得接触其他工作区的数据。

## Review Focus

- 跨用户文稿/材料访问及下载必须拒绝：Task 1/2 授权用例。
- 审核中编辑、作者自审、重复操作：Task 1 状态流转用例。
- 旧版本并发覆盖：Task 1 用 version 条件更新和冲突用例。
- API/模型失败不得展示成功或 Mock：Task 3/4 错误用例。
- 真实文件内容、A4 与水印：Task 2 OOXML 验证与 Task 5 下载验收。

### Task 1: 后端文稿、真实身份、人工审核

**Files:** Create app/gov/models.py, schemas.py, service.py, router.py; Modify app/models.py, app/main.py, app/database.py; Test tests/test_gov_basic_api.py.
**Interfaces:** /api/v1/gov/{actor,runtime,documents}; POST documents 创建；PUT documents/{id} 接收 version 和文稿内容；POST documents/{id}/{submit,approve,return} 接收 version/opinion。响应沿用 ok(data)，文稿遵循 OfficialDocument。
- [x] 写失败用例：真实 JWT/401、创建保存、跨用户404、非审核人403、自审403、待审不可编辑409、退回重提、批准、旧版本409、重复动作409。
- [x] 运行失败用例，确认原因是功能缺失。
- [x] 实现数据库模型、事务与带版本条件的更新；记录真实操作人，不接受客户端作者/状态/历史。
- [x] 回归并提交。

### Task 2: 材料与真实内部 DOCX

**Files:** app/gov/router.py, service.py, export.py; Test tests/test_gov_basic_api.py.
**Interfaces:** GET/POST /gov/materials（流式限制上传20MiB）；POST/DELETE documents/{id}/materials；POST documents/{id}/export 直接返回 DOCX Blob。复用 files 用户表，关联时验证所有者；生成仅直接读取UTF-8 TXT/Markdown，二进制解析明确未接入。
- [x] 写失败用例：真实上传、他人文件不能关联、移除仅解除关系、未授权下载404、formal403、文稿导出包含正文/A4/水印。
- [x] 运行失败，随后实现文件和导出流程；导出不复用有默认 Letter 问题的无配置输出，显式设置 section。
- [x] 运行本任务及 Task 1 测试并提交。

### Task 3: HTTP 适配器与政务入口

**Files:** web/src/features/gov-office/adapters/HttpGovOfficeAdapter.ts, index.ts, GovOfficeAdapter.ts, types.ts; stores 与 DraftWorkbenchPage、GovHomePage、AddMaterialDialog、ExportDialog、GovLayout；main.js、LoginPage。
**Interfaces:** HTTP adapter 实现已有契约，并扩展 createDocument、saveDraft 内容、uploadMaterial、generateDraft；所有写请求携带服务端 version。getSessionToken 动态取现有登录 token。
- [x] 写并运行失败用例：默认 HTTP、请求带真实 token、保存/版本/服务端错误、生产不回退 Mock、实际 Blob 下载。
- [x] 实现页面新建/编辑/保存/材料上传，去掉 HTTP 模式的 demo-d1 默认值；真实身份不能演示切换；/gov 为登录默认入口，旧入口仍保留。
- [x] 未接政策和自动审校显示明确不可用；不能将0问题渲染为已经检查通过。
- [x] npm test、typecheck、build，并提交。

### Task 4: 接通已有模型生成

**Files:** app/gov/generation.py, router.py; HTTP adapter 和起草页；tests/test_gov_basic_api.py。
**Interfaces:** POST documents/{id}/generate 携带 version/prompt，调用现有 llm_client 受控HTTP传输（避免会话兜底文本），成功更新草稿；模型失败503且文稿不变。
- [x] 写失败用例：有内容才持久化，模型异常/空内容不改文稿；生成期间文稿改变则409。
- [x] 实现线程池/同步路由边界、现有模型出口策略和明确错误；禁止规则生成假模型结果。
- [x] 运行测试并提交；实际模型验收单独记录是否有可达服务。

### Task 5: 真 HTTP 浏览器验收与候选清理

**Files:** tests/browser/basic-live.mjs, 后端隔离启动入口/配置（必要时），验收报告。
- [x] 启动独立数据库的真实 API 和前端；建立作者/他人/审核人真实测试账号。
- [x] 真实登录完成创建、保存、刷新、上传、送审、退回、重提、批准、DOCX 下载；不得拦截 API 或塞假 token。
- [x] 按已展示清单重新检查无引用，清理旧 router.js/原型页 import、重复建表段落；验证路由和测试。
- [x] 完整测试命令与构建；报告既有失败和真实模型/板端限制。
- [x] 独立全分支审阅；修复重要问题后回归并提交，保留分支不合并。

实际验收边界：真实浏览器基础闭环通过；真实模型成功、ARM64、全产品后端和Word/WPS渲染未验收，详见验收报告。
