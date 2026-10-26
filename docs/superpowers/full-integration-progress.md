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

Task 4: complete in 8a59ed0 plus review fix pass. 真實板端掃描、混合頁、Java缺失、JVM超時、損壞檔全部按預期回退/拒絕；掃描全文用原全頁CPU OCR，不用圖片摘要冒充全文。

Final review: fresh read-only reviewer; 0 Critical, 5 Important, 1 Minor. Important全部同一修復輪次RED→GREEN：政策狀態競態與鎖、混合PDF物理頁、全文OCR、前導空白序號、承辦與部分版記保留。14項修復回歸通過，完整相關板端403 passed / 2 skipped / 5 xfailed；WPS修正後再次完整回歸403 passed，168.90秒。

Final: minor (deferred): HTML預覽尚未顯示titleLines手工分行；保存與DOCX分行正確。代價是頁面與實際樣張換行可能不同，DOCX應以WPS為準。

Final: Ruling: ARM64/真實流程/WPS由執行方實測裁定通過 — 有15次性能、72次真實API流程及四類10頁WPS證據 — 代價是未涵蓋其他型號或Office環境。
Final: Ruling: 正式發文、例外放行及非通知/非文字材料生成維持原限制 — 本次要求內部草稿且既有權限尚未配置 — 代價是這些擴充仍須後續開發。
Final: Ruling: 保留按結構重新編號，原稿跳號仍報嚴重問題且必須修改才批准 — 與T2既定設計一致 — 代價是錯稿內部DOCX編號可與原輸入不同。
Final: Ruling: 批准完成後政策才改變不自動撤銷歷史批准 — 使用者未要求撤銷流程，正式發文仍禁止 — 代價是使用舊稿時仍須核對當前依據。
Final: Ruling: 沒有既有Graphify圖，直接讀程式完成審查 — 不為驗收增加建圖流程 — 代價是未提供關係圖。

Task 5: verification complete; main merge and deployment in progress under user's explicit authorization. WPS是實際KWPS COM輸出，10頁逐頁目視與A4/每頁草稿標記均通過；保留一項HTML預覽Minor。

Public verification follow-up: 初次公網發現背景載入覆寫早期編輯；Vue完整頁面測試RED→GREEN，7d1e0e8修復。前端16 host + 249 Vitest通過，typecheck/build通過。0cf7c6d合main並部署，刻意延遲真實HTTP回應的公網實測通過；2問題可定位，修正後0 critical，刷新與DOCX成功，0頁面錯誤。

Task 5: complete. WPS追加公網實物2頁，合計5份12頁。Windows與板端main同步；原分支及既有工作區保留，未push。生產臨時帳號/文稿已清理，使用者168/會話1008/消息2475/文件606/任務393維持原值。release 20261026-0cf7c6d；備份20261026-before-full-054423Z。最終驗收文件與復原bundle隨本輪收尾保存。
