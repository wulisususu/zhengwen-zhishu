# 公文生成与双层审校接口（通知，gongwen-kit）

分支 `feat/gongwen-check`。评估依据见 `docs/spike/gongwen-kit.md`（S1 + 复测）。

## 定位与分工

| 谁 | 负责 |
|---|---|
| gongwen-kit 0.4.4 | 按 GB/T 9704 生成通知 DOCX；它已支持的写法类机检（发文字号写法、日期虚位、半角标点、异形词、表格合计等）；外来 Word 的可选版式修复 |
| InNet_box（本模块） | 应有要素是否缺失、层次序号是否连续、「共 N 项」与列项是否一致、成文日期等关键字段是否完整、政策引用是否存在；审核状态与正式导出的门槛 |
| 政策库（另一任务） | 政策有效性核验。未接入前本模块一律报「未核验」，不采信前端传来的状态 |

只做「通知」一种文种。

## 数据流

```
NoticeDraft(JSON) ─校验(pydantic)─┬─ 自研规则 rules.py ───────────────────────────┐
                                  └─ converter.py → 固定构件 spec ─ Node 桥 ─ DOCX ─ gongwen check --json ─ 逐条解析 ─┤
                                                                                                                  ├─ ReviewIssue[] + issueDetails + gate
```

- **不生成也不执行任意 JS。** converter 只产出纯数据的构件表，类型限于
  `letterhead title zhusong p h1-h4 table fujian luokuan fuzhu banji`。
  固定入口 `app/services/gongwen/node/render_notice.js` 会再校验一遍类型、字段、长度和控制字符：
  未知类型、多余字段一律拒绝，每种构件只对应一个 gongwen-kit 调用。
  gongwen-kit 目录和输出路径取自配置与后端临时目录，不来自请求。
- 子进程一律用参数数组（不用 `shell=True`），放在独立进程组里，超时整组 kill。
  环境变量最小化，只透传 `GONGWEN_FONT_*`，同时运行的 Node 进程有上限。调用方走线程池，不阻塞事件循环。
- 层次序号按结构自动编号：草稿里手打的「一、」「（一）」生成时去掉，由 gongwen-kit 编号，
  所以 DOCX 里的序号总是连续的。草稿手打序号跳号，由自研规则报出。
- 空字段生成为醒目的「【待补充：××】」，不会悄悄消失。

## 接口

都要会话（复用 `get_current_user`）。前端不设登录页，会话来自角色入口 `POST /gov/entry`（见 `docs/role-entry.md`）。前缀 `/api/v1`。业务错误沿用 `ok()/fail()` 的 `{code, message, data}`。

### POST /gov/notices/review

请求体：`NoticeDraft`（见下节）。同步执行，x86 实测约 1.4 s（生成约 0.9 s，含 gongwen-kit 出稿自检；格式机检约 0.5 s）。

响应 `data`（缺陷样例的真实输出，截取；完整版见 `docs/gongwen-samples/review_defective_notice.json`）：

```json
{
 "origin": "backend", "docType": "notice", "reviewedAt": "2026-10-26T02:42:58+00:00",
 "issues": [
  {"id": "own-elem_recipient-2b40731029", "severity": "critical", "source": "rule", "title": "缺少主送机关",
   "description": "通知须写明主送机关，当前为空。", "locationLabel": "主送机关", "anchor": "seg-recipient",
   "section": "head", "requiredField": "recipient"},
  {"id": "own-elem_banji-f7a8628765", "severity": "critical", "source": "rule", "title": "缺少版记（印发机关和印发日期）",
   "description": "版记缺少印发机关、印发日期（GB/T 9704 7.4）。", "locationLabel": "版记", "anchor": "", "section": "banji"}
 ],
 "issueDetails": {"gwk-…": {"code": "GWK_DOCNO", "layer": "gongwen-kit", "check": "体例", "ruleName": "发文字号",
                            "blocking": true, "anchorPrecision": "segment", "fragments": ["[2025]"]}},
 "formatCheck": {"status": "hit", "toolVersion": "0.4.4", "sha256": "9772…", "seconds": 0.452,
                 "hitCount": 3, "blockingCount": 3, "hintCount": 0},
 "summary": {"critical": 8, "warning": 2, "hint": 2},
 "gate": {"canSubmit": true, "canExportInternalDraft": true, "canApprove": false, "canExportFormal": false,
          "blockingIssueIds": ["…8 个…"], "reasons": ["存在 8 个严重问题，须先修改（严重问题的例外审批尚未接入后端）"],
          "formalExportReasons": ["…", "正式导出需要审批记录与正式发文权限，后端审批流程尚未接入"]},
 "policyVerification": {"status": "not_available", "message": "政策库尚未接入，政策有效性（现行/废止）未经后端核验；前端提供的状态不作为核验结果。",
                        "refs": [], "citedTitles": ["示例市政务数据安全管理办法"]}
}
```

