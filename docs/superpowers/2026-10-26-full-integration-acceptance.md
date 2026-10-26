# T2 T3 與整體業務驗收

日期：2026-10-26（Asia/Shanghai）。承接已部署的349d082，在feat/full-integration逐批整合。使用者明確要求驗收後合main，並確認WPS實機驗收即可。GitHub main經連接器重查仍為aeee82b，未執行push。

## 功能驗收

- T2：通知的發文字號、版記、抄送、附注、標題分行及表格可保存並刷新恢復。前端呼叫後端雙層規則審校，顯示真實問題與anchor；無定位的工具故障明示全文問題，不編造頁碼。可實際生成通知初稿與下載內部DOCX。
- 批准使用保存的後端文稿，重新跑規則與gongwen-kit；內容修改會使舊結果失效。批准前再核政策狀態，最後核對至文稿提交期間以SQLite BEGIN IMMEDIATE阻擋政策庫寫入。文稿仍以CAS防止並發覆寫。工具失敗、廢止或歷史版本依據不能冒充通過。
- T3：僅政策PDF入口開啟OpenDataLoader；一般文件解析與原OCR入口保持原樣。文字PDF保存物理頁碼、條款、來源及原PDF SHA256定位。內網模式可離線匯入；URL直接下載PDF仍遵守原抓取限制，可改上傳文件。
- 掃描/混合頁與適配器失敗回退原解析鏈路。政策匯入額外使用原全頁渲染與CPU OCR做全文轉錄，不能把MiniCPM的96/128-token圖片摘要當政策全文。缺頁或OCR失敗不落入空/殘缺政策。
- 正式發文、忽略問題及例外放行仍未開放；非通知文種沿用原人工流程。新政策保持未核驗，系統不自動宣稱法規現行。

## 實測證據

| 項目 | 結果 |
|---|---|
| RK3588完整相關後端回歸 | **403 passed / 2 skipped / 5 xfailed，168.90秒** |
| Windows新API及回歸 | 49 passed；最後DOCX/政策/批准關聯套件23 passed |
| 前端完整npm test | 宿主16項、Vitest **248項通過** |
| 型別檢查及生產build | exit 0；保留既有大chunk提示 |
| 真實瀏覽器完整app.main | 72次真實gov HTTP請求，0頁面錯誤；實際模型生成109字 |
| 真實業務流程 | 登入→新建→上傳→模型生成→保存→雙層檢查→定位→錯稿導出→送審→退回→修改要素/序號/表格→引用PDF政策→刷新→重檢→重提→他人批准→DOCX下載；跨用戶拒絕 |
| WPS實機 | 四類樣張10頁；實際KWPS COM路徑D:/WPS Office/12.1.0.25225/office6，A4與每頁內部草稿標記全部存在，逐頁目視未見文字/表格裁切或重疊 |

2 skipped是Windows專用Node環境/程序終止測試，在Windows已實跑通過；5 xfailed是原gongwen-kit獨立檢查的已知漏檢，不是雙層規則的漏檢。403項覆蓋全部T1政策套件、T2/T3及原文稿/權限/文件解析/DOCX回歸，不冒稱整個歷史PPT及其他舊模組套件全部通過。Windows整個舊後端套件先前仍受python-pptx/docxtpl等可選依賴收集限制。

WPS樣張包括：正常通知與政策附件3頁、長正文及20行表格4頁、要素待補通知1頁、帶錯通知2頁。所有頁面已實際從WPS輸出PDF並轉PNG檢查；來源附錄改左對齊，短通知不再因額外審校說明多出一頁。WPS輸出包含FangSong/SimSun/SimHei及WPS字體子集；此驗收不宣稱所有電腦字體相同，也不等同正式發文合規認證。

## RK3588性能

實機aarch64、32GB RAM、Java17.0.20.1、Node22.22.2，MiniCPM8091與文字模型8002服務同時運行。固定OpenDataLoader2.5.15，jar SHA256與x86完全相同：`ffdd88056be30845efc6b6e6981fe4dda35ec323a08d2d70b48c80d18cd4bd20`。JVM固定-Xmx512m，同時最多一個。

