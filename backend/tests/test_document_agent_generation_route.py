import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.services.document_agent import (  # noqa: E402
    _ensure_report_completeness,
    classify_workflow,
    generate_content_schema,
    generate_agent_output_file,
    validate_task_plan,
)
from app.services.intent_policy import classify_document_intent  # noqa: E402


class DocumentAgentGenerationRouteTests(unittest.TestCase):
    def test_document_page_short_manual_request_is_generation(self):
        decision = classify_document_intent(
            "为一个AI聊天系统编写用户使用手册。要求包含登录、发起对话、导出记录。"
        )

        self.assertEqual("document_generation", decision.intent)
        self.assertTrue(decision.use_document_agent)

    def test_project_implementation_plan_generation_does_not_require_attachment(self):
        prompt = (
            "请生成一份正式项目实施方案。\n"
            "项目名称：智慧校园AI学习平台\n"
            "要求生成一个可直接交付给客户的Word文档内容，包含封面、目录、项目背景、建设目标、"
            "功能设计、技术架构、实施计划、人员安排、风险控制、培训方案、验收标准、运维保障、预算报价。"
        )

        with patch("app.services.document_agent._minicpm_service_ready", return_value=True):
            route = classify_workflow(
                prompt,
                attachments=[],
                attachment_context="",
                force_output_format="docx",
            )
        validation = validate_task_plan(route, attachment_context="", attachments=[])

        self.assertEqual("generate", route["primary_operation"])
        self.assertEqual("docx", route["output_spec"]["format"])
        self.assertEqual("success", validation["status"])
        self.assertNotIn("请先上传需要处理的附件", validation["message"])

    def test_word_document_content_mentions_ppt_but_output_remains_docx(self):
        prompt = (
            "生成会议纪要。\n\n"
            "会议主题：AI办公平台建设讨论会\n\n"
            "时间：2026年5月30日\n\n"
            "参会人员：张总、李经理、王工、赵工\n\n"
            "会议内容：\n"
            "1. 建设智能写作平台\n"
            "2. 接入本地大模型\n"
            "3. 支持Word、PPT自动生成\n"
            "4. 支持语音输入\n\n"
            "要求：形成标准会议纪要。"
        )

        with patch("app.services.document_agent._minicpm_service_ready", return_value=True):
            route = classify_workflow(
                prompt,
                attachments=[],
                attachment_context="",
                force_output_format="docx",
            )

        self.assertEqual("generate", route["primary_operation"])
        self.assertEqual("docx", route["output_spec"]["format"])

    def test_document_page_explicit_ppt_generation_still_outputs_docx(self):
        prompt = "生成PPT，主题：AI办公平台建设讨论会，包含项目背景、建设内容、实施计划。"

        with patch("app.services.document_agent._minicpm_service_ready", return_value=True):
            route = classify_workflow(
                prompt,
                attachments=[],
                attachment_context="",
                force_output_format="docx",
            )

        self.assertEqual("generate", route["primary_operation"])
        self.assertEqual("docx", route["output_spec"]["format"])

    def test_document_page_plain_hello_still_outputs_docx(self):
        with patch("app.services.document_agent._minicpm_service_ready", return_value=True):
            route = classify_workflow(
                "你好",
                attachments=[],
                attachment_context="",
                force_output_format="docx",
            )

        self.assertEqual("generate", route["primary_operation"])
        self.assertEqual("docx", route["output_spec"]["format"])

    def test_report_completeness_does_not_duplicate_completion_section(self):
        sections = [
            {"heading": "报告正文", "content": "正文内容较短。"},
            {"heading": "报告补充说明", "content": "已有补充说明。"},
        ]

        result = _ensure_report_completeness(
            sections,
            "请生成一份报告，要求不少于2000字",
            "",
            {"primary_operation": "generate", "output_spec": {"format": "docx"}},
        )

        headings = [item["heading"] for item in result]
        self.assertEqual(1, headings.count("报告补充说明"))

    def test_report_completion_without_attachment_does_not_reference_attachment_facts(self):
        result = _ensure_report_completeness(
            [{"heading": "报告正文", "content": "正文内容较短。"}],
            "请生成一份正式报告，要求不少于2000字",
            "",
            {"primary_operation": "generate", "output_spec": {"format": "docx"}},
        )

        text = "\n".join(item.get("content", "") for item in result)
        self.assertNotIn("附件中已经出现的事实", text)
        self.assertNotIn("附件内容", text)

    def test_meeting_minutes_uses_deterministic_schema_and_task_table(self):
        prompt = (
            "发送创建一个 Word 文档。\n\n"
            "标题：\n项目周会会议纪要\n\n"
            "内容包含：\n1. 会议时间\n2. 参会人员\n3. 本周工作进展\n4. 存在问题\n5. 下周计划\n\n"
            "要求：\n- 使用标题样式\n- 插入一个表格记录任务分工\n- 保存为 docx 文件\n\n"
            "文件名：\n项目周会纪要.docx"
        )

        schema = generate_content_schema(prompt, {"primary_operation": "generate", "output_spec": {"format": "docx"}})

        self.assertEqual("项目周会会议纪要", schema["title"])
        section_text = "\n".join(item["heading"] + "\n" + item["content"] for item in schema["sections"])
        self.assertIn("会议时间", section_text)
        self.assertIn("参会人员", section_text)
        self.assertIn("本周工作进展", section_text)
        self.assertIn("存在问题", section_text)
        self.assertIn("下周计划", section_text)
        self.assertTrue(schema["tables"])
        self.assertEqual("任务分工表", schema["tables"][0]["title"])

    def test_generated_docx_uses_requested_filename(self):
        prompt = (
            "创建一个 Word 文档。\n标题：项目周会会议纪要\n"
            "内容包含：会议时间、参会人员、本周工作进展、存在问题、下周计划。\n"
            "要求：插入一个表格记录任务分工，保存为 docx 文件。\n"
            "文件名：项目周会纪要.docx"
        )

        with patch(
            "app.services.document_agent._call_qwen_text",
            return_value="# 项目周会会议纪要\n\n## 会议时间\n\n2026年6月8日",
        ):
            generated = generate_agent_output_file(
                prompt,
                route={"primary_operation": "generate", "output_spec": {"format": "docx"}},
            )

        self.assertEqual("项目周会纪要.docx", generated["filename"])
        self.assertEqual("markdown", generated["document_request"]["content_type"])

    def test_project_implementation_plan_docx_stays_on_requested_project(self):
        prompt = (
            "请生成一份正式项目实施方案。\n"
            "项目名称：智慧校园AI学习平台\n"
            "生成一个可直接交付给客户的Word文档内容。必须包含：封面、目录、项目背景、建设目标、功能设计、"
            "技术架构、实施计划、人员安排、风险控制、培训方案、验收标准、运维保障、预算报价。"
            "自动生成表格、项目甘特图（Mermaid）、组织架构图（Mermaid）、预算表。"
        )

        markdown = (
            "# 智慧校园AI学习平台项目实施方案\n\n"
            "## 封面\n\n项目名称：智慧校园AI学习平台\n\n"
            "## 目录\n\n1. 项目背景\n2. 建设目标\n3. 功能设计\n4. 技术架构\n5. 实施计划\n6. 人员安排\n7. 风险控制\n8. 培训方案\n9. 验收标准\n10. 运维保障\n11. 预算报价\n\n"
            "## 项目背景\n\n建设智慧校园AI学习平台。\n\n"
            "## 建设目标\n\n提升校园学习智能化水平。\n\n"
            "## 功能设计\n\n智能学习助手、学情分析、资源推荐。\n\n"
            "## 技术架构\n\n前后端分离，AI能力服务化。\n\n"
            "## 实施计划\n\n```mermaid\ngantt\n    title 项目计划\n```\n\n"
            "## 人员安排\n\n```mermaid\nflowchart TB\n    A[项目经理] --> B[实施组]\n```\n\n"
            "## 风险控制\n\n控制需求和进度风险。\n\n"
            "## 培训方案\n\n开展管理员和教师培训。\n\n"
            "## 验收标准\n\n按功能、性能和文档验收。\n\n"
            "## 运维保障\n\n提供上线支持。\n\n"
            "## 预算报价\n\n| 费用项 | 金额 |\n| --- | --- |\n| 软件平台 | 38.00 |"
        )
        with patch("app.services.document_agent._call_qwen_text", return_value=markdown):
            generated = generate_agent_output_file(
                prompt,
                route={"primary_operation": "generate", "output_spec": {"format": "docx"}},
            )

        rendered = generated["document_request"]["content"]
        for required in ["封面", "目录", "项目背景", "建设目标", "功能设计", "技术架构", "实施计划", "人员安排", "风险控制", "培训方案", "验收标准", "运维保障", "预算报价"]:
            self.assertIn(required, rendered)
        self.assertIn("```mermaid", rendered)
        self.assertIn("gantt", rendered)
        self.assertIn("flowchart", rendered)
        self.assertNotIn("2026年中国人工智能行业发展研究报告", rendered)
        self.assertEqual("markdown", generated["document_request"]["content_type"])


if __name__ == "__main__":
    unittest.main()