`formatCheck.status`：`pass` / `hit` / `unavailable`。工具故障时为 `unavailable`，同时多一条严重问题
「格式机检未完成」，`gate.canApprove=false`。**工具故障永远不会被当成通过。**

### POST /gov/notices/export

请求：`{"draft": NoticeDraft, "kind": "internal_draft" | "formal"}`。

- `internal_draft`：任何登录用户都可以导出，有严重问题也可以（产品规则：内部草稿总能保存、提交、导出）。
  返回 DOCX，每页页眉印「内部草稿 · 未审核 · 不得作为正式公文使用」。
  响应头 `X-Gongwen-Export-Kind: internal_draft`、`X-Gongwen-Reviewed: false`，
  文件名用 `filename*=UTF-8''…`。
- `formal`：没有正式发文权限时返回 403；有权限时后端**重新跑一遍完整审校**，再按门槛决定。
  后端还没有审批记录，所以目前**一律拒绝**，返回 `code 40900` 和门槛详情：
  ```json
  {"code": 40900, "message": "后端审批流程尚未接入，不能正式导出",
   "data": {"gate": {"canApprove": true, "canExportFormal": false, "blockingIssueIds": [], "…": "…"},
            "summary": {"critical": 0, "warning": 0, "hint": 1}, "formatCheck": {"status": "pass", "…": "…"}}}
  ```
  有严重问题时，message 为「存在未解决的严重问题或格式机检未完成，不能正式导出」。
- 工具故障：`{"code": 50300, "message": "找不到 Node.js（…），需要 Node >= 18", "data": {"error": {"code": "NODE_NOT_FOUND", …}}}`。

### POST /gov/docx/check（外来 Word）

multipart `file`。只收 `.docx`，并核对 ZIP 文件头（改了扩展名的文本文件会被拒绝；S1 实测 gongwen-kit 遇到这种文件会报假命中）。
大小上限 `max_upload_mb`，默认 10 MB。上传内容以固定文件名写入私有临时目录，用完即删。

返回结构同 review，多两项：`docType: "external_docx"`；
`file: {name, bytes, sha256, unchanged: true}`（检查后比对上传字节，确认没被改动）。
外来文件只做**格式机检 + 层次序号 + 数量描述**，按段落定位（`anchor` 为 `p-<段序号>`，`locationLabel` 为「第 N 段」）。
公文要素与政策引用依赖结构化字段，外来文件不做，响应 `coverage` 会写明。

参数错误：`{"code": 40000, "message": "只接受 .docx 文件"}`，以及「文件超过 10 MB」「文件不是 DOCX（ZIP）格式」。

### POST /gov/docx/fix（外来 Word，可选）

只输出副本：原件写在临时目录里，修复写到另一个文件，前后比对原件哈希。gongwen-kit 自己也拒绝覆盖输入文件。
返回：

```json
{"filename": "通知-修订.docx", "docxBase64": "UEsDB…", "report": "修复完成 …",
 "original": {"name": "通知.docx", "sha256": "596c…", "unchanged": true},
 "postReview": {"formatCheck": {"status": "pass", "…": "…"}, "…": "…"},
 "complianceClaim": false,
 "complianceNote": "fix 只调整版式……修复后格式机检通过不代表符合 GB/T 9704 全部要求：标题、层次、列表、表格、落款、版头、版记必须人工核对……"}
```

`complianceClaim` 恒为 `false`。修复后的再审校只做参考：复测已证实标题、层次、列表、表格、落款修不好，版头和版记也不会补。

## 输入模型 NoticeDraft

与前端 `OfficialDocument` 对齐，多出的键（origin、status、issues、history…）忽略。

