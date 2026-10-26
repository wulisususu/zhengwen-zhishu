# gongwen-kit S1 验证语料

用于计算 gongwen-kit（0.4.4）`check` 的检出率与误报。结论与数据见 `backend/docs/spike/gongwen-kit.md`。

## 生成方法

- `make_samples.js`：先出一份**基线**通知（`baseline_control.docx`，实测零命中），
  每份必错样本只在基线上改**一处**。这样命中与否只取决于埋的那一个错，
  不会被版心等无关问题碰巧命中。层次序数一律手打（一、二、三），
  不用 gongwen-kit 的自动编号——自动编号不可能跳号，真实来稿也是手打。
  机关名用占位「示例单位办公室」，不用真实机关。
  重新生成：`node make_samples.js [gongwen-kit 目录]`（默认 `backend/third_party/gongwen-kit`）。
- `make_md_sample.py`：调用后端现有 `app.services.markdown_to_docx.markdown_to_docx`
  （未改动）出 `ok_03`。在 `backend/` 下运行，需要 python-docx。
- `ok_01`、`ok_02`：gongwen-kit 自带样张（`npm test` 生成的 `samples/word/公文通知.docx`、
  `公文请示.docx`，MIT），原样复制。

## 必错样本（每份只埋一个错）

| 文件 | 埋了什么错 | 与基线的唯一差别 |
|---|---|---|
| `bad_01_count_mismatch.docx` | 数字不一致：正文写「共 5 项任务」，其下只列（一）（二）（三）3 项 | 第 8 段「共 3 项任务」→「共 5 项任务」 |
| `bad_02_heading_gap.docx` | 层次序号跳号：一、二、四（缺三） | 第 14 段「三、有关要求」→「四、有关要求」 |
| `bad_03_no_letterhead.docx` | 缺发文机关标志与发文字号 | 删去版头（「示例单位办公室文件」「示办发〔2026〕8号」两段及红线） |
| `bad_04_date_iso.docx` | 成文日期格式错：`2026-10-26`（应为 2026年10月26日） | 落款日期一段 |
| `bad_05_no_banji.docx` | 版记缺失 | 删去版记（抄送、印发机关与印发日期） |

## 合规样本

| 文件 | 来源 |
|---|---|
| `ok_01_upstream_notice.docx` | gongwen-kit 样张：通知（完整版头与版记） |
| `ok_02_upstream_qingshi.docx` | gongwen-kit 样张：请示（签发人、附件页） |
| `ok_03_markdown_to_docx.docx` | 本项目 `markdown_to_docx` 出的同内容通知 |

## 对照与探针（不计入检出率 / 误报）

| 文件 | 用途 |
|---|---|
| `baseline_control.docx` | 必错样本的基线，应零命中，证明命中只来自埋的错 |
| `probe_01b_count_yixia.docx` | 与 bad_01 同一个计数错，但句式换成 check-num 能识别的「以下五项任务」 |

## 复测语料（2026-10-25）

### `claimed/`：上游声称支持的写法类错误

`make_claimed_samples.js` 生成，复用 `make_samples.js` 的基线，每份只埋一处。10 类错误 × 2 种写法，
逐份埋错位置与期望规则名见 `claimed/expected.json`（`tests/spike/gongwen_s1_bench.py --dir tests/fixtures/gongwen/claimed` 计分）。
`c08b` 与 `c08a` 是同一张合计错表，只是去掉了 `tblHeader`，模拟 python-docx／手工表格。

### `innet/`：InNet_box 两条 DOCX 链路的产物与对照

| 文件 | 来源 |
|---|---|
| `innet_01_markdown_to_docx.docx` | `markdown_to_docx`（markdown-first 主链路），`make_innet_samples.py` 生成 |
| `innet_02_render_docx.docx` | `document_agent._render_docx`（content_json 链路），用 ast 取原函数执行，不 import 整个模块 |
| `*-修订.docx`、`*.fix-report.txt` | 对上面两份跑 `gongwen fix` 的输出副本与报告（原件不变） |
| `kit_notice.docx` | `make_kit_notice.js`：gongwen-kit 标准构件出的同内容通知，用于与 python-docx 产物对比 |

## `notices/`：结构化通知（接口测试与样张用）

| 文件 | 内容 |
|---|---|
| `standard_notice.json` | 要素齐全的标准通知（含表格、附件、附注、政策依据、版记），两层审校都应通过，只留「政策有效性未核验」提示 |
| `defective_notice.json` | 按前端 Mock 文档改写的缺陷草稿：主送为空、承办为空、成文日期 `2025-10-25`、无版记、一二四跳号、共 4 项只列 2 项、`[2025]`、`05日`、半角逗号、引用未关联 |

