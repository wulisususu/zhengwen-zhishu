# gongwen-kit 公文机检接入：S1 验证报告与复测

- 日期：2026-10-25　分支：`feat/gongwen-check`（自 main `aeee82b`）
- 对象：gongwen-kit 0.4.4（`b67ced1`，MIT），`node bin/gongwen.js check`
- 环境：Linux x86_64，Intel Xeon E5-2690 v4（2 核），Node v22.23.4，npm 10.9.9
- 复现：`python tests/spike/gongwen_s1_bench.py`；`pytest tests/test_gongwen_kit_s1.py`
- **后续（2026-10-25）**：按复测结论接入。gongwen-kit 负责通知生成、它已支持的格式机检和外来 Word 的辅助修复；要素、序号、数量、政策引用和审核门槛由 政文智枢 自研规则负责。接口与字段见 `docs/gongwen-api.md`。

## S1 结论：NO-GO（停在 S1，未做 S2；复测结论见下一节）

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

## 复测（2026-10-25）：上游声称能力、fix、生成对比

S1 只测了「缺要素／跳号」这类工具本就不查的错，结论偏向一侧。复测针对它**公开声称**的能力。
S1 的 no-go 只针对「作为审校主机检」这一用途，复测后结论见本节末。

- 复现：`python tests/spike/gongwen_s1_bench.py --dir tests/fixtures/gongwen/claimed`；
  `python tests/fixtures/gongwen/make_innet_samples.py`；`pytest tests/test_gongwen_kit_s1.py`（33 passed，5 xfailed）
- 渲染：本机没有 Word／WPS。改用 LibreOffice 26.2.6（官方 deb 解包到临时目录，未安装进系统）导出 PDF，
  再用 PyMuPDF 量。本机没有仿宋／黑体／楷体／方正小标宋，渲染时被替换成 Noto CJK，
  所以**字体只能按 DOCX 里声明的字体判断，渲染图只看版面**。

### 复测 1：声称支持的写法类错误——20/20 报出，19/20 拦稿

10 类 × 2 种写法，每份在 S1 基线上只埋一处（`tests/fixtures/gongwen/claimed/`）。

| 类 | 写法 a | 写法 b | 规则 | 结果 |
|---|---|---|---|---|
| 发文字号括号 | 版头 `示办发【2026】8号` | 正文引用 `示办发[2026]8号` | 发文字号 | 2/2 拦稿 |
| 顺序号「第」／虚位 | `〔2026〕第8号` | `〔2026〕008号` | 发文字号 | 2/2 拦稿 |
| 月日虚位 | 落款 `2026年10月06日` | 正文 `2026年09月30日` | 月日编虚位 | 2/2 拦稿 |
| 中文数字日期 | 落款 `二〇二六年十月二十六日` | 正文 `二〇二六年十月三十日` | 中文数字日期 | 2/2 拦稿 |
| 中文里的半角标点 | `通知如下:` | `办文质量,` | 中文里的半角标点 | 2/2 拦稿 |
| 半角括号 | `文书科(208室)` | `各部门(单位)` | 半角括号（另报一次半角标点） | 2/2 拦稿 |
| 异形词 | 筹画 | 耽心 | 异形词 | 2/2 拦稿 |
| 表格合计错 | 工具自带表格，合计 26≠25 | 同表去掉 `tblHeader` | 合计不符 | a 拦稿；**b 只提示** |
| 全角数字 | `１ 至 ２` | `２０２６年` | 全角数字 | 2/2 拦稿 |
| 1.1 式层次 | `1.1 讲解…` | `3.1 名单报送` | 公文层次序数 | 2/2 拦稿 |

20 份单份 0.46–0.56 s。唯一的例外对我们最要紧：表格首行没有 `tblHeader` 时，合计错只是**提示**，
报告 `status=pass`、退出码 0。python-docx 出的表格（我们两条链路都是）都没有 `tblHeader`，
所以 政文智枢 产物里的合计错，按退出码看会被放行，必须读 `hits` 才能看到。
半角括号会被「半角括号」「中文里的半角标点」两条规则各报一次，接入时需要去重。