| 字段 | 说明 |
|---|---|
| `docType` | 只能是 `"notice"` |
| `title`、`titleLines?` | `titleLines` 是按意群断好的行，拼起来必须等于 `title` |
| `docNumber {id, text}` | 例：`{"id": "seg-docno", "text": "示办发〔2026〕8号"}`。写法由 gongwen-kit 检查 |
| `fields {recipient, issuer, undertaker}` | 发文机关同时用于版头标志与落款 |
| `blocks[]` | `{id, kind, section, segments[], table?}`；kind：`recipient paragraph heading1-4 attachment signature table`；segments 同前端（`text` / `field`） |
| `signDate` | 成文日期 |
| `note?` | 附注，如「（此件公开发布）」 |
| `policyRefs[]` | `{id, title, clause, status}`；status 只回显，不作为核验结果 |
| `banji? {copyTo[], printer, printDate}` | **新增**：版记。前端模型目前没有 |
| `table` 块 `{caption, head[], rows[][]}` | **新增**：前端 `BlockKind` 目前没有 |

限制：id 只允许 `[A-Za-z0-9_.:-]{1,64}` 且全局唯一；文本不得含控制字符；正文总长 ≤ 10 万字；表格 ≤ 8 列、≤ 200 行。

## ReviewIssue 字段来源

| 字段 | 自研规则 | gongwen-kit 命中 |
|---|---|---|
| `id` | `own-<规则码>-<哈希>`，同一输入稳定 | `gwk-<哈希>` |
| `severity` | 规则码对应的固定级别（`catalog.OWN_RULES`） | 按每条命中的 `blocking`：true→`critical`，false→`hint`（`catalog.KIT_SEVERITY`）。同一规则两档都可能出现，所以**不按规则名定级别** |
| `source` | `"rule"` | `"rule"` |
| `title` | 规则中文名 | 工具规则名（如「发文字号」） |
| `description` | 规则生成的说明 | 工具 `detail` 原文 |
| `locationLabel` | 所在一级标题文字 / 「主送机关」「落款」「版记」等 | 同左，由文本索引定位；无定位时为「全文」，表格类为「表格」 |
| `anchor` | 草稿里真实存在的 segment id / block id，没有就是 `""`，**从不编造** | 用命中片段回查草稿：命中 segment 用 segment id，否则用 block id；片段匹配多处时取第一处并标记 |
| `section` | 块的 `section` | 同左；无定位时为 `document` |
| `suggestion` | **不填**：两层都给不出结构化的 segmentId + replacement | **不填** |
| `requiredField` | 缺发文机关→`issuer`，缺主送→`recipient`，缺承办→`undertaker` | 不填 |

前端类型里没有的信息放在 `issueDetails[id]`：`code`、`layer`（`own` / `gongwen-kit`）、
`anchorPrecision`（`segment` / `block` / `text_snippet_ambiguous` / `none`）、`blocking`、`ruleName`、`fragments`、
`candidates`（多处匹配时列出全部候选）、`mergedRules`（被合并掉的重复命中）、`expected/actual`、`stated/listed`。

### 自研规则（catalog.OWN_RULES）

| 码 | 级别 | 内容 |
|---|---|---|
| ELEM_TITLE / ELEM_ISSUER / ELEM_RECIPIENT / ELEM_DOCNO / ELEM_BODY / ELEM_SIGN_DATE / ELEM_BANJI | critical | 应有要素缺失（版记指印发机关和印发日期） |
| ELEM_UNDERTAKER | warning | 正文引用了承办部门字段但为空 |
| TITLE_DOC_TYPE | warning | 标题不以「通知」结尾 |
| TITLE_LINE_BREAK | hint | 标题超过一行（约 20 字）且没有给 titleLines |
| SIGN_DATE_FORMAT / SIGN_DATE_INVALID | critical | 成文日期不是完整的「×年×月×日」（如 `2026-10-26`、只有年月）或不是有效日期。虚位、汉字数字归 gongwen-kit 报 |
| BANJI_DATE_FORMAT | warning | 印发日期不完整 |
| NUMBERING_GAP | critical | 标题、段首序号或段内「一是、二是」不连续；只在断点处报一次 |
| NUMBERING_LEVEL | warning | 序数形式与标题层级不符 |
| COUNT_MISMATCH | critical | 「共/以下/如下/下列/包括 N 项（条、点、方面…）」与其后的下一级标题、带序号段落、段内序号条数不一致；句子不是列举引导句（没有冒号、也不是以下/如下/下列）时不判 |
| COUNT_MISMATCH_INLINE | warning | 同上，但条数按分号数出，可能误判 |
| POLICY_REF_UNLINKED | warning | 正文《…》未在 policyRefs 中关联 |
| POLICY_REF_UNCITED | hint | policyRefs 里的依据正文没有引用 |
| POLICY_REF_UNVERIFIED | hint | 只要涉及政策依据就报：政策库未接入，有效性未核验 |
| FORMAT_CHECK_UNAVAILABLE | critical | 格式机检没能完成（工具缺失、超时、输出异常） |

