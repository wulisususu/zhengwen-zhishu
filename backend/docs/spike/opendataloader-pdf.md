# Spike：OpenDataLoader PDF 接入评估（只做适配器与验证，不接线）

- 分支：`spike/pdf-opendataloader`（从 `main@aeee82b` 拉出）
- 日期：2026-10-25
- 环境：x86_64 VPS，2 核 / 3.8 GB 内存，OpenJDK 17.0.20.1，Python 3.12.3
- **ARM64 / RK3588 未实测。** 板子上需要人工执行的步骤见 [rk3588-checklist.md](rk3588-checklist.md)。

## 1. 结论：x86 上 GO（限文字型 PDF）；扫描件不在本方案范围内

| 门槛 | 要求 | 实测（x86） | 是否达标 |
|---|---|---|---|
| 单页平均耗时 | ≤ 3 秒 | 文字型 0.07～0.24 秒/页；扫描件 C 为 0.49 秒/页（含 JVM 启动） | 达标 |
| 峰值内存（`/usr/bin/time -v`，JVM 进程） | ≤ 1.5 GB | 文字型 109～203 MB；含扫描件的批量为 741 MB（加 `-Xmx512m` 后 515 MB） | 达标 |
| 表格与页码结构 | 可用 | 页码一一对应；表格保留行、列、合并信息、表头标记和单元格坐标 | 达标 |

- **GO 的范围**：作为文字型 PDF 的**可选**解析器，配合显式开关和失败回退，在 x86 上可用。
- **扫描件**：纯本地模式没有 OCR。C 的 16 页全部提取到 0 字，这是预期行为，不算缺陷。扫描件仍然走现有的 MiniCPM / CPU OCR 链路。
- **不改变默认链路**，也不修改 `requirements.txt`。等板子实测通过后，再讨论是否正式接入。

## 2. 官方 API 依据（实际读取的包内源码）

- **包**：`opendataloader-pdf==2.5.15`
  - wheel 为 `py3-none-any`，22.7 MB，没有任何 Python 依赖；
  - 安装后 venv 共 39 MB；
  - 内置 jar：`opendataloader_pdf/jar/opendataloader-pdf-cli.jar`，24,205,939 字节；
  - jar 的 MANIFEST：`Java-Version: 11`，`Main-Class: org.opendataloader.pdf.cli.CLIMain`。
- **Python 接口**：`from opendataloader_pdf import convert, run, run_jar`（`run` 已标记弃用）。

```python
convert(input_path: str | list[str], output_dir: str | None = None, password=None,
        format: str | list[str] | None = None, quiet: bool = False, ..., keep_line_breaks=False,
        use_struct_tree=False, table_method=None, reading_order=None, image_output=None,
        pages=None, include_header_footer=False, hybrid=None, ..., threads=None, ...) -> None
```

- `convert()` 内部调用 `subprocess.run(["java", "-Djava.awt.headless=true", ..., "-jar", jar, *args])`。
  - 它**没有 timeout 参数**，并且会把 CLI 的 stdout 写到当前进程的 stdout。
  - 所以适配器**不调用 `convert()`**，而是用参数数组直接调用同一个内置 jar，并设置超时。传给 CLI 的参数与 `convert()` 生成的完全一致。
- 适配器使用的 CLI 参数：`<files...> --output-dir <dir> --format json,markdown --image-output off --threads 1`。
  - 不使用 `--hybrid`；
  - JVM 参数加上 `-Duser.language=en`，让日志前缀固定为 `INFO:` / `WARNING:`，便于按文件归属警告。

### 实际 JSON 输出结构（opendataloader-pdf 2.5.15）

顶层字段：

```json
{"file name": "...", "number of pages": 12, "author": "...", "title": "...",
 "creation date": "...", "modification date": "...", "kids": [ ... ]}
```

