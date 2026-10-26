# RK3588 / ARM64 人工验证清单（OpenDataLoader PDF）

**以下内容都没有在 ARM64 上执行过**，需要有人在板子上逐项运行，并记录结果。x86 上的基线数据见 [opendataloader-pdf.md](opendataloader-pdf.md) 第 4 节。

## 0. 前置信息记录

```bash
uname -m                       # 期望 aarch64
cat /proc/cpuinfo | grep -m1 "model name\|Hardware"
free -h                        # 总内存与当前可用内存
df -h /home                    # 剩余空间，至少需要约 100 MB
# 另外记录：当前是否有 MiniCPM（8003）、Qwen（8002）等服务在运行（会影响内存余量）
ss -ltnp | grep -E ':8002|:8003|:8088'
```

## 1. Java 版本（必须是 11 或更高）

```bash
java -version 2>&1 | head -1
# 没有 Java 或版本低于 11 时（Ubuntu / Debian 系）：
sudo apt-get install -y openjdk-17-jre-headless   # 约 200 MB；只装 headless 版即可
```

记录：版本号、是否为 aarch64 构建（`java -XshowSettings:properties -version 2>&1 | grep os.arch`）。

## 2. 获取 OpenDataLoader（与 x86 使用同一个版本）

来源：PyPI 的 `opendataloader-pdf==2.5.15`。wheel 是 `py3-none-any`，22.7 MB，不区分 CPU 架构；里面自带一个约 24 MB 的 CLI jar。

```bash
cd /home/youyeetoo/InNet_box/backend
python3 -m venv .venv-pdf
.venv-pdf/bin/pip install -r requirements-pdf.txt       # 不要装 [hybrid]
JAR=$(.venv-pdf/bin/python -c "import opendataloader_pdf,os;print(os.path.join(os.path.dirname(opendataloader_pdf.__file__),'jar','opendataloader-pdf-cli.jar'))")
ls -l "$JAR"                                             # 约 24,205,939 字节
sha256sum "$JAR"                                         # 和 x86 上的值比对是否一致
```

板子不能访问 PyPI 时：在其他机器上执行 `pip download opendataloader-pdf==2.5.15 --no-deps`，把 wheel 拷到板子上，再运行 `pip install <wheel>`。

## 3. 单文件冒烟测试（先用 A 跑通）

```bash
mkdir -p /tmp/odl-out
java -Djava.awt.headless=true -Duser.language=en -jar "$JAR" A.pdf \
  --output-dir /tmp/odl-out --format json,markdown --image-output off --quiet
echo "exit=$?"; ls -l /tmp/odl-out; head -c 600 /tmp/odl-out/A.json
```

检查：退出码为 0；JSON 中 `number of pages` 为 12；markdown 正文是中文且没有乱码。

## 4. 耗时与内存（与 x86 使用同样的方法）

对同一份文件连续跑 3 次，记录 `Elapsed (wall clock)` 和 `Maximum resident set size`：

```bash
for i in 1 2 3; do
  /usr/bin/time -v java -Djava.awt.headless=true -Duser.language=en -jar "$JAR" D.pdf \
    --output-dir /tmp/odl-out --format json,markdown --image-output off --quiet \
    2>&1 | grep -E "Elapsed|Maximum resident"
done
```

需要测的用例：
- 官方长篇 D（28 页）；
- 批量 A～D 一次调用：把四个文件依次放在 `"$JAR"` 后面；
- 50 页文件：可以用 `tests/fixtures/pdf/make_samples.py --perf` 生成的 `text_50p.pdf`，也可以用另一份真实的长文件；
- 在 MiniCPM / RKLLM 正常运行的同时，再跑一次 D，观察内存是否吃紧、有没有被 OOM killer 杀掉（`dmesg | tail`）。

也可以直接跑基准脚本（输出 JSON，和 x86 的报告可以逐行对比）：

```bash
.venv-pdf/bin/python tests/spike/odl_benchmark.py --runs 3 --json /tmp/bench-arm.json \
  D=/path/D.pdf batch=/path/A.pdf,/path/B.pdf,/path/C.pdf,/path/D.pdf
# 如需限制堆内存，加 --xmx 512m 再跑一次
```

判定门槛与 x86 相同：单页平均 ≤ 3 秒，峰值内存 ≤ 1.5 GB，表格与页码结构可用。另外记下 JVM 启动时间，即单页文件的总耗时。

## 5. 功能核对

```bash
ODL_REAL=1 ODL_JAR="$JAR" ODL_REAL_SAMPLES=/path/to/policy-pdfs \
  <装有 pytest 和 fastapi 的 python> -m pytest tests/test_opendataloader_pdf_real.py -v
```

期望 10 / 10 通过；C（扫描件）报告无文本层是预期结果。

## 6. 失败时如何回退

- 默认链路本来就没有切换：不设置 `pdf_parser.engine`，或者 `engine` 不是 `opendataloader` 时，仍然走 `_extract_pdf()`（pdftotext + MiniCPM）。
- 板子上任何一项不达标（Java 装不上、耗时或内存超过门槛、出现乱码）时：
  1. 不要设置 `pdf_parser.engine`；
  2. 删除独立 venv：`rm -rf backend/.venv-pdf`；
  3. 不需要改动其他任何文件。`requirements.txt` 没有被修改过。
- 即使开启了适配器，单次失败（超时、内存溢出、损坏文件）时 `extract_pdf_with_engine` 也会自动回退到 `_extract_pdf()`，返回值与没开启时完全相同。

## 7. 需要回传的结果

请把以下内容整理成表格回传：
- `java -version` 输出；
- jar 的 sha256；
- 第 4 节每个用例的耗时（3 次）和最大常驻内存；
- 第 5 节的 pytest 输出；
- 同时运行 MiniCPM 时 D 的结果，以及 `free -h` 的前后对比。
