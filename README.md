# INnet Agent AI Box

AI 全能盒子项目，包含 Web 前端、后端服务与 PPT 生成/编辑能力。

## 项目结构

```text
frontend/  Web 前端
backend/   API 服务与 PPT 后端
```

## 本地开发

前端：

```bash
cd frontend
npm ci
npm run dev
```

后端：

```bash
cd backend
python -m venv .venv
# 激活虚拟环境后安装依赖
pip install -r requirements.txt
```

请基于 `frontend/.env.example` 与 `backend/.env.example` 配置本地环境变量。

## 版本库范围

本仓库仅保存运行所需源码、配置示例和 PPT 模板资源；不包含模型文件、历史 PPT、数据库、备份、日志、测试目录、依赖目录或运行状态文件。

## 本地模型与部署目录

模型权重刻意不提交到 Git。克隆仓库后，以下文件缺失属于正常部署前置条件，并不表示源码缺失。当前代码有部分绝对路径依赖；若部署用户或目录不同，应同步调整对应代码/启动脚本，或通过软链接保持相同路径。

|能力|模型与格式|代码当前读取位置|部署时应准备的位置|状态与说明|
|---|---|---|---|---|
|主对话与文档生成|Qwen2.5-3B-Instruct（`.rkllm`）|`backend/app/services/llm_server.py`、`backend/app/docs_pipeline/infer_worker.py`|`/home/youyeetoo/rkllm_model_zoo/Qwen2.5-3B-Instruct RKLLM/Qwen2.5-3B-Instruct.rkllm`|主本地 LLM；生产服务器存在，但 Git 不包含。|
|轻量备用推理|Qwen3-0.6B Q4_K_M（`.gguf`）|`backend/app/services/llm_client.py`|`/home/youyeetoo/rkllm_model_zoo/Qwen3-0.6B/Qwen3-0.6B-Q4_K_M.gguf`|由本地 `llama-server` 启动的备用链路；生产服务器存在。|
|视觉理解 / OCR|MiniCPM-V-2.6：`vision_transformer.rknn` + `qwen.rkllm`|`backend/app/services/minicpm_vision_service.py`、`minicpm_ocr_runner.py`|运行后端时的 `backend/model/vision_transformer.rknn` 与 `backend/model/qwen.rkllm`|代码使用相对路径。生产模型源位于 `/home/youyeetoo/rkllm_model_zoo/MiniCPM-V-2_6-rkllm/model/`；部署时需复制或软链接到 `backend/model/`。|
|语音合成|Piper `zh_CN-huayan-medium.onnx` 与同名 `.onnx.json`|`backend/app/services/tts_service.py`（可由 `PIPER_MODEL`、`PIPER_CONFIG` 覆盖）|默认：`/home/youyeetoo/piper_tts/models/`|可选 TTS 功能。当前生产服务器的默认路径下未发现该模型，启用语音合成前必须补齐文件或设置环境变量。|
|语音识别|Paraformer ONNX 目录（含 `model.onnx`、`decoder_fixed.onnx`、`am.mvn`、`tokens.json`）|`backend/app/services/asr_service.py`|默认：`/home/youyeetoo/rkllm_model_zoo/mqw-tools/paraformer_onnx/`|可选 ASR 功能。当前生产服务器默认目录未发现该模型；启用语音识别前需补齐。|
|旧版实验链路|DeepSeek-R1-Distill-Qwen-1.5B（`.rkllm`）|`backend/start_llm.sh`|`/home/youyeetoo/rkllm_model_zoo/DeepSeek-R1-Distill-Qwen-1.5B_W8A8_RK3588.rkllm`|历史/实验启动脚本引用，主 `llm_service.py` 已标注为禁用，不应当作主链路依赖。|

### 模型部署检查

1. 不要把上述权重、推理缓存或模型目录提交到 Git。
2. 主对话和 PPT/文档相关本地推理至少需要 Qwen2.5-3B RKLLM 模型。
3. 需要图片理解或 OCR 时，再补齐 MiniCPM-V 两个文件，并保证其位于运行工作目录下的 `backend/model/`。
4. 需要语音功能时，按上表补齐 Piper 或 Paraformer；否则相关端点不能工作，但不影响普通对话、PPT 编辑与外部模型配置。
5. 前端也支持通过“外部模型”设置调用远程 API；该模式依赖 `.env` 中的服务配置，不依赖本地权重。
