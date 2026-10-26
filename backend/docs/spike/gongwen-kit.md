# gongwen-kit 公文机检接入：S1 验证报告

- 日期：2026-10-25　分支：`feat/gongwen-check`（自 main `aeee82b`）
- 对象：gongwen-kit 0.4.4（`b67ced1`，MIT），`node bin/gongwen.js check`
- 环境：Linux x86_64，Intel Xeon E5-2690 v4（2 核），Node v22.23.4，npm 10.9.9
- 复现：`python tests/spike/gongwen_s1_bench.py`；`pytest tests/test_gongwen_kit_s1.py`

## 结论：NO-GO（停在 S1，未做 S2）

| 门槛 | 要求 | 实测 | 结果 |
|---|---|---|---|
| 必错样本检出 | ≥ 4/5 | **0/5** | ✗ |
| 合规样本误报 | ≤ 1/3 | 0/3（ok_03 有 2 条命中，经核实是真问题，见下） | ✓ |
| check 单份耗时 | ≤ 5 s | 0.47–0.71 s | ✓ |
| `--json` 可稳定解析 | 是 | 10/10 份可解析；故障时也输出 JSON | ✓ |

检出率一项不达标，按任务书不做适配器、接口与 config 改动。

漏检不是样本做坏了：五份必错样本都由同一份基线各改一处生成，基线零命中，
逐段比对确认每份只差埋的那一处（`tests/fixtures/gongwen/README.md`）。
读 `checks/check-doc.js` 源码也对得上：0.4.4 **没有**以下规则——

| 样本 | 为什么查不出 |
|---|---|
| bad_01 「共 5 项任务」只列 3 项 | `check-num` 的计数规则只认「以下／如下／下列 + 数 + 项／点／方面…」。「共 5 项」不在其列。同一个错换成「以下五项」（probe_01b）能报出 |
| bad_02 一、二、四 | 没有层次序数连续性规则；只查「1.1 式编号」与「标题重复编号」 |
| bad_03 缺发文机关标志与发文字号 | 没有要素是否存在的规则；发文字号只查写法（〔〕、「第」、虚位） |
| bad_04 成文日期 `2026-10-26` | 「日期简写」正则 `\d{4}-\d{1,2}(?!\d)(?!-)` 有意排除完整的 `YYYY-MM-DD`（GB/T 15835 允许该写法），且不区分「成文日期」与正文日期 |
| bad_05 版记缺失 | 没有版记是否存在的规则 |

gongwen-kit 的定位是「出稿自检 + 写法规范」，它查的是**写错了**，不查**缺了**、**跳了**；
而我们审校最想拦的正是要素缺失与结构错误。

## 实测数据

### 逐份结果（`check --json`）

| 样本 | 类别 | 退出码 | status | 命中 | 耗时 | md5 前后一致 |
|---|---|---|---|---|---|---|
| bad_01_count_mismatch | 必错 | 0 | pass | — | 0.541 s | ✓ |
| bad_02_heading_gap | 必错 | 0 | pass | — | 0.508 s | ✓ |
| bad_03_no_letterhead | 必错 | 0 | pass | — | 0.513 s | ✓ |
| bad_04_date_iso | 必错 | 0 | pass | — | 0.471 s | ✓ |
| bad_05_no_banji | 必错 | 0 | pass | — | 0.712 s | ✓ |
| ok_01_upstream_notice | 合规 | 0 | pass | — | 0.493 s | ✓ |
| ok_02_upstream_qingshi | 合规 | 0 | pass | — | 0.476 s | ✓ |
| ok_03_markdown_to_docx | 合规 | 1 | hit | 公文版式 ×2 | 0.507 s | ✓ |
| baseline_control | 对照 | 0 | pass | — | 0.509 s | ✓ |
| probe_01b_count_yixia | 探针 | 1 | hit | 计数与列举 | 0.493 s | ✓ |

10 份连续总耗时 5.23 s。

**ok_03 的两条命中不是误报。** 后端 `markdown_to_docx` 产出的是 US Letter
（`pgSz 12240×15840`），页边距为 Word 默认值（`pgMar top/bottom 1440，left/right 1800`），
`docGrid linePitch 360`，确实不合 GB/T 9704 8.1。文案「版心 top、bottom、left、right 不合
GB/T 9704 8.1（上 37 下 35 左 28 右 26 mm）」可读。附带发现两点：gongwen-kit 不查纸张大小，
没有指出「不是 A4」；我们的 DOCX 链路如果要出公文，版式需要单独处理（本任务不改该文件）。

### 验证清单

1. **必错样本**：0/5 命中，见上表。唯一能报出的形态（probe_01b）文案为
   「计数与列举：「以下五项」其后列了 3 个下一级标题」，可读。
