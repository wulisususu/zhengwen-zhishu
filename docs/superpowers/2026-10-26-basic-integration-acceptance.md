# 政务基础功能联调验收

日期：2026-10-26。分支：`feat/basic-integration`，基线：`main@aeee82b`。

本期已打通真实身份、文稿持久化、材料上传关联、人工审核与内部 DOCX 下载。真实模型生成成功及整个产品的部署验收尚未完成，不能据此声称全部功能已联调。

## 已交付

- `/gov` 成为登录默认入口；旧聊天、PPT、语音、知识库和儿科功能入口继续保留。
- 默认 HTTP adapter 连接 FastAPI，复用 JWT 与用户表，文稿和审核记录进入 SQLite。Mock 仅用于显式演示和测试，接口失败不会切回演示数据。
- 通知文稿可新建、编辑标题/正文/要素/日期、保存、刷新恢复。普通用户为起草人，管理员可审核他人的稿件；后端拒绝自审、越权、非法状态和版本冲突。
- 真实材料上传、关联、解除关联与鉴权下载；单次上传上限20MiB。旧文件删除接口也会保护已关联的政务材料。
- 草稿→送审→退回→修改重提→他人批准的流程与历史记录落库；待审和批准状态锁定编辑。
- 真实 DOCX 导出，显式 A4 和页边距，包含保存后的正文以及“未审核 · 内部草稿”标记。人工审核通过仍不等于正式发文授权。
- “生成初稿”已调用现有受控模型 HTTP 传输，失败503且保留原稿。直接读取的材料限UTF-8 TXT/Markdown，单份80000字节，过长明确拒绝；PDF等二进制材料可上传，但尚未接入生成解析。
- 政策检索、自动审校明确显示未接入；没有把空问题列表当作检查通过，没有合入T1–T3。

## 验证证据

所有验收使用独立数据库、上传目录和随机测试账号；未使用其他工作区的业务数据。

| 项目 | 最终结果 | 命令/证据 |
|---|---|---|
| 后端政务、既有DOCX和文件解析回归 | 34 passed | `python -m pytest tests/test_gov_basic_api.py tests/test_markdown_to_docx.py tests/test_file_parse_service.py -q -p no:cacheprovider` |
| 前端宿主测试 | 16 passed | `npm test` 内的宿主测试 |
| 前端Vitest | 234 passed，33个文件 | `npm test` |
| 类型检查及生产构建 | exit 0 | `npm run build`（含 `vue-tsc --noEmit`） |
| 真实浏览器全流程 | 通过，43次真实政务HTTP请求，0页面错误 | `CHROME_PATH=/usr/bin/google-chrome node tests/browser/basic-live.mjs` |
| 审查回归 | 7项先失败后通过 | 账号切换4项；未来版本绕锁、旧接口删材料、中文长材料各1项 |
| 实际不可达模型 | 503，正文和版本保持 | 实际HTTP请求；成功返回只由测试替身验证持久化契约 |
| 下载DOCX | OOXML验证通过 | A4为11906×16838 twip；包含退回后修改的正文，排除修改前正文，内部草稿标记存在 |

浏览器真实登录并完成：新建→编辑→保存→刷新→TXT上传关联→送审→审核人退回→作者修改重提→审核人批准→作者下载DOCX；第三个账号访问他人文稿被拒绝。没有拦截API或注入假token。起草与审核页面已截图检查。

验收日志位于服务器 `/tmp/basic-gov-post-review-{backend,web,build,browser}.log`；浏览器证据位于该工作区 `.gov-runtime/evidence/`（忽略目录，不提交测试凭据和数据库）。

## 删除清单执行结果

此前已列出的清理单独提交为 `b7afe58`：

1. 未引用的 `web/src/router.js`。
2. 未挂载的 `web/src/views/PrototypeChatPage.vue` 及残留import。
3. `backend/app/database.py` 中重复的 `ppt_structured_workspaces` 建表和索引代码段。

旧业务功能未删除。主要实现提交为 `240302d`、`ad5999a`；后续审查修正和本报告另有提交，可由分支日志查看。

## 已知边界

- 全量后端 `pytest` 在收集阶段被既有PPT测试挡住：缺少 `backend/app/PPT_master/skill/ppt-master/scripts/pptx_shapes/data/shape_type_values.txt`。该资源在main基线也不存在；未把全量后端写成通过。
- 本次运行的是独立应用 `app.gov.application`，挂载与主入口相同的真实auth/gov路由；`app.main` 已注册gov路由，但整个旧产品运行未通过本次验收。
- 模型真实成功、ARM64/RK3588、二进制材料解析、正式发文均未验收。仅提供通知文种的基础闭环，不表示全部公文模板已实现。
- DOCX的OOXML与下载内容已检查；本机和VPS均无LibreOffice，渲染尝试未成功，Word/WPS实际分页和字体效果仍需验收。
- 构建仍有既有的大chunk提示；旧前端测试有访问未启动3000端口的stderr，但测试退出码为0。后端有既有依赖弃用警告。
- 前端首次 `npm ci` 遇DNS错误，实际使用与锁文件SHA256一致的既有依赖目录；未改依赖版本。

## 实施裁决与代价（按记录顺序）

1. 使用已有轻量Python环境和隔离应用验收真实auth/gov路由：避免牵动其他工作区。代价：不能证明可选模型模块及整个产品的启动兼容性。
2. DNS失败后复用锁文件一致的前端依赖：保证版本不变。代价：全新环境依赖安装尚未验证。
3. 直接复用现有受控模型HTTP层，避开会话接口的兜底文本：模型失败如实报错。代价：上游内部接口变化时需维护适配。
4. 生成仅读取UTF-8 TXT/Markdown，二进制明确拒绝：不会冒充已经阅读附件。代价：PDF等需另接解析链路。
5. 真实模型成功及ARM64保留为未验证：503保留原文已实测，模拟成功只证明接口和持久化。代价：真实内容质量、板端性能仍需验收。
6. 全产品/旧后端验收因既有PPT缺资源而未通过：本期验收仅覆盖真实基础闭环。代价：旧模块运行兼容性仍未认证。
7. 二进制解析、正式发文、政策和自动审校维持本分支边界：符合已确认范围，不混入T1–T3。代价：完整政务产品仍需后续集成。

独立审查原标为Minor的中文截断问题已上调为Important并修复；无延后的小问题。

分支和worktree保留在服务器 `/home/browser/work/innet-agent-ai-box-worktrees/basic-integration`，不合并、不push；main仍为 `aeee82b`。
