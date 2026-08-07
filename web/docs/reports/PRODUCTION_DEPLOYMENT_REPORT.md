# AI 全能盒子 PPT 工作台生产发布报告

发布日期：2026-07-18

正式地址：`http://192.168.0.11:3000/`

服务器目录：`/home/youyeetoo/INnet_agent/web/`

## 1. 发布版本

| 项目 | 值 |
|---|---|
| 发布前 `main` | `e51c15409bf898a4424f5dfd0bda2e7ab98c7dcd` |
| 实际部署应用 commit | `e51c15409bf898a4424f5dfd0bda2e7ab98c7dcd` |
| 宿主基线标签 | `ppt-workbench-host-baseline-20260718` |
| 生产标签 | `ppt-workbench-production-20260718` |
| 回滚标签 | `pre-ppt-host-integration-20260718` |
| 生产标签指向 | `e51c15409bf898a4424f5dfd0bda2e7ab98c7dcd` |

本次是已有已验收 commit 的运行服务切换，没有修改业务源码。发布报告和生产截图作为发布后证据单独提交，不改变生产标签所指向的应用代码。

## 2. 发布前服务审计

3000 端口原服务为 Vite dev，不是 Vite preview、Node 静态服务或 Nginx 静态目录。

| 项目 | 发布前 |
|---|---|
| Listener PID | `58889` |
| npm 父进程 PID | `58865` |
| 启动命令 | `npm exec vite --host 0.0.0.0 --port 3000` |
| 工作目录 | `/home/youyeetoo/INnet_agent/web` |
| stdout / stderr | `/home/youyeetoo/INnet_agent/service_logs/frontend_3000.log` |
| 启动时间 | 2026-07-16 09:56:12 CST |
| 环境来源 | 交互 shell 继承环境及 Vite 默认环境加载；未发现生产 `.env*` 文件或 `VITE_*` 启动变量 |

后端 `http://127.0.0.1:8000/api/v1/health` 发布前返回 HTTP 200，状态 `healthy`。

## 3. 备份与构建隔离

发布前备份目录：

`/home/youyeetoo/INnet_agent/release_backups/ppt-workbench-production-20260718-predeploy-e51c154`

备份内容包括：

- 当前 `dist/`；
- `package.json`、`package-lock.json`、`vite.config.js`、`.env.example`；
- 发布前 `frontend_3000.log`。

备份大小约 1.5 MiB。为避免 `npm ci` 删除线上 Vite 进程正在读取的 `node_modules`，发布门禁在同一 Git commit 的隔离工作树中执行：

`/home/youyeetoo/INnet_agent/release_staging/ppt-workbench-production-20260718-e51c154`

隔离工作树 HEAD 和发布目录 HEAD 均为 `e51c15409bf898a4424f5dfd0bda2e7ab98c7dcd`，构建产物复制到正式目录后，`dist/index.html` SHA-256 完全一致。

## 4. 构建门禁

| 命令 | 结果 |
|---|---|
| `npm ci` | 通过，从锁文件安装 271 个包 |
| `npm test` | 通过：宿主 Node 测试 15/15；PPT Vitest 13 文件、96/96 |
| `npm run typecheck` | 通过 |
| `npm run build` | 通过；Vite 5.4.21，2216 modules transformed，9.26s |

依赖审计仍报告 7 个既有漏洞（3 moderate、2 high、2 critical）。未执行 `npm audit fix --force`，也未在本次发布升级依赖。

## 5. 3000 服务发布

### 首次切换与恢复演练

旧进程组仅包含 npm、shell、Vite Node 和 esbuild，确认后使用 SIGTERM 优雅停止。首次新启动命令缺少 `npm exec` 的参数分隔符，Vite 将参数值视为位置参数并错误监听 5173，3000 健康检查失败。

该失败立即触发启动恢复流程：

