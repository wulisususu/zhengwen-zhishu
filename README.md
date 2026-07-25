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
