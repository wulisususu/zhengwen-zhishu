"""Intent-first routing policy for chat, attachments, and document workflows.

The policy answers one question before any model chain runs:
what does the user want to receive? Attachments are context, not the
primary routing signal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class IntentDecision:
    intent: str
    confidence: float
    use_document_agent: bool
    reason: str
    answer_quality_guard: bool = False

    def model_dump(self) -> dict:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "use_document_agent": self.use_document_agent,
            "reason": self.reason,
            "answer_quality_guard": self.answer_quality_guard,
        }


def _contains(text: str, *markers: str) -> bool:
    return any(marker in text for marker in markers)


def _question_like(text: str) -> bool:
    return bool(
        "?" in text
        or "？" in text
        or re.search(
            r"(为什么|为何|怎么|如何|是否|能否|请问|解释|说明|分析原因|原因是|"
            r"求解|计算|证明|判断|回答|解答|完成下列要求|阅读.*资料|题目|试题)",
            text,
        )
        or re.search(
            r"\b(what|why|how|explain|solve|answer)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _formal_office_document_request(text: str) -> bool:
    text = text or ""
    return (
        "入职通知书" in text
        or "入职通知" in text
        or "录用通知书" in text
        or "录用通知" in text
    )


def _structured_document_blueprint_request(text: str) -> bool:
    text = (text or "").strip()
    if not text or _negated_file_generation_request(text):
        return False
    if not _contains(
        text,
        "投标文件",
        "招标文件",
        "技术部分",
        "技术标",
        "建设方案",
        "实施方案",
        "项目方案",
        "可行性研究报告",
        "申报书",
        "建议书",
    ):
        return False
    if re.search(r"(第[一二三四五六七八九十百0-9]+章|第[一二三四五六七八九十百0-9]+节)", text):
        return True
    if re.search(r"(^|\n)\s*[0-9]+(?:\.[0-9]+)+", text):
        return True
    return bool(
        re.search(
            r"(项目理解|项目背景|建设目标|总体设计|技术架构|实施计划|安全合规|服务方案|运维方案|质量保证)",
            text,
        )
        and len(text) >= 40
    )


def _exam_or_problem(text: str) -> bool:
    return bool(
        re.search(
            r"(阅读图文资料|完成下列要求|高考|中考|考试|试题|题目|地理题|数学题|物理题|"
            r"化学题|生物题|气压带|风带|太阳直射点|黄赤交角|解答|作答)",
            text,
        )
    )


def _explicit_file_output(text: str) -> bool:
    if _negated_file_generation_request(text):
        return False
    return bool(
        re.search(
            r"(生成|创建|制作|输出|导出|整理成|写成|改成|转换成|转成|下载|写).{0,24}"
            r"(word|docx|ppt|pptx|文档|报告|函|通知|公告|证明|纪要|清单|表格|正式)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(r"(word|docx|ppt|pptx).{0,24}(生成|创建|制作|输出|导出|下载|版)", text, flags=re.IGNORECASE)
    )


def _negated_file_generation_request(content: str) -> bool:
    text = (content or "").strip()
    if not text:
        return False
    output = r"(word|docx|ppt|pptx|excel|xlsx|文档|文件|报告|正式稿|正式版|可下载|下载链接)"
    action = r"(生成|创建|制作|输出|导出|整理成|写成|做成|保存为|下载|形成|转成|转换成)"
    negation = r"(别|不要|不需要|无需|不用|先不|暂不|不要给我|别给我)"
    return bool(
        re.search(negation + r".{0,8}" + action + r".{0,16}" + output, text, flags=re.IGNORECASE)
        or re.search(negation + r".{0,8}" + output, text, flags=re.IGNORECASE)
        or re.search(action + r".{0,8}" + negation + r".{0,8}" + output, text, flags=re.IGNORECASE)
    )


def is_explicit_file_generation_request(content: str) -> bool:
    text = (content or "").strip()
    if not text:
        return False
    if _negated_file_generation_request(text):
        return False
    if _formal_office_document_request(text):
        return True
    if _office_document_need(text):
        return True
    action = re.search(
        r"(生成|创建|制作|输出|导出|整理成|写成|做成|保存为|下载|形成|生成一份|写一份|写一篇|做一份|转成|转换成)",
        text,
        flags=re.IGNORECASE,
    )
    output = re.search(
        r"(word|docx|ppt|pptx|excel|xlsx|文档|文件|报告|正式稿|正式版|可下载|下载链接|"
        r"简历|周报|方案书|申请书|通知|公告|函|证明|纪要|清单|表格)",
        text,
        flags=re.IGNORECASE,
    )
    return bool(action and output)


def is_longform_document_request(content: str) -> bool:
    text = (content or "").strip()
    if not text or _negated_file_generation_request(text):
        return False
    if _structured_document_blueprint_request(text):
        return True
    create = re.search(
        r"(编写|撰写|起草|拟写|拟定|写一份|写一篇|生成一份|生成一篇|形成|输出|准备|提供)",
        text,
        flags=re.IGNORECASE,
    )
    document = re.search(
        r"(方案|报告|申报书|建设方案|实施方案|总结|汇报|材料|文稿|文档|制度|办法|申请书|计划书|策划书|说明书|可行性研究报告)",
        text,
        flags=re.IGNORECASE,
    )
    length = re.search(r"(不少于|不低于|约|大约)?\s*\d+\s*字", text)
    titled = "《" in text and "》" in text
    editing = re.search(r"(改短|缩短|修改|润色|优化|补充|追加|继续|续写|扩写|改写|调整|重写第|第.{0,4}[段章节部分])", text)
    return bool(create and document and not editing and (titled or length or len(text) >= 12))


def _office_document_need(text: str) -> bool:
    if _explicit_file_output(text):
        return True
    if _formal_office_document_request(text):
        return True
    if _contains(text, "面试邀约", "离职证明", "催款函", "处罚通报", "采购申请", "报销汇总", "员工档案", "背调提问清单"):
        return True
    return bool(
        re.search(
            r"(正式|商务|公文|公司).{0,12}(通知|公告|函|证明|报告|纪要|通报|申请|说明)"
            r"|面试邀约|离职证明|催款函|处罚通报|采购申请|报销汇总|员工档案|背调提问清单",
            text,
        )
    )


def _transform_attachment_need(text: str) -> bool:
    return bool(
        re.search(
            r"(整理成|改成|转成|转换|润色|改写|补充到|追加到|保留原文|保留结构|生成正式|输出正式)",
            text,
        )
    )


def _creative_need(text: str) -> bool:
    return bool(re.search(r"(写一首|故事|小说|文案|口号|海报文案|创意|剧本)", text))


def _code_need(text: str) -> bool:
    return bool(re.search(r"(代码|函数|脚本|报错|bug|接口|SQL|Python|JavaScript|TypeScript|Vue|React)", text, re.I))


def classify_request_intent(content: str, has_attachments: bool = False) -> IntentDecision:
    raw = content or ""
    text = raw.strip()
    low = text.lower()

    compact = re.sub(r"[\s,，。.!！?？~～]+", "", text).lower()
    if not text:
        return IntentDecision("conversation", 0.9, False, "empty_or_greeting")
    if _negated_file_generation_request(text):
        if has_attachments:
            return IntentDecision("attachment_qa", 0.88, False, "negated_file_generation_attachment", True)
        return IntentDecision("conversation", 0.82, False, "negated_file_generation")
    if compact in {"hi", "hello", "hey", "你好", "您好", "你好呀", "嗨", "在吗", "在么"}:
        return IntentDecision("conversation", 0.96, False, "greeting")

    if _formal_office_document_request(text):
        return IntentDecision("document_generation", 0.95, True, "formal_office_document")

    if _contains(low, "word", "docx", "ppt", "pptx") and _contains(
        text, "生成", "创建", "制作", "输出", "导出", "下载", "版", "写"
    ):
        return IntentDecision("document_generation", 0.94, True, "file_format_requested")

    if _office_document_need(text):
        return IntentDecision("document_generation", 0.92, True, "explicit_file_or_office_document")

    if _exam_or_problem(text):
        return IntentDecision("question_answering", 0.95, False, "exam_or_problem_question", True)

    if _code_need(text) and not _explicit_file_output(text):
        return IntentDecision("code", 0.88, False, "code_question_or_debug", True)

    if _question_like(text):
        return IntentDecision("question_answering", 0.86, False, "question_like_request", bool(has_attachments))

    if has_attachments and _contains(
        text,
        "建议",
        "解释",
        "分析",
        "看看",
        "看一下",
        "什么意思",
        "普通话",
        "白话",
        "图文",
        "图片和文字",
        "文字和图片",
    ):
        return IntentDecision("question_answering", 0.84, False, "attachment_answer_request", True)

    if has_attachments and _transform_attachment_need(text):
        return IntentDecision("document_transformation", 0.82, True, "attachment_transformation")

    if has_attachments and _contains(
        text,
        "总结",
        "概括",
        "提取",
        "对比",
        "比较",
        "风险",
        "清单",
        "表格",
        "报告",
        "整理",
    ):
        return IntentDecision("document_analysis", 0.76, True, "attachment_document_analysis")

    if _creative_need(text):
        return IntentDecision("creative", 0.78, False, "creative_generation")

    if _contains(low, "word", "docx", "ppt", "pptx"):
        return IntentDecision("document_generation", 0.72, True, "file_format_mentioned")

    return IntentDecision("conversation", 0.62, False, "default_chat")


def classify_chat_intent(content: str, has_attachments: bool = False) -> IntentDecision:
    if is_explicit_file_generation_request(content):
        return IntentDecision("handoff_to_document", 0.94, False, "chat_explicit_file_generation")
    if has_attachments:
        return IntentDecision("attachment_qa", 0.9, False, "chat_attachment_context", True)
    decision = classify_request_intent(content, has_attachments=False)
    if decision.use_document_agent:
        return IntentDecision("conversation", 0.72, False, "chat_guard_forced_conversation", decision.answer_quality_guard)
    return decision


def classify_document_intent(content: str, has_attachments: bool = False) -> IntentDecision:
    # The document page is already a dedicated document-generation entry.
    # Do not downgrade short or conversational-looking prompts to document_chat here.
    if str(content or "").strip():
        return IntentDecision("document_generation", 0.96, True, "document_page_forced_generation")
    if is_explicit_file_generation_request(content):
        return IntentDecision("document_generation", 0.95, True, "document_explicit_file_generation")
    if is_longform_document_request(content):
        return IntentDecision("document_generation", 0.91, True, "document_longform_request")
    decision = classify_request_intent(content, has_attachments=has_attachments)
    if decision.intent in {"document_generation", "document_transformation"} and decision.use_document_agent:
        return decision
    if has_attachments and decision.intent in {"question_answering", "document_analysis"}:
        return IntentDecision("document_chat", 0.86, False, "document_attachment_text_answer", True)
    if decision.use_document_agent:
        return IntentDecision("document_chat", 0.76, False, "document_guard_text_answer", decision.answer_quality_guard)
    return IntentDecision("document_chat" if decision.intent == "conversation" else decision.intent, decision.confidence, False, decision.reason, decision.answer_quality_guard)