### gongwen-kit 结果的处理

- 逐条读 `checks[].hits[]`，不看退出码下结论。只有退出码、`status`、`blocking` 汇总数、逐条命中、
  文档 sha256 五者一致才采信；任何不一致都按工具故障处理（`INCONSISTENT` / `BAD_OUTPUT` / `TOOL_FAULT`）。
- 提示级命中（`blocking:false`）保留为 `hint`，不丢弃，也不升级。注意：python-docx 一类没有声明表头行的表格，
  合计错只是提示；本模块生成的表格都声明了表头，合计错是 `critical`。
- 去重：完全相同的命中只留一条；实测的重叠（半角括号同时被「半角括号」「中文里的半角标点」报出）合并成一条，
  记在 `mergedRules`，只在能确认被覆盖时才合并。
- 规则名不在 `catalog.KIT_RULE_CODES` 里的，仍然输出，码为 `GWK_UNMAPPED`，并写警告日志。

## 后端门槛（gate）

- `canSubmit`、`canExportInternalDraft`：恒为 true。
- `canApprove`：格式机检已完成，且没有 `critical`。严重问题的「例外审批」需要后端持久化审批记录，目前没有，
  所以只能先修改。
- `canExportFormal`：恒为 false，等审批记录入库后再放开。正式导出接口会重新跑完整审校，不信任前端结论。
- 正式发文权限：后端目前只有 admin / user，暂用 admin 代替（`gov_docs.can_formal_issue`）。

## 错误码

| code | 含义 | data |
|---|---|---|
| 40000 | 参数错误（非 .docx、超限、非 ZIP、生成参数被拒，如发文机关标志过长） | `error.code`：`INVALID_INPUT` / `RENDER_REJECTED` |
| 40900 | 后端门槛拒绝正式导出 | `gate`、`summary`、`formatCheck` |
| 50300 | 格式工具不可用或失败 | `error.code`：`NODE_NOT_FOUND` `KIT_NOT_FOUND` `TIMEOUT` `BUSY` `TOOL_FAULT` `BAD_OUTPUT` `INCONSISTENT` `RENDER_FAILED` `FIX_FAILED` |
| 401 / 403 / 422 | 未登录 / 无正式发文权限 / 请求体不合模型 | FastAPI 默认 |

40900、50300 定义在 `app/services/gongwen/catalog.py`，没有加进 `app/errors.py`（政策检索分支也在改那个文件）。

## 部署

- Node ≥ 18（验证机 v22.23.4）。gongwen-kit 用 clone（固定提交）+ `npm ci` 或离线包，见 `backend/third_party/README.md`。
- `config.yaml` 新增：

  ```yaml
  gongwen:
    kit_path: third_party/gongwen-kit
    node_bin: node
    check_timeout_seconds: 20
    render_timeout_seconds: 30
    fix_timeout_seconds: 30
    max_upload_mb: 10
    max_concurrent: 2
  ```
  不配也行，全部有默认值。没有 Python 新依赖，`requirements.txt` 不变。不用 Docker。
- 字体：方正小标宋、仿宋、黑体、楷体由目标机器提供，生成时只写字体名。

## 测试

```bash
cd backend
pytest tests/test_gongwen_rules.py          # 自研规则、构件转换、报告解析、问题映射（不需要 Node）
pytest tests/test_gongwen_integration.py    # 真实生成、双层审校、外来检查与修复、工具异常（需要 Node + gongwen-kit）
pytest tests/test_gov_docs_router.py        # 接口：登录、权限、门槛、上传限制、原件保护、工具不可用
pytest tests/test_gongwen_kit_s1.py         # S1 / 复测基线
```

没装 Node 或 gongwen-kit 时，需要它们的用例自动 skip。

## 已知限制与未验证

- Word / WPS 渲染没有验过；本机只用 LibreOffice 看过版面（字体被替换），样张见 `docs/gongwen-samples/`。
- 标题超过一行时，程序不替人断行，只提示补 `titleLines`。
- 外来 Word 的公文要素、政策引用不检查；段落层级靠文字序数推断，Word 自动编号的标题看不到序号。
- 「共 N 项」只认引导句加冒号的写法，以及其后的下一级标题、带序号段落、段内序号或分号列举。
- 审批记录、例外审批、正式发文权限都还没有后端实现，正式导出目前一律被拒。
- 前端仍是 Mock 适配器，HTTP 适配器与 `banji`、`table` 字段尚未接入前端（本轮按要求未改 web/）。
- 板端（RK3588）性能未测。