1. 终止错误的 5173 临时进程；
2. 使用 `npm exec vite -- --host 0.0.0.0 --port 3000` 正确转交参数；
3. 3000 恢复 HTTP 200；
4. 清理诊断用 3002 listener；
5. 未修改 JWT、数据库、后端配置或 Git 历史。

这次实际故障恢复验证了停止、发现失败、恢复 listener 和日志留存流程。失败及冒烟日志保存在：

`/home/youyeetoo/INnet_agent/service_logs/frontend_3000.release-smoke-20260718.log`

### 最终生产进程

| 项目 | 发布后 |
|---|---|
| Listener PID | `216738` |
| npm 父进程 PID | `216721` |
| 进程组 | `216721` |
| 启动命令 | `npm exec vite -- --host 0.0.0.0 --port 3000` |
| 工作目录 | `/home/youyeetoo/INnet_agent/web` |
| stdout / stderr | `/home/youyeetoo/INnet_agent/service_logs/frontend_3000.log` |
| HTTP 根地址 | 200 |
| 后端 health | 200 |
| 监听状态 | 仅预期的 `0.0.0.0:3000`；无 3002/5173 临时 listener |
| 测试页数变量 | 最终进程不存在 `VITE_PPT_MASTER_PAGE_COUNT` 覆盖，使用正式默认值 |

最终启动日志：

```text
VITE v5.4.21 ready
Local:   http://localhost:3000/
Network: http://192.168.0.11:3000/
```

## 6. 正式浏览器冒烟

使用正常业务账号在正式 3000 地址执行，JWT 未输出到控制台、截图、报告或测试日志。

| 验证项 | 结果 |
|---|---|
| 登录 | 通过；未登录访问 Chat 正确进入登录页，登录后返回 Chat |
| Chat 入口、历史和发送链路 | 入口、历史、鉴权请求和降级 UI 正常；实际消息因上游主模型不可用转本地模型，最终到宿主既有 5 分钟超时，未取得有效回答 |
| 文档入口 | 通过；文档页面、最近对话和输入区正常加载；未在 Chat 模型超时状态下继续创建文档生成任务 |
| 知识库 | 通过；入口可打开，已索引文件、预览和下载入口正常显示 |
| 左侧 PPT 生成 | 通过 |
| PPT conversation 首屏 | 通过；没有预先展示空工作台 |
| opening → split-workbench | 通过，动画后出现聊天、1 页占位和 Legacy 编辑能力说明 |
| 中文阶段卡 | 通过：分析需求、规划设计、生成幻灯片、质量检查、导出 PPTX |
| SSE | 完整结束，无解析异常 |
| 质检 | 评分 100，通过项 2，无阻断错误 |
| 鉴权 Blob 下载 | 通过；页面显示实际下载文件名，后端 GET download 为 HTTP 200 |
| 刷新恢复 | 通过；完成结果、质量检查和下载入口恢复 |
| Chat / Word / 知识库切换后返回 | 通过；按同一 `/ppt/:projectId` 返回时项目状态仍在 |
| 最终默认配置新标签页 | 通过；项目恢复，控制台 0 error、0 warning |
| 页面/DOM 泄漏扫描 | 0 个 JWT、Authorization、服务器绝对路径、`pptx_path` 或 `project_dir` 命中 |

### Chat 依赖异常说明

额外执行的 Chat 消息冒烟未取得模型回答。浏览器表现为主模型不可用后切换本地轻量服务，最终按宿主现有 300 秒空闲超时返回“暂时没有拿到有效内容”。`openclaw-chat.service` 仍为 active，`127.0.0.1:18790/health` 返回 200；该链路没有引用 PPT feature，且问题发生在上游模型响应阶段。

因此本报告不将 Chat 生成写为通过。回滚 PPT 前端不会恢复上游模型，本次没有为该外部依赖问题改写前端 `main`；需要由模型/Chat 后端运维单独处理。若发布验收要求“Chat 必须返回内容”，当前状态应视为未完全满足，而不是被生产发布掩盖。