| 用例（三次） | 整份耗時 | 峰值RSS最大值 | 結果 |
|---|---|---|---|
| 官方D，28頁 | 1.86–1.92s | 335076KB | GO |
| 合成50頁 | 3.23–3.55s | 298376KB | GO |
| 官方A–D批量70頁 | 6.43–6.71s | 569700KB，約556MB | GO |
| 官方A+B+D文字54頁 | 2.53–2.86s | 425420KB | GO |
| 合成多列表格1頁 | 0.98–1.03s | 109244KB | GO |

全部15次均符合文字解析每頁≤3秒、峰值≤1.5GB。真實解析測試核對A/B/D頁碼及bbox、合成表格行列、C掃描件無文字層。50頁明確是合成樣本，未充作官方樣本。

實際故障回退：0.01秒JVM超時後0.482秒完成原文字解析；缺Java後0.102秒回退；1頁掃描全文OCR6.053秒，文字+掃描2頁5.966秒，均保留完整頁號；損壞PDF拒絕。OCR耗時不屬於文字PDF的≤3秒門檻。舊MiniCPM-v2 runner路徑在此機不存在，原鏈路會走現有CPU OCR；政策全文採同一CPU OCR全頁轉錄，未宣稱實際使用了MiniCPM轉錄。

## 獨立審查及處理

一輪新上下文唯讀審查，0 Critical、5 Important、1 Minor。所有Important已用先失敗後通過的回歸修復：

1. 審校期間政策失效競態：Node結束後重新讀取，批准最後階段持政策SQLite寫鎖直到文稿commit。測試`test_policy_revoked_while_node_runs_blocks_approval`、`test_policy_guard_blocks_updates_until_approval_commit`。
2. 混合PDF頁號錯亂/Markdown黏連：保留原OCR呼叫，另從原文字層form feed重建物理頁。測試`test_legacy_mixed_pages_keep_original_page_numbers_despite_merged_markdown`；板端真實混合件通過。
3. 圖片摘要誤作全文：政策掃描頁必須全頁CPU OCR，不用受96/128-token上限限制的摘要。測試`test_policy_scan_uses_full_page_transcription_instead_of_image_summary`，包含第60條末條。
4. 前導空白造成重複序號：分類、規則與生成使用一致的標題文字，保留原段落id。測試`test_indented_heading_keeps_ids_and_does_not_double_number`。
5. 承辦及部分版記遺失：生成保留承辦、已填抄送/印發機關，缺日期顯式佔位。測試`test_internal_export_retains_undertaker_and_partial_banji`。

延後Minor：HTML預覽尚未按titleLines顯示手工分行；保存及DOCX使用正確分行。內部DOCX實物以WPS樣張為準。

審查未裁定事項由執行方處理：ARM64/真實流程/WPS以本次實測驗收；正式發文/例外權限維持關閉；其他文種及非文字材料模型生成沿用基線限制；結構化重新編號時保留原文並報嚴重問題；政策在批准完成之後才變更不自動撤銷舊批准；無現成Graphify圖時直接讀程式，不另建圖。

## 保存與部署

Windows倉庫D:/innet-agent-ai-box，整合工作區D:/vps_claude/integration-worktrees/basic。原T1/T2/T3與feat/basic-integration分支保留，開發VPS原會話與工作區未重置。程式分批提交6e833b3（T2）、8a59ed0（T3），最終修復提交可由本報告相鄰Git歷史查閱。

驗收產物位於D:/vps_claude/artifacts/20261026-stage2/：性能、回退、完整測試日誌、真實瀏覽器截圖、WPS樣張與逐頁PNG。實際合main/部署版本、資料計數及備份路徑以部署後`deployment-final.json`及板端`mqw/deploy/full-integration-20261026.json`為準。

部署須先SQLite backup及私人配置備份，再原子切換backend/web軟連結。回退切回20261026-0a695d7版本與先前配置，重啟mqw-backend/frontend；保留當前業務及政策資料庫，不以舊備份覆蓋上線後新增資料。