`kids` 中每个元素带 `type`、`id`、`page number`、`bounding box`（`[x0, y0, x1, y1]`，单位为 PDF 点，原点在左下角）。不同类型的附加字段：
- `heading`：`heading level`、`font`、`font size`、`content`
- `paragraph` / `caption`：`content`（`caption` 另有 `linked content id`）
- `list`：`numbering style`、`list items[]`。每个列表项**同时**带 `content` 和 `kids`。
- `table`：`number of rows`、`number of columns`、`rows[].cells[]`。每个单元格带 `row number`、`column number`、`row span`、`column span`、`is_header`、`kids[]`。
- `text block`：容器，内容在 `kids` 里，可能包着 `list`。
- `image`：只有 bbox。设置 `--image-output off` 时 `source` 为 null。

真实片段（A《艺术发展“十五五”规划》第 1 页）：

```json
{"type": "heading", "pdfua_tag": "H1", "id": 1, "level": "Doctitle", "page number": 1,
 "bounding box": [170.64, 708.134, 423.47, 733.685], "heading level": 1,
 "font": "FZXBSK--GBK1-0", "font size": 21.95, "content": "艺术发展“十五五”规划"}
```

A 第 2 页「专栏 1」被识别为 2 行 1 列的表格。经适配器映射后的单元格：

```json
{"row": 2, "col": 1, "row_span": 1, "col_span": 1, "is_header": false,
 "text": "到“十五五”期末，累计扶持具有导向性、代表性、示 范性的舞台艺术作品约 400 部（个）和美术作品约 200 件；",
 "bbox": [71.15, 85.6, 524.7, 142.26]}
```

对应的 markdown 输出：

```
|专栏 1 艺术发展主要指标|
|---|
|到“十五五”期末，累计扶持具有导向性、代表性、示 范性的舞台艺术作品约 400 部（个）和美术作品约 200 件；|
```

适配器返回的第 1 页 `text`（前 200 字）：

```
艺术发展“十五五”规划
为贯彻落实《中华人民共和国国民经济和社会发展第十 五个五年规划纲要》《文化和旅游发展“十五五”规划》等， 推动艺术事业高质量发展，编制本规划。
一、总体要求 坚持以习近平新时代中国特色社会主义思想为指导，深 入贯彻党的二十大……
```

## 3. 首次运行是否下载资源

- 安装时只下载了 wheel 本身（22.7 MB，来自 PyPI），没有任何依赖。
- 首次转换前后分别对 `~/.cache`、`~/.m2`、`~/.local/share` 做了快照：**没有新增任何文件**，也没有下载模型。`/tmp` 下只多了 JVM 的标准目录 `hsperfdata_root`。
- 在没有网络接口的网络命名空间（`unshare -n`）里复跑转换，结果相同，说明解析本身不需要网络。
- 本次没有安装 `[hybrid]` extra（docling + easyocr），也没有启用 hybrid。

## 4. 实测数据（x86 VPS，每个用例跑 3 次，测量对象是适配器实际执行的 JVM 命令）

| 用例 | 样本 | 页数 | 平均耗时（秒） | 最长耗时（秒） | 秒/页 | 峰值内存 | 适配器结果 |
|---|---|---|---|---|---|---|---|
| 10 页 | 合成 `text_10p.pdf` | 10 | 2.42 | 2.62 | 0.242 | 109 MB | 成功 |
| 50 页 | 合成 `text_50p.pdf` | 50 | 5.13 | 5.18 | 0.103 | 153 MB | 成功 |
| 官方 A（文字型 + 专栏） | gov.cn | 12 | 2.15 | 2.21 | 0.179 | 139 MB | 成功 |
| 官方 B（文字型 + 专栏） | gov.cn | 14 | 2.28 | 2.40 | 0.163 | 140 MB | 成功 |
| 官方 C（扫描件） | gov.cn | 16 | 7.83 | 8.51 | 0.490 | 638 MB | 无正文（预期） |
| **官方 D（长篇）** | gov.cn | 28 | 3.05 | 3.10 | 0.109 | 168 MB | 成功 |
| **批量 A～D，一次 JVM** | gov.cn | 70 | 9.59 | 10.18 | 0.137 | 741 MB | A/B/D 成功，C 无正文 |
| 批量 A+B+D（纯文字） | gov.cn | 54 | 3.77 | 4.02 | 0.070 | 203 MB | 全部成功 |
| 批量 A～D，`-Xmx512m` | gov.cn | 70 | 9.66 | 9.71 | 0.138 | 515 MB | 与不限堆时一致 |