## 7. 真实 1 页 PPT 与文件检查

生产冒烟短暂以受控的 `VITE_PPT_MASTER_PAGE_COUNT=1` 启动 3000，完成后已重启为无该变量的正式默认配置。

生成需求：一页简洁生产发布周报，`page_format=ppt169`、`sources=[]`。

| 文件检查 | 结果 |
|---|---|
| 后端文件记录 | `599` |
| 下载文件名 | `pptgen_aca006d1_20260718_213800.pptx` |
| 文件大小 | 15,983 bytes |
| size 一致性 | 通过 |
| SHA-256 一致性 | 通过 |
| ZIP / OOXML | 通过 |
| 必需 OOXML 部件 | 通过 |
| Slide 数量 | 1 |
| 可编辑 shape | 69 |
| 可编辑文本节点 | 44 |

检查过程只输出脱敏结构指标，没有输出服务器文件系统路径。

## 8. 截图证据

1. [PPT conversation 首屏](docs/evidence/production/01-production-ppt-landing.png)
2. [opening 过渡](docs/evidence/production/02-production-ppt-opening.png)
3. [真实 Legacy 生成](docs/evidence/production/03-production-ppt-generating.png)
4. [生成完成](docs/evidence/production/04-production-ppt-completed.png)
5. [质量检查](docs/evidence/production/05-production-ppt-validation.png)
6. [刷新恢复](docs/evidence/production/06-production-refresh-restored.png)
7. [最终默认配置](docs/evidence/production/07-production-final-default-config.png)

## 9. 日志与安全检查

- 最终 `frontend_3000.log` 只包含本次干净启动信息。
- 最终前端日志敏感/绝对路径扫描：0。
- 后端最近 250 行敏感/绝对路径扫描：0。
- 浏览器新标签页控制台只有 Vite `connecting/connected` debug：0 error、0 warning。
- 页面和 DOM 扫描：0 个 JWT、Bearer、Authorization、服务器绝对路径命中。
- PPT 下载后端请求：HTTP 200。

## 10. origin 推送

服务器本地 `main` 比已缓存的 `origin/main` 超前 3 个 commit。已按要求依次尝试普通非强制推送：

- `main`
- `ppt-workbench-host-baseline-20260718`
- `ppt-workbench-production-20260718`

三次均未成功，原因是部署服务器到 `origin` 地址 `192.168.1.212:3001` 无路由（`No route to host`）。没有强推，没有修改 remote，没有绕过分支保护。待网络恢复后可重复普通 `git fetch origin` 和 `git push`。

## 11. 回滚方式

优先采用不改写 `main` 历史的恢复分支方式：

```bash
cd /home/youyeetoo/INnet_agent/web/
git switch -c rollback/pre-ppt-production pre-ppt-host-integration-20260718
npm ci
npm run build
```

或者恢复发布前备份目录中的 `dist` 和启动配置。Vite dev 运行方式下，回滚前必须先在隔离目录完成构建验证，再优雅切换 3000；不得对 `main` 执行强制 reset。

本次已实际演练错误 listener 的检测、终止和 3000 恢复，但没有切换到旧业务 commit，因为最终 PPT、登录、导航和下载均正常，额外发现的 Chat 模型超时属于上游依赖而非 PPT 前端回归。

## 12. 当前遗留问题

1. Chat 上游主模型不可用，本地轻量服务在 300 秒内未返回有效内容；需要模型/Chat 后端运维处理。
2. 生产前端仍使用 Vite dev，长期应迁移到构建后静态部署或受管进程服务。
3. `origin` 网络不可达，`main` 和标签尚未推送远端仓库。
4. 依赖审计存在 7 个既有漏洞，应建立独立兼容性升级任务。
5. Legacy 后端仍不支持逐页在线数据、取消、恢复、单页重生成和提案应用。
6. 窄屏横向滚动仍是临时兜底，不代表正式移动端方案。
