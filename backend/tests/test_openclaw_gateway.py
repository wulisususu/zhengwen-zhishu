import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.services.openclaw_gateway import (  # noqa: E402
    build_chat_input,
    build_document_chunk_input,
    build_document_prompt_budget,
    build_document_input,
    build_document_outline_input,
    build_knowledge_input,
    call_openclaw_document,
    classify_openclaw_provider_error,
    compact_document_filename,
    constrain_document_summary,
    create_document_generation_state,
    ensure_outline_covers_requirements,
    extract_document_task_payload,
    extract_kb_grounding_from_trace_rows,
    extract_kb_grounding_payload,
    extract_openclaw_completed_text,
    extract_openclaw_prompt_error,
    extract_openclaw_stop_reason,
    extract_openclaw_stream_delta,
    merge_openclaw_text_delta,
    prepare_document_markdown_for_render,
    prepare_document_text_for_display,
    extract_response_text,
    finalize_document_outcome,
    parse_openclaw_sse_event,
    should_use_document_chunk_mode,
    synthesize_document_reply,
    should_continue_document_chunk,
    update_document_generation_state,
    validate_document_task_payload,
)


class OpenClawGatewayTests(unittest.TestCase):
    def test_extracts_document_task_from_nested_tool_result(self):
        payload = {
            "status": "completed",
            "output": [
                {
                    "type": "function_call_output",
                    "name": "document_render_docx",
                    "output": {
                        "details": {
                            "ok": True,
                            "data": {
                                "task_id": "task_123",
                                "status": "queued",
                                "title": "weekly.docx",
                                "download_url": "/api/v1/files/9/download",
                                "workflow_type": "document",
                            },
                        }
                    },
                }
            ],
        }

        task = extract_document_task_payload(payload)

        self.assertEqual("task_123", task["task_id"])
        self.assertEqual("queued", task["status"])
        self.assertEqual("weekly.docx", task["title"])
        self.assertEqual("/api/v1/files/9/download", task["download_url"])

    def test_extracts_human_readable_response_text(self):
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "已为你创建文档任务。"},
                        {"type": "output_text", "text": "请稍候查看生成进度。"},
                    ],
                }
            ]
        }

        text = extract_response_text(payload)

        self.assertIn("已为你创建文档任务。", text)
        self.assertIn("请稍候查看生成进度。", text)

    def test_extract_response_text_ignores_openclaw_empty_placeholder(self):
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "No response from OpenClaw."}],
                }
            ]
        }

        text = extract_response_text(payload)

        self.assertEqual("", text)

    def test_extract_prompt_error_detects_nested_provider_context_overflow(self):
        payload = {
            "type": "response.completed",
            "response": {
                "output": [],
                "stopReason": "error",
                "errorMessage": "Context size has been exceeded.",
                "errorCode": "500",
                "errorType": "server_error",
                "errorBody": "{\"code\":500,\"message\":\"Context size has been exceeded.\",\"type\":\"server_error\"}",
            },
        }

        error = extract_openclaw_prompt_error(payload)

        self.assertEqual("context_overflow", error["error_type"])
        self.assertIn("Context size has been exceeded", error["message"])

    def test_chunk_state_drops_openclaw_empty_placeholder(self):
        state = create_document_generation_state(
            doc_id=789,
            title="测试文档",
            outline=[{"id": "1", "title": "项目概述", "level": 1, "writing_goal": "写项目概述。"}],
        )

        updated = update_document_generation_state(
            state,
            "# 项目概述\n\n正文第一段。\n\nNo response from OpenClaw.",
            stop_reason="",
        )

        self.assertIn("正文第一段", updated["full_markdown"])
        self.assertNotIn("No response from OpenClaw", updated["full_markdown"])
        self.assertNotIn("No response from OpenClaw", updated["last_output_tail"])

    def test_call_openclaw_document_normalizes_failed_provider_response(self):
        failed_payload = {
            "id": "resp_failed",
            "object": "response",
            "status": "failed",
            "model": "openclaw/docgen",
            "output": [],
            "error": {"code": "api_error", "message": "upstream provider timeout"},
        }

        with patch("app.services.openclaw_gateway._openclaw_cfg", return_value={
            "enabled": True,
            "gateway_token": "token",
            "gateway_base_url": "http://127.0.0.1:18789",
            "document_model": "openclaw/docgen",
            "document_agent_id": "docgen",
            "timeout_seconds": 30,
        }), patch(
            "app.services.openclaw_gateway._post_json",
            return_value=(200, failed_payload, '{"status":"failed","error":{"message":"upstream provider timeout"}}'),
        ):
            result = call_openclaw_document("生成Word文档", conversation_id=693, user_id=1)

        self.assertFalse(result["ok"])
        self.assertIsNone(result["task"])
        self.assertIn("上游模型超时", result["assistant_text"])
        self.assertNotIn('"status":"failed"', result["assistant_text"])
        self.assertNotIn("正在生成文档大纲", result["assistant_text"])

    def test_builds_self_repair_reply_when_task_missing(self):
        reply = synthesize_document_reply(None, "")

        self.assertIn("回到上一步", reply)
        self.assertNotIn("OpenClaw", reply)

    def test_synthesize_document_reply_replaces_queue_receipt_with_friendly_copy(self):
        reply = synthesize_document_reply(
            {"task_id": "task_123", "status": "queued"},
            "文档生成任务已提交：\n\n- Task ID: task_123\n- 状态: 已加入队列\n\n文档正在后台生成中。",
        )

        self.assertIn("中科信创自研模型", reply)
        self.assertNotIn("Task ID", reply)
        self.assertNotIn("已加入队列", reply)

    def test_synthesize_document_reply_preserves_outline_preview_text(self):
        reply = synthesize_document_reply(
            {"task_id": "task_123", "status": "queued"},
            "我将根据您的要求生成word\n正在开始执行...\n\n文档大纲预览：\n月度运营分析报告\n1. 核心运营数据概览",
        )

        self.assertIn("文档大纲预览", reply)
        self.assertIn("月度运营分析报告", reply)

    def test_build_document_input_includes_ids_and_attachment_hints(self):
        text = build_document_input(
            content="生成项目周报",
            conversation_id=626,
            user_id=11,
            attachment_ids=[31, 32],
            attachment_context="附件摘要",
        )

        self.assertIn("conversation_id=626", text)
        self.assertIn("user_id=11", text)
        self.assertIn("31", text)
        self.assertIn("附件摘要", text)
        self.assertIn("完整 markdown 正文", text)
        self.assertIn("document_render_docx", text)
        self.assertNotIn("必须调用 generate_document", text)

    def test_should_use_document_chunk_mode_for_long_manual(self):
        self.assertTrue(should_use_document_chunk_mode("生成完整运维手册，包含部署、监控、SOP、应急预案，不少于10000字。"))
        self.assertTrue(should_use_document_chunk_mode("编写项目技术方案，包含七个章节，要求详细全面。", estimated_sections=7))
        self.assertFalse(should_use_document_chunk_mode("生成一份项目周报。", estimated_sections=3))

    def test_build_document_outline_input_is_private_and_structured(self):
        text = build_document_outline_input(
            content="生成完整运维手册",
            conversation_id=784,
            user_id=11,
            attachment_context="附件摘要",
        )

        self.assertIn("只返回 JSON", text)
        self.assertIn("用户不可见", text)
        self.assertIn("generation_state", text)
        self.assertIn("生成完整运维手册", text)
        self.assertIn("附件摘要", text)

    def test_build_document_chunk_input_contains_cursor_tail_and_no_repeat_rules(self):
        outline = [
            {"id": "1", "title": "系统概述", "level": 1, "children": []},
            {"id": "2", "title": "部署方案", "level": 1, "children": []},
        ]
        state = create_document_generation_state(doc_id=784, outline=outline, title="运维手册")
        state["completed_sections"] = ["1"]
        state["current_section_id"] = "2"
        state["last_output_tail"] = "上一段最后内容"

        text = build_document_chunk_input(
            content="生成完整运维手册",
            generation_state=state,
            conversation_id=784,
            user_id=11,
        )

        self.assertIn("当前 cursor/current_section_id：2", text)
        self.assertIn("已完成章节：1", text)
        self.assertIn("上一段输出末尾", text)
        self.assertIn("上一段最后内容", text)
        self.assertIn("不能重写前文", text)
        self.assertIn("禁止输出“下面继续”", text)
        self.assertIn("不要调用 document_render_docx", text)

    def test_update_document_generation_state_appends_chunk_and_tail(self):
        outline = [
            {"id": "1", "title": "系统概述", "level": 1, "children": []},
            {"id": "2", "title": "部署方案", "level": 1, "children": []},
        ]
        state = create_document_generation_state(doc_id=784, outline=outline, title="运维手册")

        updated = update_document_generation_state(state, "第一章内容" * 80)

        self.assertEqual(1, updated["chunk_index"])
        self.assertIn("1", updated["completed_sections"])
        self.assertEqual("2", updated["current_section_id"])
        self.assertIn("第一章内容", updated["full_markdown"])
        self.assertLessEqual(len(updated["last_output_tail"]), 800)
        self.assertFalse(updated["is_final_chunk"])

        updated = update_document_generation_state(updated, "第二章内容")

        self.assertTrue(updated["is_final_chunk"])
        self.assertEqual("completed", updated["status"])

    def test_stop_reason_length_is_extracted_from_openclaw_payload(self):
        payload = {
            "type": "model.completed",
            "items": [
                {
                    "text": "正文片段",
                    "stopReason": "length",
                    "model": "Qwen3.5-35B-A3B-UD-Q4_K_XL.gguf",
                }
            ],
        }

        self.assertEqual("length", extract_openclaw_stop_reason(payload))

    def test_length_stopped_chunk_does_not_advance_cursor(self):
        outline = [
            {"id": "1", "title": "身份认证", "level": 1, "children": []},
            {"id": "2", "title": "权限管理", "level": 1, "children": []},
        ]
        state = create_document_generation_state(doc_id=784, outline=outline, title="安全建设方案")

        updated = update_document_generation_state(
            state,
            "## 身份认证\n\n**保障措施**。说明应急",
            stop_reason="length",
        )

        self.assertEqual(1, updated["chunk_index"])
        self.assertEqual([], updated["completed_sections"])
        self.assertEqual("1", updated["current_section_id"])
        self.assertEqual("generating", updated["status"])
        self.assertTrue(should_continue_document_chunk(updated, stop_reason="length", chunk_text="**保障措施**。说明应急"))

    def test_outline_is_augmented_with_explicit_required_modules(self):
        content = "请编写《政务AI助手安全建设方案》。包含：身份认证 权限管理 数据加密 日志审计 漏洞管理 灾备方案。字数不少于8000字。"
        outline = [
            {"id": "1", "title": "数据安全法", "level": 1, "children": []},
            {"id": "2", "title": "灾备方案", "level": 1, "children": []},
        ]

        augmented = ensure_outline_covers_requirements(outline, content)
        titles = [item["title"] for item in augmented]

        for expected in ["身份认证", "权限管理", "数据加密", "日志审计", "漏洞管理", "灾备方案"]:
            self.assertIn(expected, titles)

    def test_chunk_prompt_uses_section_slice_not_full_outline_json(self):
        outline = []
        for index in range(1, 11):
            outline.append({
                "id": str(index),
                "title": f"第{index}章 安全模块{index}",
                "level": 1,
                "writing_goal": "围绕当前安全模块生成正文。" * 8,
                "children": [
                    {"id": f"{index}.{child}", "title": f"子节{child}", "level": 2, "writing_goal": "详细说明。" * 10, "children": []}
                    for child in range(1, 5)
                ],
            })
        state = create_document_generation_state(doc_id=788, outline=outline, title="政务AI助手安全建设方案")
        state["last_output_tail"] = "上一段尾部。" * 120

        prompt = build_document_chunk_input(
            content="请编写《政务AI助手安全建设方案》。包含：身份认证 权限管理 数据加密 日志审计 漏洞管理 灾备方案。字数不少于8000字。",
            generation_state=state,
            conversation_id=788,
            user_id=11,
        )

        self.assertLess(len(prompt), 3000)
        self.assertNotIn("后台完整大纲 JSON", prompt)
        self.assertNotIn('"outline"', prompt)
        self.assertIn("当前章节", prompt)
        self.assertIn("必备模块", prompt)
        self.assertLessEqual(len(state["last_output_tail"]), 800)

    def test_document_prompt_budget_reports_compressed_and_overflow(self):
        compressed = build_document_prompt_budget(
            user_prompt="x" * 3200,
            outline_text="o" * 1000,
            state_text="s" * 200,
            tail_text="t" * 400,
            system_prompt_chars=3000,
            max_allowed_chars=8000,
        )
        overflow = build_document_prompt_budget(
            user_prompt="x" * 6000,
            outline_text="o" * 4000,
            state_text="s" * 2000,
            tail_text="t" * 1000,
            system_prompt_chars=30520,
            max_allowed_chars=8000,
        )

        self.assertEqual("compressed", compressed["budget_status"])
        self.assertEqual("overflow_blocked", overflow["budget_status"])

    def test_extracts_context_overflow_prompt_error(self):
        payload = {
            "type": "response.completed",
            "response": {
                "promptError": "Context overflow: prompt too large for the model (precheck).",
                "promptErrorSource": "precheck",
            },
        }

        error = extract_openclaw_prompt_error(payload)

        self.assertEqual("context_overflow", error["error_type"])
        self.assertIn("Context overflow", error["message"])

    def test_summary_is_constrained_to_short_status_text(self):
        raw = "# 政务AI助手安全建设方案\n\n## 第一章 项目概述\n\n" + ("正文内容。" * 120)

        summary = constrain_document_summary(raw)

        self.assertLessEqual(len(summary), 150)
        self.assertNotIn("#", summary)
        self.assertNotIn("第一章", summary)

    def test_classify_openclaw_provider_error_returns_clear_8081_message(self):
        result = classify_openclaw_provider_error(
            ConnectionRefusedError("ECONNREFUSED"),
            provider_url="http://192.168.10.212:8081/v1",
        )

        self.assertEqual("connection_refused", result["error_type"])
        self.assertIn("大模型服务当前不可用", result["message"])
        self.assertIn("192.168.10.212:8081", result["message"])

    def test_compact_filename_prefers_operations_manual_over_generic_fault_words(self):
        title = compact_document_filename("生成完整运维手册，包含部署方案、监控巡检、备份恢复、故障处理、安全管理六章。")

        self.assertIn("运维", title)
        self.assertNotIn("事故", title)

    def test_build_chat_input_includes_history_and_attachment_context(self):
        text = build_chat_input(
            content="继续处理上面的内容",
            history_messages=[
                {"role": "user", "content": "先帮我总结一下"},
                {"role": "assistant", "content": "已经总结好了"},
            ],
            attachment_context="这是附件摘要",
        )

        self.assertIn("user: 先帮我总结一下", text)
        self.assertIn("assistant: 已经总结好了", text)
        self.assertIn("这是附件摘要", text)
        self.assertIn("继续处理上面的内容", text)

    def test_build_chat_input_includes_voice_tool_routing_rules_and_context_ids(self):
        text = build_chat_input(
            content="把这段音频转成文字，再朗读一下结果",
            history_messages=[
                {"role": "user", "content": "附件已经上传了"},
            ],
            attachment_context="附件里是一段会议录音",
            conversation_id=701,
            user_id=11,
            attachment_ids=[401, 402],
            audio_attachment_ids=[402],
        )

        self.assertIn("conversation_id=701", text)
        self.assertIn("user_id=11", text)
        self.assertIn("401", text)
        self.assertIn("402", text)
        self.assertIn("必须调用 synthesize_speech", text)
        self.assertIn("必须调用 transcribe_audio", text)
        self.assertIn("audio_bytes", text)
        self.assertIn("原样带上 conversation_id、user_id 和其中一个 file_id", text)

    def test_build_chat_input_marks_explicit_tts_requests_as_mandatory_audio_calls(self):
        text = build_chat_input(
            content="请把这句话读出来：OpenClaw Phase2B TTS smoke test。",
            history_messages=[],
            attachment_context="",
            conversation_id=701,
            user_id=11,
        )

        self.assertIn("明确的 TTS 请求", text)
        self.assertIn("必须调用 synthesize_speech", text)
        self.assertIn("不要输出音标、拼读、发音解释", text)
        self.assertIn("冒号、引号或书名号后给了要朗读的正文", text)

    def test_build_knowledge_input_requires_kb_search(self):
        text = build_knowledge_input(
            content="帮我查一下制度里关于请假的规定",
            history_messages=[
                {"role": "user", "content": "我们继续知识库问题"},
            ],
        )

        self.assertIn("必须先调用 kb_search", text)
        self.assertIn("如果不调用 kb_search，这次回答就是无效的", text)
        self.assertIn("我们继续知识库问题", text)
        self.assertIn("帮我查一下制度里关于请假的规定", text)

    def test_validates_document_task_payload(self):
        task = validate_document_task_payload({
            "task_id": "task_999",
            "status": "queued",
            "conversation_id": 633,
        })

        self.assertEqual("task_999", task["task_id"])
        self.assertEqual("queued", task["status"])

    def test_rejects_invalid_document_task_payload(self):
        task = validate_document_task_payload({
            "status": "queued",
            "conversation_id": 633,
        })

        self.assertIsNone(task)

    def test_finalize_document_outcome_prefers_detected_task(self):
        result = finalize_document_outcome(
            task={"task_id": "task_live", "status": "queued", "conversation_id": 633},
            response_text="",
            timed_out=True,
        )

        self.assertTrue(result["task_detected"])
        self.assertIn("中科信创自研模型", result["reply_text"])
        self.assertNotIn("task_live", result["reply_text"])
        self.assertEqual("task_live", result["task"]["task_id"])

    def test_finalize_document_outcome_returns_self_repair_without_task(self):
        result = finalize_document_outcome(
            task=None,
            response_text="",
            timed_out=True,
        )

        self.assertFalse(result["task_detected"])
        self.assertIn("回到上一步", result["reply_text"])
        self.assertNotIn("OpenClaw", result["reply_text"])

    def test_parses_openclaw_sse_event_and_text_delta(self):
        event_name, parsed = parse_openclaw_sse_event(
            'data: {"type":"response.output_text.delta","delta":"收到"}'
        )

        self.assertEqual("", event_name)
        self.assertEqual("收到", extract_openclaw_stream_delta(parsed["payload"]))

    def test_extracts_completed_text_from_response_completed_payload(self):
        text = extract_openclaw_completed_text(
            {
                "type": "response.completed",
                "response": {
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": "收到。"},
                            ],
                        }
                    ]
                },
            }
        )

        self.assertEqual("收到。", text)

    def test_prepares_document_markdown_for_render_without_summary_or_openclaw_tail(self):
        raw = """### 本周总结

本周完成核心功能开发，整体进度正常。

---

# 项目周报

## 本周工作

- 完成用户认证模块开发

---

现在生成正式文档...
---

**文档任务已创建**

| 字段 | 值 |
|------|-----|
| **task_id** | `task_123` |

文档内容已生成完成，Markdown 正文已渲染为 DOCX 任务。

---

MEDIA:document_render_docx"""

        cleaned = prepare_document_markdown_for_render(raw)

        self.assertTrue(cleaned.startswith("# 项目周报"))
        self.assertIn("## 本周工作", cleaned)
        self.assertNotIn("本周总结", cleaned)
        self.assertNotIn("现在生成正式文档", cleaned)
        self.assertNotIn("task_id", cleaned)
        self.assertNotIn("MEDIA:document_render_docx", cleaned)

    def test_prepares_plain_document_body_without_footer_metadata(self):
        raw = """小总结：
本月核心运营数据显示业务增长稳健。
────────────────────────
月度运营分析报告
报告周期： 2024 年 10 月

一、核心数据概览
业务保持健康增长态势。

────────────────────────
报告生成： OpenClaw 文档 Agent
数据源： 运营数据统计系统
联系方式： operations@company.com
------"""

        cleaned = prepare_document_markdown_for_render(raw)

        self.assertTrue(cleaned.startswith("月度运营分析报告"))
        self.assertIn("一、核心数据概览", cleaned)
        self.assertNotIn("小总结", cleaned)
        self.assertNotIn("报告生成", cleaned)
        self.assertNotIn("数据源", cleaned)
        self.assertNotIn("联系方式", cleaned)

    def test_prepares_document_text_for_display_keeps_summary_but_removes_tool_tail(self):
        raw = """小总结：
这是一段给用户看的总结。

# 项目周报

正文内容。

<!--SECTION_COMPLETE:1-->

**文档任务已创建**

| **task_id** | `task_123` |

MEDIA:document_render_docx"""

        cleaned = prepare_document_text_for_display(raw)

        self.assertIn("小总结", cleaned)
        self.assertIn("# 项目周报", cleaned)
        self.assertNotIn("SECTION_COMPLETE", cleaned)
        self.assertNotIn("文档任务已创建", cleaned)
        self.assertNotIn("task_id", cleaned)
        self.assertNotIn("MEDIA:document_render_docx", cleaned)

    def test_prepares_display_text_without_openclaw_status_footer_variant(self):
        raw = """# 月度运营分析报告

## 一、核心数据概览

正文内容。

<!--SECTION_COMPLETE:2--># 追加标题

报告编制： OpenClaw 文档生成系统
数据周期： 2024 年 10 月 1 日 - 2024 年 10 月 31 日## 任务状态

| 字段 | 值 |
|------|-----|
| status | done |
"""

        cleaned = prepare_document_text_for_display(raw)

        self.assertIn("# 月度运营分析报告", cleaned)
        self.assertIn("正文内容", cleaned)
        self.assertNotIn("SECTION_COMPLETE", cleaned)
        self.assertNotIn("报告编制", cleaned)
        self.assertNotIn("数据周期", cleaned)
        self.assertNotIn("任务状态", cleaned)
        self.assertNotIn("| 字段 | 值 |", cleaned)

    def test_cleans_section_complete_marker_even_when_attached_to_heading(self):
        raw = "<!--SECTION_COMPLETE:1--># 产品背景\n\n正文。"

        cleaned = prepare_document_text_for_display(raw)

        self.assertTrue(cleaned.startswith("# 产品背景"))
        self.assertNotIn("SECTION_COMPLETE", cleaned)

    def test_merges_openclaw_done_full_text_without_duplicate_replay(self):
        current = "### 本周总结\n\n总结内容。\n\n# 项目周报\n\n正文内容。"
        replay = current + "\n\n**文档任务已创建**"

        merged = merge_openclaw_text_delta(current, replay)

        self.assertEqual(replay, merged)

    def test_extracts_kb_grounding_payload_from_tool_result(self):
        grounding = extract_kb_grounding_payload(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call_output",
                    "name": "kb_search",
                    "output": {
                        "details": {
                            "ok": True,
                            "data": {
                                "passages": [{"chunk_id": "c1", "chunk_text": "请假制度"}],
                                "sources": [{"chunk_id": "c1", "filename": "employee-handbook.md", "score": 0.91}],
                            },
                        }
                    },
                },
            }
        )

        self.assertTrue(grounding["grounded"])
        self.assertEqual(1, grounding["source_count"])
        self.assertEqual("employee-handbook.md", grounding["sources"][0]["filename"])

    def test_extracts_empty_kb_grounding_payload_when_tool_returns_no_sources(self):
        grounding = extract_kb_grounding_payload(
            {
                "response": {
                    "output": [
                        {
                            "type": "function_call_output",
                            "name": "kb_search",
                            "output": {
                                "details": {
                                    "ok": True,
                                    "data": {
                                        "passages": [],
                                        "sources": [],
                                    },
                                }
                            },
                        }
                    ]
                }
            }
        )

        self.assertFalse(grounding["grounded"])
        self.assertEqual(0, grounding["source_count"])
        self.assertEqual([], grounding["sources"])

    def test_extracts_kb_grounding_from_latest_new_trace_rows(self):
        rows = [
            json.dumps({
                "call_id": "old-call",
                "tool_name": "kb_search",
                "status": "completed",
                "result_snapshot": {
                    "passages": [],
                    "sources": [],
                },
            }, ensure_ascii=False),
            json.dumps({
                "call_id": "new-call",
                "tool_name": "kb_search",
                "status": "validated",
                "result_snapshot": {
                    "passages": [{"chunk_id": "c9"}],
                    "sources": [{"chunk_id": "c9", "filename": "kb_test.txt", "score": 0.88}],
                },
            }, ensure_ascii=False),
        ]

        grounding = extract_kb_grounding_from_trace_rows(rows, known_call_ids={"old-call"})

        self.assertEqual("new-call", grounding["call_id"])
        self.assertTrue(grounding["grounded"])
        self.assertEqual(1, grounding["source_count"])
        self.assertEqual("kb_test.txt", grounding["sources"][0]["filename"])


if __name__ == "__main__":
    unittest.main()