说明：
- **没有 50 页的官方样本**：政策文件库的单份附件一般在 12～30 页。官方长文件以 D（28 页）为准；「50 页」一行用的是合成样本，单独标注。
- 每次调用都包含约 1～1.5 秒的 JVM 启动时间。批量调用可以把这部分摊薄：A+B+D 批量的单页耗时比单独跑 D 时更低。
- 内存峰值主要由扫描件里的大图片决定。限制堆内存（`-Xmx512m`）后峰值从 741 MB 降到 515 MB，没有出现内存溢出。

### 文本覆盖率（与 pypdf 5.1.0 逐页比较非空白字符数）

| 样本 | pypdf | 适配器 | 比例 |
|---|---|---|---|
| A | 5760 | 5721 | 99.3% |
| B | 9118 | 9099 | 99.8% |
| C | 0 | 0 | — |
| D | 14313 | 14210 | 99.3% |

各份文件都没有覆盖率低于 80% 的页。

开发过程中，B 的第 8 页一度丢失全部正文：`text block` 里面包着 `list`，列表项的 `kids` 没有被读取。已修复，并加了基于真实 B 输出的回归测试。

## 5. 测试（mock 与真实解析分开）

### mock 测试：`tests/test_opendataloader_pdf_adapter.py`，37 / 37 通过

不需要 Java 和 opendataloader，JVM 由 fake 代替；信封映射用的是保存下来的**真实** 2.5.15 JSON（`tests/fixtures/pdf/odl_json/`）。覆盖：
- 页码与正文的对应；bbox 保留；表格单元格的行、列、合并、表头；
- 表格几何不一致时给出警告；扫描页给出警告，并且不伪造正文；`text block` / 列表漏字的回归；
- 未安装（包括测试环境本身确实没装这个包的情况）、找不到 Java、Java 过旧；
- 空文件、非 PDF、文件不存在时，根本不调用 JVM；
- `output_dir` 路径穿越、指向允许范围外的绝对路径、符号链接逃逸，都会被拒绝；
- 参数数组、`shell=False`、超时传递、不使用 hybrid；文件名形似命令行参数或重名时安全暂存；
- 超时后报明确错误，成功或失败后都会清理临时目录；
- 批量只启动一个 JVM，结果保持输入顺序，部分失败不影响其他文件；警告按文件归属；
- **不阻塞事件循环**：`parse_pdf_async` 解析 1.5 秒期间，`/ping` 在 0.6 秒内返回。另有反例：在 async 端点里直接调用 `parse_pdf` 会让 ping 等满约 1 秒。
- **回归**：
  - 默认引擎是 legacy，适配器完全不会被调用；
  - 适配器失败（未安装）时，`extract_pdf_with_engine` 的返回值与直接调用 `_extract_pdf()` **完全相等**，子进程调用序列同为 `pdfinfo → pdftotext → pdfimages`；
  - 适配器内部抛异常时也会回退；
  - `_extract_pdf()` 的源码没有被修改。

### 真实解析测试：`tests/test_opendataloader_pdf_real.py`，需显式开启

```
ODL_REAL=1 ODL_JAR=<jar> ODL_REAL_SAMPLES=/srv/box/in/policy-pdfs pytest tests/test_opendataloader_pdf_real.py
```

本次结果 10 / 10 通过：
- 合成样本：文字型、表格型、扫描型、损坏文件；
- 官方样本：A / B / D 页码与正文对应、每页都有文字、每个块都有 bbox；A / B 的专栏表格结构；C 被如实标注为无文本层。

不设置 `ODL_REAL` 时，这 10 项全部跳过。

## 6. 调用方式