2. **合规样本**：误报 0。ok_03 的 2 条命中是真问题。
3. **`--json` 结构**：见下节样例。可以稳定解析出 {规则, 级别, 描述, 定位}，但有以下限制：
   - **没有规则编号**。`rule` 是中文显示名（如「公文版式」），同一份报告里可重复出现，
     随版本可能改名。要做稳定 id，只能在我方维护「规则名 → 编号」表。
   - **级别只有两档**：`blocking: true/false`（拦稿／提示）。同一条规则可能两档都出现，
     例如表格类规则在表头声明了 `tblHeader` 时拦稿，否则只提示。所以 severity
     必须按每条命中的 `blocking` 定，不能按规则名定。
   - **定位只是文本片段**：`anchors` 是原文片段字符串数组（表格类为 `{text, table}`），
     **没有段落序号、没有页码**。版式类命中 `anchors` 为空数组；`文风` 的命中**没有
     `anchors` 字段**。要得到段落序号，需由适配器拿片段回原文搜；同一片段出现多次
     （如日期出现在落款与版记）时无法唯一定位。
4. **退出码**：与文档一致。`--json` 时 0=pass，1=hit（有拦稿命中），2=fault。
   - 实测 fault：非 zip、截断 zip、缺 `word/document.xml`、文件不存在，均为 2 且 stdout 仍是 JSON。
   - 注意：只有**提示级**命中时 status 仍为 `pass`、退出码 0。
   - 注意：不加 `--json` 也不加 `--strict` 时，有拦稿命中**退出码也是 0**，接入时必须用 `--json`。
   - 注意：把 docx 改成 `.txt` 扩展名送进去，`check-doc` 按 zip 读、`check-style` 按纯文本读，
     会报出一条假的「中文里的半角标点」（status=hit）。调用方必须自己校验 `.docx` 后缀。
   - node 不存在时由调用方的 `FileNotFoundError` 体现，工具本身不给退出码。
5. **原文件不改**：所有 check 前后 md5 一致（bench 脚本逐份比对）。示例：
   `710b8b8f…2b44b7ac` 在 check、`fix --dry-run`、`fix` 之后均不变。
6. **中文与特殊文件名**：`关于 开展培训的通知（第2稿）[终版].docx`（目录名也含空格和括号）、
   `'quote' & $x;semi.docx` 均正常；`report.file` 原样回显 basename。
7. **fix**：`--dry-run` 只打报告，不生成文件，原件 md5 不变；`fix` 输出 `<原名>-修订.docx`，
   原件 md5 不变。ok_03 修后版式变为 A4、`pgMar 2098/1984/1587/1474`、`linePitch 579`。
8. **修后再查**：ok_03 修后 `pass`，问题消失。另造一份含「10月06日」「【2026】第012号」的稿子，
   修复写成 5 处修订痕迹，修后再 check 为 `pass`——**check 把未接受的修订当作已接受**。
   如果审核人在 Word 里拒绝修订，问题会回来，check 无法区分。bad_04 修复不涉及日期（因为没检出）。
9. **性能**：上游 2～5 页样张（要素全览 5 页、请示 4 页、管理办法 3 页、通知 2 页、企业报告 2 页）
   单份 0.48–0.62 s，峰值 RSS 约 55 MB；5 份连续 3 轮总耗时 2.80 / 2.49 / 2.50 s。
   每次 check 起 4 个 node 进程（入口 + 三道机检）。
10. **字体**：本机只有 Noto CJK，没有方正小标宋、仿宋、黑体、楷体。三道机检**不读字体**
    （`checks/*.js` 无任何字体规则），只看 XML 文本与版心参数，所以缺字体不影响机检结论。
    反过来说，`check` 也**不验字体**：ok_03 全文是 Microsoft YaHei，没有任何字体命中。
    字体只能靠可选的 `tools/check-pdf.py`（要先导出 PDF，需要 PyMuPDF），本次未验。

### 安装与离线包

- `npm install` 约 1.8 s，`node_modules` 11 MB；`npm test` 通过（197 项 ✓，约 51 s）。
- npm 10 的 `npm install` 会往 `package-lock.json` 补 `bin` 段、弄脏工作区，
  进而导致 `pack-offline.js` 拒绝打包；改用 `npm ci` 无此问题。
- `node tools/pack-offline.js --out /tmp` → `gongwen-kit-v0.4.4-offline.tgz`
  **2,114,109 字节（2.0 MiB）**，sha256 `3363758f…ac539911d`，解压 11 MB／530 个条目；
  按 `backend/third_party/README.md` 的步骤解压后 `where` 与 `check` 可用。

## `--json` 真实输出样例

样本均为占位内容（「示例单位办公室」、×××），无需另行脱敏。ok_03：