### 复测 2：fix 处理 政文智枢 产物——纸张版心成功，标题、层次、列表、表格、落款不达标

样本是 政文智枢 两条真实链路的产物（同一份通知，含列表、名额表、加粗日期）：
`markdown_to_docx`（主链路）与 `document_agent._render_docx`（content_json 链路）。
`fix` 都只输出 `-修订.docx`，原件 md5 不变，修后 `check` 均为 `pass`。逐项对照（DOCX XML + LibreOffice 渲染）：

| 项 | 修前（两条链路） | 修后 | 判定 |
|---|---|---|---|
| 纸张 | US Letter 215.9×279.4 mm | A4 210×297 mm | ✓ |
| 版心 | 上下 25.4、左右 31.75 mm | `pgMar` 37/35/28/26 mm；渲染文字区左 28.0、右 26.0–26.2 mm | ✓ |
| 行字网格 | `linePitch 360`，无字网格 | `linePitch 579`、linesAndChars；首段 28 字回行，与工具自出稿一致 | ✓（XML） |
| 正文字体 | 主链路 Microsoft YaHei 11 pt；content_json 链路未声明中文字体 | Normal 改为仿宋三号 | ✓ |
| 页码 | 无 | 「— 1 —」单页居右、双页居左 | ✓ |
| **标题** | Heading1 左对齐 | **未识别**（报告：「前几段里没找到居中的标题段，未改」）；Heading1 被当作一级层次标题改成黑体三号、不居中 | ✗ |
| **层次标题** | 一、＝Heading2（markdown `##`） | 一、被改成**楷体**（二级样式），应为黑体 | ✗ |
| **列表段** | ListNumber 样式，微软雅黑 11 pt | **未改**，仍是微软雅黑 11 pt | ✗ |
| **表格** | 网格表、蓝色表头底纹 | 主链路表内仍是微软雅黑 11 pt；content_json 链路表格继承仿宋三号，行高变大，「合计」一行被挤到第 3 页单独成页 | ✗ |
| **落款** | 普通段落 | 未调整（不右空四字，与日期不成对） | ✗ |
| **版头／版记** | 无 | 不会补（fix 不新增内容，按设计如此） | ✗ |
| 页数 | 2 页／1 页 | 3 页／3 页 | — |

**修后 `check` 报 `pass`，但上表 6 项仍不合格。** check 不查标题、层次字体、列表字体、表格版式、落款、版头、版记，
所以「修后通过」不能当成「已合公文版式」。

**标题与层次两项是约定不符，不是能力缺失。** 在临时副本里把标题段改成居中的 `Title`、把 一、 改成 Heading1
（即我方 markdown 的 `#`/`##` 各上移一级）后再 fix：标题改为方正小标宋二号居中，一、改为黑体。
列表、表格、落款、版头、版记五项不受此影响，仍是 fix 的局限。

图：`docs/spike/gongwen-kit-retest/markdown_path_vs_kit.png`（主链路修前／修后／工具出稿）、
`render_docx_path.png`（content_json 链路修前／修后）。LibreOffice 渲染、字体被替换；
CJK 行在替换字体下会占两个网格行（工具自出稿同样如此），所以**不能用这些图判断每页 22 行**，
上游 `docs/版式.md` 记录的 22 行是在 Word 里量的。

### 复测 3：同内容通知，gongwen-kit 生成 vs 政文智枢 python-docx

`innet/kit_notice.docx`（`make_kit_notice.js`，按上游 `templates/notice.js` 的构件写，正文与 政文智枢 样本逐字相同）
对比 `innet_01`／`innet_02`：