```python
from fastapi.concurrency import run_in_threadpool
from app.services.opendataloader_pdf_adapter import AdapterConfig, parse_pdf_async, parse_pdfs, parse_pdf

config = AdapterConfig(timeout_seconds=120, jvm_options=("-Xmx512m",))

# 在 async 代码里（单 uvicorn worker）：必须放进线程池，不能直接调 parse_pdf
envelope = await parse_pdf_async("/data/uploads/x.pdf", config=config)
# 等价写法：await run_in_threadpool(parse_pdf, path, None, config=config)

# 批量：只启动一个 JVM；结果顺序与输入一致，单个文件失败不影响其他文件
envelopes = await run_in_threadpool(parse_pdfs, [a, b, c], None, config=config)

if not envelope["success"]:
    ...  # 读 envelope["error"]（带错误码前缀）和 envelope["warnings"]，然后回退到现有链路
```

**将来在政务政策导入模块（`feat/policy-retrieval` 分支的 `/gov/policies/import`）中使用**：上传的文件是 PDF 时：
1. 在线程池里调用 `parse_pdf`；
2. 把每页每个块的 `text` 按 `pages[].blocks[]` 的顺序拼成正文，交给条款切分。条款可以记录 `page_number`，也可以用块的 `bbox` 生成 `source_anchor`；
3. 如果 `success=false`，按原有逻辑报 `UNSUPPORTED_FILE` / `EMPTY_CONTENT`，或者回退到 OCR 链路。

本 spike 没有接线，以上只是建议用法。

**显式开关**：`extract_pdf_with_engine(path, engine="opendataloader")`，或者在 `config.yaml` 里设置 `pdf_parser.engine: opendataloader`（本次没有改 config 示例）。未设置时返回值与 `_extract_pdf()` 完全相同。这个函数目前没有任何调用方。

## 7. 依赖

- Python：`opendataloader-pdf==2.5.15`，写在 `backend/requirements-pdf.txt`，**没有改 `requirements.txt`**。
- Java：JRE 11+（jar 的编译目标是 11），本机用的是 OpenJDK 17。
- 不下载模型。hybrid（docling + easyocr）没有安装，也没有启用。
- 磁盘：venv 39 MB；临时文件在每次调用结束后删除。

## 8. 已知问题与未验证项

- **ARM64 / RK3588 未实测**：包括 JRE 版本、实际耗时、内存，以及与 MiniCPM / RKLLM 同时运行时的内存竞争。
- **扫描件质量**：本地模式没有 OCR，C 的 16 页均为 0 字。hybrid 的 OCR 效果没有验证，本任务按要求不启用。
- **超长文件稳定性**：官方最长样本只有 28 页，只额外跑了一份合成的 50 页文件；100 页以上和上百 MB 的大文件没有测过。
- **并发**：适配器用信号量限制同一时刻最多 `max_concurrent=1` 个 JVM。多请求同时提交时的排队和超时表现只做了单元级验证。
- **CJK 换行空格**：原文换行处的中文之间会被插入空格（例如「第十 五个五年」「示 范性」）。适配器不改原文；后续做条款切分和引用匹配时需要规范化（例如去掉 CJK 字符之间的单个空格），或者评估 `--keep-line-breaks` 参数。
- **元数据不可信**：PDF 自带的 `title` 字段是乱的（A 为「外欧函〔2011〕225号」，C 为 Windows 本地路径），不能拿来当政策标题。
- **版面误判**：表格后面的落款曾被识别成表格的 `caption`；扫描件上的框线被识别成空表格。适配器已经忽略空表格并给出警告。
- 「专栏」在 A / B 中实际是带框的单列文字栏，并不是多列指标表。多列指标表的结构在合成样本上验证过（4×4，表头标记正确），但**没有在多列的官方表格上验证**。
- 背景图片会被解析器的内容安全过滤当作背景去掉（日志中的「Detected background」）。目前没有观察到对正文的影响。
- 历史遗留：`file_parse_service._merge_pdftotext_fallback()` 中提到 OpenDataLoader，但没有任何调用方。它可能是早期在板子上通过 `mqw-tools/pipeline/run.py` 接入时留下的。本次没有改动。
