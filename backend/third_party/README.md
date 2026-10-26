# third_party

## gongwen-kit（中文公文机检，Node）

| 项 | 值 |
|---|---|
| 上游 | https://github.com/imhuhe/gongwen-kit |
| 版本 | 0.4.4（tag `v0.4.4`，提交 `b67ced12425b9988747282af570e82f0d726ac8f`） |
| 许可 | MIT |
| 运行要求 | Node >= 18（验证机 v22.23.4，npm 10.9.9） |
| 生产依赖 | docx、jszip、sax（纯 JavaScript，无安装脚本、无模型下载） |
| 离线包 | `gongwen-kit-v0.4.4-offline.tgz`，**2,114,109 字节（2.0 MiB）**，解压后 11 MB，530 个条目 |
| 状态 | **S1 未达标（no-go），未接入后端**。见 `backend/docs/spike/gongwen-kit.md` |

目录 `gongwen-kit/` 已在 `.gitignore` 里，不进本仓库；需要时按下面任一方式放到这里。
它不是 Python 依赖，不要写进 `backend/requirements.txt`。

上游 `package.json` 是 `"private": true`，**不能 `npm install gongwen-kit`**。

### 方式一：clone（能上网的机器）

```bash
cd backend/third_party
git clone https://github.com/imhuhe/gongwen-kit.git
cd gongwen-kit
git checkout b67ced12425b9988747282af570e82f0d726ac8f
npm ci                     # 用 npm ci：npm 10 的 npm install 会给 package-lock.json 补一段 bin，弄脏工作区
npm test                   # 可选，约 50 s，七份样张 + 全部负对照
node bin/gongwen.js where  # 打印目录即可用
```

### 方式二：离线包（内网机器）

在能上网的机器上，于干净的 clone 里打包（工作区有改动时脚本会拒绝）：

```bash
node tools/pack-offline.js --out /tmp
# → /tmp/gongwen-kit-v0.4.4-offline.tgz
```

拷到目标机器：

```bash
tar -xzf gongwen-kit-v0.4.4-offline.tgz -C backend/third_party/
mv backend/third_party/gongwen-kit-v0.4.4 backend/third_party/gongwen-kit
node backend/third_party/gongwen-kit/bin/gongwen.js where
```

离线包不含测试、样张和宣传图，包内 `npm test` 不可用。已在本机（Linux x86_64）
解压后跑通 `check`；Windows、RK3588（arm64）上的解压与运行未实测。

### 验证

```bash
cd backend
python tests/spike/gongwen_s1_bench.py        # 逐份 check --json：退出码、命中、耗时、md5
pytest tests/test_gongwen_kit_s1.py           # 没装 node 或本目录时自动 skip
```