| 项 | gongwen-kit | 政文智枢（python-docx） |
|---|---|---|
| 纸张／版心 | A4，37/35/28/26 mm，22 行×28 字网格 | US Letter，Word 默认页边距，无网格 |
| 版头 | 红色发文机关标志 + 发文字号 + 红色分隔线 | 无（两条链路都没有这些字段的输入） |
| 标题 | 方正小标宋二号，居中，按词意分两行 | 微软雅黑 18 pt 加粗蓝色左对齐／默认 Heading 1 |
| 主送 | 顶格，仿宋三号 | 普通段落 |
| 层次 | 一、黑体（自动编号） | 微软雅黑 15 pt 蓝色 Heading 2 |
| 正文 | 仿宋三号，首行缩进 2 字 | 微软雅黑 11 pt／默认字体 |
| 表格 | 三线表，表题在上（GB/T 1.1），表头黑体 | 网格表，蓝色表头底纹／content_json 链路表格排在落款之后 |
| 落款 | 右空四字，日期与署名居中对齐 | 左对齐普通段落 |
| 版记 | 抄送、印发机关与日期，分隔线，贴版心底 | 无 |
| 页码 | 「— 1 —」单右双左 | 无 |
| `check` | pass | hit：公文版式 ×2 |
| 耗时 | 0.91–0.98 s（含出稿后自动跑三道机检），约 85 MB | 两份合计 0.36–0.39 s，约 43 MB |

代价：gongwen-kit 出稿要先把内容组织成它的构件（版头、标题、主送、h1/h2、表格、落款、版记）
再交给 Node 跑；我们现有的 markdown 与 content_json 都不带版头、发文字号、版记等字段，接入要补一层映射。
字体（尤其方正小标宋）仍须目标机器自备。

### 复测结论

| 能力 | 结论 |
|---|---|
| 写法类机检（声称支持的规则） | **可用**：20/20 报出。注意手工表格合计错只提示；半角括号重复报 |
| 要素缺失／结构类机检 | **不具备**（S1：0/5），须我方自写 |
| fix 修 政文智枢 产物 | **部分可用**：纸张、版心、网格、正文字体、页码可靠；标题和层次需先对齐约定；列表、表格、落款、版头、版记修不了；修后 `pass` 不代表合规 |
| 按标准构件生成 | **明显优于**现有 python-docx 输出，代价是 Node 运行时与一层内容到构件的映射 |

所以不建议整体弃用。建议用作**公文生成 + 写法机检**模块；fix 不作为我方产物的主修复手段
（与其生成后再修，不如直接用它的构件生成）。

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

- Windows 版 Word、WPS 打开 `fix` 产物的渲染与修订显示（上游自述只在 Mac 版 Word 验收）。复测只用了 LibreOffice，且字体被替换；`tests/fixtures/gongwen/innet/` 里的修前、修后与 kit_notice 可直接拿到 Word／WPS 里核对
- 22 行×28 字在 Word／WPS 里的实际行数（LibreOffice 替换字体下行高翻倍，无法据此判断）
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
2. 保留 gongwen-kit 作写法类机检（复测 1：20/20），作为第二层。接入时须：只认 `--json`；
   读全部 `hits`，不只看 status（手工表格合计错只提示）；按规则对去重；文案写明定位只到文本片段。
3. 公文出稿改用 gongwen-kit 构件生成（复测 3），不走「python-docx 出稿 → fix」。
   需要先定一份「通知」的结构化字段（版头、发文字号、主送、层次、表格、落款、版记），
   与前端 `OfficialDocument` 对齐后再做映射。
4. fix 只作为外来稿的版式整理工具，且修后必须人工看标题、层次、列表、表格、落款；
   不能用修后 `check` 通过作为合规依据。
5. 在 Windows 版 Word 与 WPS 上打开 `tests/fixtures/gongwen/innet/` 的样本，确认复测 2、3 的结论后再定稿。
6. 独立于本任务：后端 `markdown_to_docx` 若继续用于出公文，标题应居中、层次应上移一级，
   否则任何下游版式工具都会把标题和层次认错。
