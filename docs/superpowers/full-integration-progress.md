# SDD ledger — plan: docs/superpowers/plans/2026-10-26-full-integration.md

User authorization: 明確要求依序完成第4至6步並在驗收後合main，延續已部署T1的既有方案；不重複詢問方案或例行可逆操作。

Workspace: 既有Windows isolated worktree D:/vps_claude/integration-worktrees/basic，分支feat/full-integration，基線349d082；原feat/basic-integration引用保留。

Pre-flight: Task2 produces persisted fields/review metadata consumed by Task3; Task1 ARM64 GO gates Task4; Task5 Word/WPS and full workflow gate main merge.

Ruling: 直接沿用使用者已明確選定的逐批整合路線，在現有框架內完成 — 省去重複方案批准，需求改動可回退到349d082。

Baseline: RK3588 aarch64, Java17.0.20.1, Node22.22.2, mqw-backend/frontend/frpc均active；模型8002正在監聽，8003未監聽，必須如實驗證OCR可用性。

Task 1: in progress. T2入口衝突只需同時保留gov與gov_docs路由；T1部署版本與資料不動。

Task 1: complete. 合併保存c5462be、494dac2。RK3588原T2/T3套件169 passed / 5 xfailed。15次性能全部達標：28頁1.86–1.92s；50頁3.23–3.55s；70頁批量6.43–6.71s，最高569700KB RSS。MiniCPM8091及文字模型8002持續運行。

Task 2/3: complete in 6e833b3. Windows T2相關156 passed / 5 xfailed，新API9項與前端4項先RED後GREEN。Windows最小子程序環境缺SystemRoot導致Node亂數初始化失敗、POSIX killpg無法Windows終止，均已真實Node測試RED→GREEN修復。

Ruling: Git將ASCII形式PDF誤作文字而破壞xref；增加二進位attributes並在板端重建樣本 — 避免錯把損壞樣本歸咎ARM64，代價是樣本位元組hash改變；官方A-D完全未改。

User clarification: WPS實機驗收即可；不要求額外Microsoft Word環境。已確認WPS COM實際路徑D:/WPS Office/12.1.0.25225/office6。

Task 4: in progress. PDF匯入8項及原T1文稿引用10項通過；新增歷史政策不可批准及PDF頁碼前端回歸。
