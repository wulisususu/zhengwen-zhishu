"""Qwen2.5-3B 文档生成管线 — 已验证配置.

模型说明:
  - 路由: Qwen3-0.6B-Q4_K_M.gguf  @ llama-server :8002  (c4096)
  - 生成: Qwen2.5-3B-Instruct @ RKLLM :8093 (Qwen2.5-3B-Instruct)

测试通过: 2026-06-16  weekly_report 端到端完成
"""

from __future__ import annotations

# ══════════════════════════════════════════════════════════════════════
# 模型端点
# ══════════════════════════════════════════════════════════════════════

ROUTER_URL = "http://127.0.0.1:8002/v1/chat/completions"
ROUTER_MODEL = "Qwen3-0.6B-Q4_K_M.gguf"
ROUTER_MAX_TOKENS = 128
ROUTER_TEMPERATURE = 0.1
ROUTER_TIMEOUT = 15

GEN_URL = "http://127.0.0.1:8093/v1/chat/completions"
GEN_MODEL = "Qwen2.5-3B-Instruct"
MINICPM_MAX_TOKENS = 1024
MINICPM_TEMPERATURE = 0.1          # 0.1 关键：降低随机性防格式错误
MINICPM_TIMEOUT = 120
MINICPM_STOP = ["\n\n\n\n", "```", "<think>"]
MINICPM_MAX_RETRIES = 2            # 总共最多 3 次尝试

# ══════════════════════════════════════════════════════════════════════
# Prompt — Qwen3-0.6B 路由分类
# ══════════════════════════════════════════════════════════════════════

ROUTER_SYSTEM_PROMPT = """你是文档类型路由器。分析用户输入,输出JSON分类。
类型: weekly_report(周报) resume(简历) checklist(清单) simple_report(简单报告) complex_report(复杂报告)
引擎: docxtpl(模板型) python-docx(动态型)
规则: 周报/简历/清单→docxtpl, 复杂/分析/方案/调研→python-docx, 其他→simple_report/docxtpl
只输出JSON: {"doc_type":"","engine":"","template_id":""}"""

# ══════════════════════════════════════════════════════════════════════
# Prompt — MiniCPM-V-4.6 内容生成 (few-shot 示例是关键)
# ══════════════════════════════════════════════════════════════════════

CONTENT_SYSTEM_PROMPT = (
    "你是JSON生成器。根据用户要求输出一个合法JSON对象。\n"
    "示例：{\"title\":\"周报\",\"sections\":[{\"heading\":\"工作\",\"content\":\"完成开发\"},{\"heading\":\"问题\",\"content\":\"修复bug\"}],\"summary\":\"进展顺利\"}\n"
    "只输出JSON，不要解释。"
)

# 用户消息模板 (含文档类型提示)
USER_MESSAGE_TEMPLATE = "文档类型：{doc_type}\n要求：{user_input}"
USER_MESSAGE_WITH_ATTACHMENT = "文档类型：{doc_type}\n要求：{user_input}\n参考资料：{attachment_context}"

# ══════════════════════════════════════════════════════════════════════
# 文档类型 → 模板 / 引擎 映射
# ══════════════════════════════════════════════════════════════════════

DOC_TYPE_TEMPLATE = {
    "weekly_report":   "weekly_v1",
    "resume":          "resume_v1",
    "checklist":       "checklist_v1",
    "simple_report":   "simple_v1",
    "complex_report":  "complex_v1",
}

DOC_TYPE_ENGINE = {
    "weekly_report":   "docxtpl",
    "resume":          "docxtpl",
    "checklist":       "docxtpl",
    "simple_report":   "docxtpl",
    "complex_report":  "python-docx",
}

VALID_DOC_TYPES = {"weekly_report", "resume", "checklist", "simple_report", "complex_report"}

# ══════════════════════════════════════════════════════════════════════
# 容错：MiniCPM 输出字段别名映射
# ══════════════════════════════════════════════════════════════════════
# MiniCPM 小模型可能输出 content/document_type/requirements 等变体字段
# _normalize_content() 负责将这些映射到标准 {title, sections, summary}

SECTION_ALIASES = ["sections", "content", "items", "points", "details"]
TITLE_ALIASES = ["title", "document_type"]
SUMMARY_ALIASES = ["summary", "requirements"]

# ══════════════════════════════════════════════════════════════════════
# 输出目录
# ══════════════════════════════════════════════════════════════════════

OUTPUT_DIR = "/home/youyeetoo/backend/data/generated_docs"
TEMPLATE_DIR = "/home/youyeetoo/backend/app/templates/docx"
