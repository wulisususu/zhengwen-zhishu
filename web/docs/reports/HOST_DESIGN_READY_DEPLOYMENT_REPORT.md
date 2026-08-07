# AI 全能盒子 Design-ready 展开编排部署报告

日期：2026-07-19  
服务器：`192.168.0.11`  
宿主目录：`/home/youyeetoo/INnet_agent/web/`

## 版本与分支

| 项目 | 结果 |
|---|---|
| 本地 PPT 基线合并前 | `main@30a8cc9` |
| 本地 PPT 基线合并后 | `main@409fcba7b2414068ea33f29278055ef9542638d9` |
| 本地标签 | `design-ready-opening-baseline-20260719` |
| 宿主发布前 commit | `04df5d2a88ba7d69b7abe8e5b208bab8039330e4` |
| 宿主开发分支 | `feat/design-ready-opening-host` |
| 宿主集成 commit | `e8718b37e959f56e113b58a3d3ef5d9f944a4b6e` |
| 宿主发布后 main | `e8718b37e959f56e113b58a3d3ef5d9f944a4b6e` |
| 生产标签 | `design-ready-opening-production-20260719` |

## 迁移范围

只迁移了展开编排相关增量，没有重新复制整个 feature：

- `src/features/ppt-workbench/composables/usePptWorkflow.ts`
- `src/features/ppt-workbench/components/shell/WorkbenchShell.vue`
- `src/features/ppt-workbench/components/chat/ChatPanel.vue`
- `tests/design-ready-opening.spec.ts`
- `tests/split-workbench.spec.ts`
- `tests/refresh-restore.spec.ts`

宿主原有 `createClientUuid`、JWT 获取、401 处理、Router、Pinia、Legacy Adapter 配置和 Vite API proxy 均保留。

## 展开策略

1. 有效提交只启动 workflow，继续保持完整 conversation。
2. progress/understanding 只更新聊天阶段卡，不展开工作台。
3. 当前任务首次 `design.ready` 才调用 `workspace.beginOpening()`。
4. CSS 和 UI fallback 均为 560ms，随后进入 split-workbench。
5. 旧任务、重复 `design.ready`、用户关闭后的同任务事件不自动重开。
6. validate、done、Slide 事件不改变 workspaceMode 或 activeView。
7. 生成中提供显式“提前打开工作台”入口。

一次性消费与用户关闭保护是 `usePptWorkflow` controller 局部策略状态，没有修改五个 Store、标准协议或后端接口。

## 自动验证

| 命令 | 结果 |
|---|---|
| `npm test` | 通过：宿主 Node tests 15/15；PPT Vitest 105/105 |
| `npm run typecheck` | 通过 |
| `npm run build` | 通过，2216 modules transformed |

## 临时端口真实 Legacy 一页验收

临时实例使用端口 `3001`，仅进程环境设置 `VITE_PPT_MASTER_PAGE_COUNT=1`；未修改或提交生产环境配置。验收结束后临时服务已停止，3001 无 listener。

第一次请求完整进入分析、规划、SVG、质检和导出阶段，但后端返回阻断项 `svg_xml_invalid`。前端正确显示失败且不提供下载，没有把无效结果伪装成成功。

第二次受控请求使用更简单的提示词并成功：

- 提交后 250ms：conversation；显示“正在分析需求”“正在规划设计方案”；无编辑器。
- 约 1.2s：仍为 conversation。
- 收到 spec → `design.ready` 后：进入 opening，再进入 split-workbench。
- SVG 阶段：显示“正在生成幻灯片”、1 页 Legacy 占位和一次性生成说明。
- validate/export：显示中文质检与导出阶段卡，workspaceMode 保持 split-workbench。
- done：显示“PPTX 已生成”，在线编辑入口保持禁用。
- 鉴权 Blob 下载成功：`pptgen_54ec902d_20260719_045900.pptx`。
- 离开 PPT 再返回同一项目：完成状态和工作台恢复。
- 浏览器页面日志：0 error、0 warning。

## 宿主回归

| 能力 | 临时端口 | 正式 3000 |
|---|---|---|
| Chat `/chat` | 页面加载，0 控制台问题 | 页面加载，0 控制台问题 |
| 文档 `/document` | 页面加载，0 控制台问题 | 页面加载，0 控制台问题 |
| 知识库入口 | 沿用宿主现有 `/knowledge` → `/chat` 行为 | 沿用宿主现有行为，未回归 |
| PPT landing | 正常 | 正常 |
| PPT Legacy 1 页 | 成功生成并下载 | 使用同一已构建 commit 发布 |

知识库路由仍复用宿主当前 Chat 页面，这是发布前已有行为，本轮未调整。

## 3000 发布

| 项目 | 发布前 | 发布后 |
|---|---|---|
| systemd user service | `ai-box-frontend-3000.service` | 同一服务 |
| PID | `218224` | `224172` |
| Listener | `0.0.0.0:3000` | `0.0.0.0:3000` |
| HTTP | 200 | 200 |

发布采用 `systemctl --user stop/start` 优雅切换。外部工作站复核：3000 TCP 可达、HTTP 200、页面标题正确；3001 已关闭。

最近 300 行前端日志检查：

- error/exception/failed：0
- Authorization/Bearer 泄露：0
- `/home/youyeetoo`、`project_dir`、`pptx_path`、`filepath`：0

## 浏览器证据

- `deployment-evidence/design-ready-opening-20260719/real-legacy-1page-completed.png`
- `deployment-evidence/design-ready-opening-20260719/production-3000-ppt-landing.png`

## 回滚

若生产出现阻断问题，不执行强制 reset：

```bash
cd /home/youyeetoo/INnet_agent/web
git switch main
git revert --no-edit e8718b37e959f56e113b58a3d3ef5d9f944a4b6e
npm run build
systemctl --user restart ai-box-frontend-3000.service
curl -fsS http://127.0.0.1:3000/ >/dev/null
```

也可从发布前 commit `04df5d2a88ba7d69b7abe8e5b208bab8039330e4` 建立恢复分支，不改写 main 历史。

## 遗留事项

- 3000 当前仍由 Vite dev server 的 systemd user service 托管，尚未切换到 Nginx/静态 dist。
- Legacy 后端仍不提供逐页数据、取消、恢复或单页重生成。
- 首次真实生成出现一次模型输出 `svg_xml_invalid`；第二次受控重试成功，建议后端继续统计该质检阻断率。
