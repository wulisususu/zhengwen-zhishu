# PPT 观感优化 — 并行冲突矩阵与检查点（2026-07-24，更新于本回合）

> 任务：AI 全能盒子 PPT「观感优化智能体」（前端观感优化负责人）
> 模式：与 P3-A（结构化生成）/P3-B（Strategist）/P4（对象动画）并行，互不阻塞、互不覆盖。
> 环境说明：本 WorkBuddy 环境**不具备真实浏览器/截图/Playwright 能力**，故浏览器观感与截图验收已取消，改以「代码审查 + Vitest 组件挂载 + DOM 断言 + 响应式计算」覆盖验收点；真实浏览器验收留待后续具备浏览器能力的智能体或人工，且**不得伪造**浏览器验收结果。

## 1. 审计结论（§3.1，已复核）

| 项 | 值 |
|---|---|
| 真实生产基线 commit | `f294f31`（`release/ppt-source-attachments-web-20260722`，3000 服务实际来源 `/home/youyeetoo/.releases/ppt-source-web-prod`） |
| 本任务 worktree 路径 | `/home/youyeetoo/.worktrees/ppt-visual-polish-web` |
| 本任务分支 | `feature/ppt-visual-polish-web` |
| 本任务 HEAD（本回合起始） | `02d4052`（5 个 phase-1 提交，基于 `f294f31`，干净；仅 `node_modules` 未跟踪） |
| P3-A 最新 tip | `f83716f` feat(ppt): P3-A editor structured UI（master/layout lock banner、placeholder markers、bounds_locked、export error），基 `f294f31` + `b4c09c2` + `ea5c5f2` |
| 服务器 | `192.168.0.11`（youyeetoo / 123456），仅 `0.0.0.0:3000` 与 `0.0.0.0:8000` |
| 其他并行 agent | P3-A `feature/ppt-p3a-structured-web` @ `f83716f`；`fix/chat-knowledge-attachment` @ `72a5bf1` |

## 2. 文件冲突矩阵（本回合更新）

