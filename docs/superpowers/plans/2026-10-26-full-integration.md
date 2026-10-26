# T2 T3 完整整合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在下一階段總整合分支接入 T2、驗證並接入 T3，完整驗收後合 main。

**Architecture:** 同一後端文稿為審校、批准與 DOCX 的資料來源。政策 PDF 匯入使用經 ARM64 驗證的 OpenDataLoader，失敗沿用原 OCR 回退。

**Tech Stack:** FastAPI、SQLAlchemy/SQLite、Vue/Pinia、Node gongwen-kit 0.4.4、OpenDataLoader 2.5.15、Java17。

**Spec:** docs/superpowers/specs/2026-10-26-full-integration-design.md

## Global Constraints

- 從349d082開始，保留 T1/基礎真實流程及來源引用，不 push。
- 保存、送人工審核、內部草稿可用，正式發文維持禁止。
- 審校與文稿 version 綁定，修改後失效，批准重新驗證。
- PDF 板端每頁≤3秒、峰值RSS≤1.5GB，掃描及失敗回退既有OCR。
- WPS實際驗收前不合 main（使用者已確認WPS即可）；不可聲稱未執行的項目通過。

## Review Focus

- 審校執行期間並發保存/政策狀態改變：不得批准過期版本。
- 發文字號、版記及表格刷新遺失：儲存/載入/生成必須一致。
- 機檢故障、缺少工具、過期前端狀態：不得被當作批准通過。
- PDF 無文字層、超時、損壞、混合掃描頁：保留原OCR，失敗不寫空政策。
- Word/WPS 字體替代、跨頁表格與內部草稿標記：逐頁驗收並記錄限制。

### Task 1: 保留既有交付與板端依賴

**Files:** backend/app/main.py; backend/third_party/README.md; backend/docs/spike/rk3588-checklist.md

**Interfaces:** 合入 feat/gongwen-check、spike/pdf-opendataloader，兩種API均保留。

- [ ] 解決入口合併衝突並提交；從固定上游建立離線依賴，記錄hash。
- [ ] RK3588跑T2既有測試、T3真實測試/性能，記錄服務負載及失敗回退。

### Task 2: 文稿持久化與後端審校門檻

**Files:** backend/app/gov/{schemas,service,router,export,proofread}.py; backend/tests/test_gov_gongwen_integration.py

**Interfaces:** POST documents/{id}/check(version) → OfficialDocument + review; POST approve(version)重新機檢；export從保存資料生成。

- [ ] 加入API回歸：新增欄位刷新仍在、真實anchor、修改失效、過期version拒絕、批准重檢及工具故障阻擋。
- [ ] 執行測試確認RED；擴充schema、資料轉換、check與批准流程，再驗證GREEN。
- [ ] 驗證政策狀態取自庫、非通知保留原人工流程、內部草稿含來源/未審核標記；提交。

### Task 3: 前端通知審校與導出

**Files:** web/src/features/gov-office/{types,domain/issueRules,adapters/HttpGovOfficeAdapter,components/draft/DraftFieldsForm,components/document/OfficialDocumentView,components/review/IssuePanel,pages/DraftWorkbenchPage,pages/ProofreadPage}.{ts,vue}; web/tests/gov-gongwen.spec.ts

**Interfaces:** 使用同一文稿check/export端點；真實問題只提供已實作操作；定位真實anchor。

- [ ] 加入前端RED：新欄位保存、審校按鈕、格式故障與門檻顯示、問題定位。
- [ ] 接入新欄位、表格及雙層審校資訊，保持demo行為；跑npm test/typecheck/build至GREEN並提交。

### Task 4: 政策PDF匯入與回退

**Files:** backend/app/services/policy/{extract,library}.py; backend/app/services/opendataloader_pdf_adapter.py; web/src/features/gov-office/components/policy/PolicyLibraryPanel.vue; backend/tests/test_policy_pdf_integration.py

**Interfaces:** extract_file(name,bytes) → ExtractedDocument；PDF解析中保留頁碼/表格資訊與警告，不信任PDF title。

- [ ] 測試純文字PDF、掃描/混合頁、適配器失敗、OCR失敗不落空政策及中文空白規範化，確認RED。
- [ ] 板端驗證通過後接線；保留既有OCR回退與intranet出口，確認GREEN並提交。

### Task 5: 完整業務、樣張與獨立審查

**Files:** docs/superpowers/2026-10-26-full-integration-acceptance.md; task-local測試/樣張/日誌

- [ ] 在生產庫副本跑實際完整app、前後端瀏覽器流程、雙層審校/定位/修正/重檢及PDF匯入與失敗回退。
- [ ] 樣張由Word及WPS實際輸出並逐頁檢查，缺環境則明確記錄未驗收。
- [ ] 跑完整相關後端及前端套件，做一輪獨立審查；Important問題用RED→GREEN修復。
- [ ] 所有門檻通過才合main、部署、保留bundle與回退；未通過的門檻如實報告並保留分支。
