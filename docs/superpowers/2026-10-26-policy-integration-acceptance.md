# 基础联调与 T1 政策检索：部署验收

日期：2026-10-26。完成用户要求的前三步：Windows 保存各分支成果、保留真实基础流程、接入 T1。没有合并 main 或向 GitHub push；T2/T3 未接入产品运行链路。

## 提交与基线

| 内容 | 分支 | 提交 |
|---|---|---|
| 当前 main（GitHub 连接器已核对） | main | aeee82b |
| 已部署的基础联调基线 | feat/basic-integration | f7a8b20 |
| T1 原始模块 | feat/policy-retrieval | ebc137a |
| T2 完整交付保存，66个文件 | feat/gongwen-check | fd5803b |
| T3 已保存 | spike/pdf-opendataloader | 46f4087 |
| T1 合入联调分支 | feat/basic-integration | 392969f |
| 本轮业务代码与测试 | feat/basic-integration | 0a695d7 |

所有任务分支原已包含 aeee82b；只合入该 main 不会带来最新真实联调，因此以 f7a8b20 为集成基础。原开发 VPS 的工作区未被重置；Windows 和部署机均保存各任务分支引用。

## 当前能力

- 真实登录、新建/编辑/保存、刷新恢复、材料上传关联、送审/退回/重提/他人审核、内部 DOCX 下载继续可用。
- `/gov/library` 和 `/gov/policy-qa` 在真实模式下打开政策检索。可浏览政策、按条款检索、查看原文/来源/版本，选择条款保存至自己的可编辑文稿。
- 引用只提交真实 citation ID，后端重新解析，遵守作者、文稿锁定和 version 冲突检查；前端不能伪造政策标题、现行状态或版本。
- 文稿保存服务器生成的引用快照；政策库不可用时明确显示引用无法核对，仍可阅读/保存文稿或移除引用，不把故障当通过。
- DOCX 包含所选政策的来源、版本、状态和历史/核验警告；保持 A4 与内部草稿标记。
- 管理员可导入 HTML/TXT/Markdown/DOCX、记录人工核验。DOCX表格按顺序保留文本，并标记条款切分需人工复核。
- 以[中国政府网原文](https://www.gov.cn/zhengce/content/202506/content_7026294.htm)初始化《政务数据共享条例》，原文归档 SHA256：`7a1c252d7e62da54d2539ba600d3f16c660c0487443773d9123c4f26576ef0ff`。该记录保留为 **unverified**，没有自动宣称现行。默认条款检索仅含人工核验的现行政策，查看新导入条款需勾选“包含未核验”。
- 模型出口继续 intranet；不为政策集成放开模型外网。内网模式可离线导入带来源的原文文件，URL在线抓取仍遵守原出口限制。

## 实测

| 验证 | 结果 |
|---|---|
| T2 保存前复测 | 122 passed / 5 xfailed（保留原上游漏检基线） |
| RK3588候选：T1、文稿、文件解析与DOCX回归 | **211 passed，80.16秒** |
| 前端完整 npm test | 宿主16项、Vitest **243项通过** |
| 类型检查及生产构建 | exit 0；仅既有大chunk提示 |
| 基础流程真实浏览器 | 55次真实政务HTTP请求，0页面错误 |
| 政策真实浏览器 | 官方HTML入库、条款检索、保存引用、刷新/保存、DOCX下载，0页面错误 |
| RK3588完整 app.main + 生产库副本 | 登录、上传、政策引用、退回重提、他人批准、DOCX及权限拒绝全部通过 |
| 公网实际页面 | 普通临时账号真实登录、创建保存、政策检索/引用、刷新、下载38308字节DOCX，0页面错误 |
| DOCX实物 | OOXML A4、正文、政策来源/版本/未核验提示、内部草稿标记均存在 |

Windows全量后端 pytest 的收集被既有可选依赖 `python-pptx`、`docxtpl` 缺失阻断（PPT/document/pediatric测试）。Windows原T1路由测试的网络封锁fixture还会拦截标准库事件循环的内部loopback；未削弱该fixture，转在实际Linux板端跑完整相关211项。没有将整个旧产品测试套件写成通过。

独立只读审查无Critical，三个Important问题均用先失败后通过的回归修复：DOCX表格丢文、历史版本警告丢失、政策库故障阻断文稿。没有延后的小问题。

## 部署与数据

- 公网：`http://124.223.176.99:3000/gov`。
- 当前业务代码：`0a695d7`；版本目录：`/home/youyeetoo/mqw/releases/20261026-0a695d7`。
- 入口仍为 `/home/youyeetoo/mqw/web` 和 `/home/youyeetoo/mqw/backend` 的版本软链接。
- 保留原数据库、材料、JWT和用户密码；政策库使用持久路径 `/home/youyeetoo/mqw/shared/backend-data/policy.db`。
- mqw-backend、mqw-frontend、frpc-mqw 均 active；本次没有更改FRP隧道目标。
- 成功切换前备份：`/home/youyeetoo/mqw/backups/20261026-before-policy-043931Z`。SQLite使用backup API，配置与Git元数据均有备份。
- 两次部署前检查触发了自动回退：一次是HTTP文本编码比较，另一次是既有 `config.worktree` 覆盖主配置。已修正部署检查及配置写入位置，再次切换成功；回退不覆盖业务数据库。
- 公网临时验收用户及文稿已定向清除，最终数据：168用户、1008对话、2475消息、606文件、393文档任务、0政务文稿；与原数据一致。新政策库保留一份真实官方原文。

部署证据在板端 `mqw/deploy/policy-integration-20261026.json`、`policy-public-cleanup-20261026.json`；Windows日志、截图和下载样本位于 `D:/vps_claude/artifacts/20261026/`。

## 回退

将 mqw/backend 和 mqw/web 原子切回 `releases/20261026-f7a8b20`，重启 mqw-backend、mqw-frontend；若回退配置，使用上述备份中的 config.yaml，保持原权限600。Git需使用 `git config --worktree core.worktree <旧版本目录>` 同步其独立工作区配置。保留当前业务数据库和政策库，不用旧数据库覆盖上线后的新数据。

## 仍不在本轮范围

T2产品接入、T3板端PDF验证/接入、正式发文权限、自动政策有效性判定、Word/WPS人工分页字体验收及完整旧模块测试。人工审核不等于自动审校通过。