### 2.1 本智能体改动文件（累计）

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/features/ppt-workbench/index.ts` | 改 | 仅新增 `import "./visual/visual-tokens.css"` |
| `src/features/ppt-workbench/visual/visual-tokens.css` | 新增→改 | 设计令牌 + 原语；本回合补充 `:focus-visible` 键盘焦点轮廓 |
| `src/features/ppt-workbench/components/editor/EditorToolbar.vue` | 改 | 统一顶栏/视图页签/状态药丸；本回合补 `role="status"`+`aria-live="polite"` |
| `src/features/ppt-workbench/components/editor/ObjectToolbar.vue` | 新增 | 单行图标+中文工具栏（无竖排文字、无假按钮） |
| `src/features/ppt-workbench/components/editor/SlideEditor.vue` | 改 | 接入 ObjectToolbar；画布令牌化；缩放包 `:zoom`；保存/导出状态 |
| `src/features/ppt-workbench/components/slides/SlideList.vue` | 改 | 编辑态真实 16:9 缩略图 + 悬停重排 |
| `src/features/ppt-workbench/components/editor/SpeakerNotesPanel.vue` | 改 | 折叠抽屉；本回合折叠状态接入持久化 store（替代局部 ref） |
| `src/features/ppt-workbench/stores/pptWorkspace.ts` | 改（本回合） | 新增 `speakerNotesCollapsed` 状态 |
| `src/features/ppt-workbench/persistence/workspaceStorage.ts` | 改（本回合） | `PersistedWorkspace` 增加 `speakerNotesCollapsed` |
| `src/features/ppt-workbench/composables/useWorkspacePersistence.ts` | 改（本回合） | 持久化 watch 增加 `speakerNotesCollapsed` |
| `src/features/ppt-workbench/ppt-workbench.css` | 改（本回合） | 内容列 `minmax(0,1fr)` 防窄屏溢出；新增 1024/1280 响应式断点 |
| `src/features/ppt-workbench/utils/resolveWorkbenchLayout.ts` | 新增（本回合） | 纯函数响应式布局解析（1600+/1280-1600/1024-1280/<1024） |
| `tests/visual-polish.spec.ts` | 改（本回合） | 扩展到 21 项：折叠持久化、状态/冲突(409)、无内部ID泄露、响应式断点、工具栏不竖排、adapter 入口 |

### 2.2 其他并行 agent 触及文件

- **P3-A `f83716f` 编辑器结构化 UI**：`EditorToolbar.vue`、`SlideEditor.vue`（与 §2.1 本任务 phase-1 改动**文件级重叠**——见 §2.3）、`EditorWorkspace.vue` 相关。
- P3-A 结构化模式开关/工作区选择器：`LandingComposer.vue`、`ChatPanel.vue`、`pptUi` store。
- `fix/chat-knowledge-attachment`：聊天附件相关，**不整合并入**本分支。

### 2.3 重叠判定（已修正）

**文件级重叠：存在（2 个）。**
- `EditorToolbar.vue`：本任务（视图页签/状态药丸/aria-live）vs P3-A（lock banner / export error 提示）。
- `SlideEditor.vue`：本任务（令牌化/ObjectToolbar/缩放/保存状态）vs P3-A（placeholder markers / bounds_locked）。

**集成策略（必须遵守）**：
1. 待 P3-A 合入生产基线后，将本分支 `rebase` 到最新生产基线（当前为 `f294f31`，未来为 P3-A 合入后的新基线）。
2. 对 `EditorToolbar.vue` / `SlideEditor.vue` 采用**逐文件、逐区块合并**，保留双方能力：我的令牌体系/状态药丸/工具栏 与 P3-A 的 lock banner/placeholder/bounds_locked/export error **共存**，不得整文件覆盖任一侧。
3. 不并入 `fix/chat-knowledge-attachment` 整支；其聊天附件能力由 P3-A 主线负责。
4. 禁止：`git reset --hard` / `clean -fd` / `checkout -- .` / `restore .` / `push --force` / 整文件覆盖。

## 3. 风险与策略

- **风险等级：中（合并期）。** 正常运行期无风险（独立 worktree）；合并期 `EditorToolbar`/`SlideEditor` 需人工逐区块解决。
- **语义耦合点**：`EditorToolbar` 被 `EditorWorkspace`/`WorkbenchShell` 引用，对外接口（`emit close`/`select-view`、既有 `aria-label`）保持不变。
- **测试保护**：保留既有 Vitest 所需的 `data-*` 与 `aria-label`；本回合新增断言不破坏既有选择器。
- **真实浏览器验收**：已取消（环境无浏览器能力），不伪造；以 Vitest/DOM/响应式计算替代，见 §4。

## 4. 检查点状态

- [x] 并行冲突审计（含本回合 P3-A tip 复核）
- [x] 文件冲突矩阵（本文，已修正重叠判定）
- [x] 独立 worktree（feature/ppt-visual-polish-web @ 02d4052）
- [x] 视觉令牌 + 原语 + 顶栏/工具栏/缩略图/演讲稿抽屉（phase-1）
- [x] 本回合 P1/P2：折叠持久化、响应式防溢出、focus-visible、aria-live、布局解析
- [x] 同步至服务器 worktree（9 个文件已上传）
- [x] `visual-polish.spec.ts` 21 项全部通过
- [~] `npm test`（全量，含 host + ppt 套件）— 本回合运行中
- [ ] `npm run typecheck` / `npm run build` / `git diff --check`
- [x] 清理 3097 临时验收服务（已 kill pid 1259923，3000/8000 不动）+ 本地 Playwright harness（已删）
- [ ] 浏览器基线截图 — **取消**（环境无浏览器能力，不伪造）
- [ ] 安全窗口：备份 → rebase 到最新生产基线 → 合并 → 重启 3000 → 验收 → 打 production/rollback 标签
