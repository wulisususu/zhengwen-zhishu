# SDD ledger — plan: docs/superpowers/plans/2026-10-26-full-integration.md

User authorization: 明確要求依序完成第4至6步並在驗收後合main，延續已部署T1的既有方案；不重複詢問方案或例行可逆操作。

Workspace: 既有Windows isolated worktree D:/vps_claude/integration-worktrees/basic，分支feat/full-integration，基線349d082；原feat/basic-integration引用保留。

Pre-flight: Task2 produces persisted fields/review metadata consumed by Task3; Task1 ARM64 GO gates Task4; Task5 Word/WPS and full workflow gate main merge.

Ruling: 直接沿用使用者已明確選定的逐批整合路線，在現有框架內完成 — 省去重複方案批准，需求改動可回退到349d082。

Baseline: RK3588 aarch64, Java17.0.20.1, Node22.22.2, mqw-backend/frontend/frpc均active；模型8002正在監聽，8003未監聽，必須如實驗證OCR可用性。

Task 1: in progress. T2入口衝突只需同時保留gov與gov_docs路由；T1部署版本與資料不動。