```json
{
  "file": "ok_03_markdown_to_docx.docx",
  "status": "hit",
  "blocking": 2,
  "checks": [
    {
      "check": "体例",
      "file": "ok_03_markdown_to_docx.docx",
      "hits": [
        { "rule": "公文版式", "detail": "版心 top、bottom、left、right 不合 GB/T 9704 8.1（上 37 下 35 左 28 右 26 mm）", "blocking": true, "anchors": [] },
        { "rule": "公文版式", "detail": "docGrid linePitch 不是 579：每页 22 行的行距被改过（GB/T 9704 8.1）", "blocking": true, "anchors": [] }
      ]
    },
    { "check": "数字自洽", "file": "ok_03_markdown_to_docx.docx", "hits": [] },
    { "check": "文风", "file": "ok_03_markdown_to_docx.docx", "hits": [] }
  ],
  "toolVersion": "0.4.4",
  "generatedAt": "2026-10-25T20:47:37.673Z",
  "sha256": "dd1563e53ae5421149e6417cddad969031936af79b76d74e52673eafcad2dec4"
}
```

带定位片段的命中（probe_01b，`数字自洽` 一节）：

```json
{ "rule": "计数与列举", "detail": "「以下五项」其后列了 3 个下一级标题", "blocking": true, "anchors": ["以下五项"] }
```

工具故障（非 zip 文件，退出码 2）：

```json
{ "file": "corrupt.docx", "status": "fault", "blocking": 0, "message": "check-doc.js 没能跑起来：退出码 2", "checks": [], "toolVersion": "0.4.4", "generatedAt": "…", "sha256": "…" }
```

## 前端字段映射分析（ReviewIssue，未实现，仅供决策）

| 字段 | 来源 | 能否填 | 说明 |
|---|---|---|---|
| `id` | 适配器合成（检查名 + 序号） | 合成 | 工具无规则编号，`rule` 可重复 |
| `severity` | 每条命中的 `blocking` | 部分 | `true→critical`、`false→hint`，`warning` 无来源；须写成常量映射表，不能按规则名 |
| `source` | 常量 `"rule"` | 能 | |
| `title` | `rule` | 能 | 中文规则名 |
| `description` | `detail` | 能 | 文案可读 |
| `locationLabel` | `anchors` 文本片段 | 部分 | 版式类为空；文风类无该字段 |
| `anchor` | — | **不能** | 工具不给段落序号，更没有 segment/block id；片段反查只能到「可能的段落」，片段重复时不唯一。任务书预设的 `anchor_precision: "paragraph"` 实际达不到，最多是 `"text_snippet"` |
| `section` | — | 不能 | 工具不输出所属章节 |
| `suggestion` | — | **留空** | 只有文字说明（如「筹画 → 筹划」写在 detail 里），没有 segmentId／replacement，不得伪造对象 |
| `requiredField` | — | **留空** | 工具没有任何要素缺失规则，issuer／recipient／undertaker 都对不上（与 bad_03 漏检同因） |

## 未验证项

- Windows 版 Word、WPS 打开 `fix` 产物的渲染与修订显示（上游自述只在 Mac 版 Word 验收）
- 真实公文（本次全部是自造或上游样张）；扫描件转 docx、WPS 另存的 docx
- 长文档（> 5 页，如 50 页以上）的耗时与内存
- RK3588（arm64）板端与 Windows 内网机上的离线包解压与运行
- `tools/check-pdf.py` 字体检查（需 PDF 导出与 PyMuPDF）
- 并发调用（每次 4 个 node 进程，单 uvicorn worker 下的排队行为）
- 上游 issue／后续版本是否会补要素缺失类规则

## 部署说明（仅供将来复评，当前不接入）

- Node >= 18；clone 固定提交后 `npm ci`，或用离线包解压，见 `backend/third_party/README.md`。
- 不用 Docker，不改 `backend/requirements.txt`。
- 若将来接入，再在 `config.yaml` 增加 `gongwen.kit_path` 等配置项；本次**未改** config。

## 建议

1. 要素完整性与结构类规则（发文机关标志、发文字号、主送、成文日期格式、版记、
   层次序号连续、「共 N 项」计数）由我方自写，直接作用在前端的文档模型
   （`DocBlock` / `DocSegment` 自带 id）上。这样 `anchor`、`segmentId`、`requiredField`
   都能如实填，正好补上 gongwen-kit 拿不到的字段。规则都是确定性的，规模不大。
2. gongwen-kit 可作为第二层，只用于它擅长的写法规范（发文字号写法、日期虚位、
   数字与单位、异形词、版心），待第 1 条落地后再评估，届时须在文案里写明它的定位精度只到文本片段。
3. 独立于本任务：后端 `markdown_to_docx` 若要用于出公文，版式需按 GB/T 9704 调整。
