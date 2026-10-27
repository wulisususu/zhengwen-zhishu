"""政策问答的「对话」路线：打招呼、库外问题、无关问题的友好回应。

设计要点（对应 docs/superpowers/specs/2026-10-27-policy-qa-conversational-design.md）：
- 这一类的回答仍然只调一次模型，但走一套受约束的系统提示词；
- 回复由 guard_reply 做质检：出现引用标记之外的书名、文号或代码块，一律换兜底话术，
  不给模型编造政策内容的机会；
- 无关问题只说明范围并建议找对人，不给出具体步骤、命令或答案；
- 兜底话术按问题内容确定性地轮换，措辞不千篇一律，也便于测试。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["greeting", "policy", "other"]

#: 「像政策问题」的判定词：只用于兜底话术与给模型的提示，不决定路线
_POLICY_KEYWORD_RE = re.compile(r"政策|办法|通知|规定|条例|意见|补贴|补助|申请|办理|文件")
_GREETINGS = ("你好", "您好", "hi", "hello", "在吗", "早上好", "下午好", "晚上好", "谢谢", "辛苦了")
_PUNCT_RE = re.compile(r"[，,。．.!！?？~～\s]")

#: 对话回复的字数上限，超长时截到句末标点
REPLY_MAX_CHARS = 300

CHAT_SYSTEM_PROMPT = (
    "你是本单位政务办公系统里的「政策问答」助手，围绕本单位政策库服务。"
    "打招呼或寒暄时，自然、简短地回应，说明你能做什么（查政策条款、解读政策要求、按名称找政策文件），"
    "并给一两个问法示例。"
    "问的是政策，但下文「政策库情况」没有给出相关内容时，如实说明政策库暂未找到相关内容，"
    "建议换个关键词、写明政策全称，或请审核人把文件导入政策库；"
    "不得凭你自己的知识陈述任何政策内容、政策名称、文号或数字。"
    "问的与政策和政务办公无关（电脑操作、编程、生活常识等）时，友好说明这里专门解答政策问题，"
    "建议咨询信息部门或相关专业人员，不要给出任何具体步骤、命令或答案。"
    "措辞自然，不要每次都是同一句话；不超过 120 字；不使用 [1] 这类引用标记；不输出标题或代码块。"
)

_FALLBACKS: dict[str, list[str]] = {
    "greeting": [
        "您好！我是政策问答助手，可以帮您查找政策条款、解读政策要求，也能按名称找政策文件。"
        "您可以直接问，比如「小微企业贷款贴息的比例是多少」。",
        "您好，有什么政策方面的问题？可以直接问条款内容，也可以说「帮我看看《某某办法》」，我来找依据。",
        "您好！政策方面的问题可以直接问我；想看某份文件的整体内容，就说「帮我看看某某政策」。",
    ],
    "policy": [
        "政策库里暂时没有找到和这个问题直接相关的内容。可以换个关键词再问，或者告诉我政策的全称；"
        "如果文件还没入库，可以请审核人导入后再来问。",
        "这个问题我在政策库里没有查到相关条款。建议换几个关键词试试，或者写明政策的全称和文号；"
        "文件尚未入库的话，请审核人在政策库导入。",
        "政策库中暂时没有匹配到相关内容。您可以换个问法、写明政策全称，"
        "或请审核人先把文件导入政策库，我再帮您解读。",
    ],
    "other": [
        "这个问题不在政策问答的范围内，建议咨询单位信息部门或相关专业同事。政策方面有什么需要，随时问我。",
        "这里专门解答政策方面的问题，这类技术问题建议找信息部门或相关专业人员处理。政策上的事随时来问我。",
        "抱歉，这个我帮不上忙——我只负责解读政策库里的文件。这类问题建议咨询信息部门；政策方面的问题欢迎随时问。",
    ],
}


@dataclass
class ChatContext:
    """对话路线的上下文：路线分类、政策库概况、可点选建议、范围提示。"""

    kind: Kind
    stats: dict
    suggestions: list[dict] = field(default_factory=list)
    scope_hint: str = ""
    known_titles: set[str] = field(default_factory=set)


def classify(question: str, has_candidates: bool) -> Kind:
    """把问题分成 greeting / policy / other。

    只影响兜底话术和给模型的提示；是否走对话路线由「有没有依据」决定。
    """
    text = _PUNCT_RE.sub("", (question or "").strip()).lower()
    if text in _GREETINGS or any(text.startswith(g) and len(text) <= 8 for g in _GREETINGS):
        return "greeting"
    if has_candidates or _POLICY_KEYWORD_RE.search(question or ""):
        return "policy"
    return "other"


def build_chat_messages(question: str, history: list[dict], ctx: ChatContext) -> list[dict[str, str]]:
    """系统提示词 + 最近几轮问答 + 带政策库情况说明的本轮问题。"""
    messages: list[dict[str, str]] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    for turn in history or []:
        if turn.get("question"):
            messages.append({"role": "user", "content": str(turn["question"])})
        if turn.get("answer"):
            messages.append({"role": "assistant", "content": str(turn["answer"])})

    stats = ctx.stats or {}
    parts = [f"政策库情况：共 {stats.get('total', 0)} 份，"
             f"已核验 {stats.get('verified', 0)} 份，待核实 {stats.get('unverified', 0)} 份。"]
    if ctx.suggestions:
        names = "、".join(f"《{s['title']}》" for s in ctx.suggestions)
        parts.append(f"名称相近的政策：{names}。")
    if ctx.scope_hint:
        parts.append(ctx.scope_hint)
    parts.append(f"问题类型参考：{ctx.kind}")
    parts.append(f"用户问题：{question}")
    messages.append({"role": "user", "content": "\n".join(parts)})
    return messages


def _strip_reasoning(text: str) -> str:
    cleaned = re.sub(r"<think[^>]*>[\s\S]*?</think\s*>", "", text or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"<think[^>]*>[\s\S]*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned


def guard_reply(text: str, known_titles: set[str]) -> str | None:
    """对话回复质检。返回清理后的文本；None 表示必须改用兜底话术。

    会拦下三类危险输出：代码块、文号、政策库里不存在的《书名》——
    这些都是模型在用自身知识编内容，哪怕看起来在客气地拒绝也不能放行。
    """
    cleaned = _strip_reasoning(text or "")
    cleaned = re.sub(r"\[\d+\]", "", cleaned)
    cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```\s*$", "", cleaned).strip()
    if "```" in cleaned:
        return None
    if re.search(r"〔\d{4}〕", cleaned):
        return None
    for name in (n.strip() for n in re.findall(r"《([^》]{1,80})》", cleaned)):
        if not name:
            continue
        if name in known_titles:
            continue
        if any(name in title or title in name for title in known_titles):
            continue
        return None
    if not cleaned:
        return None
    if len(cleaned) > REPLY_MAX_CHARS:
        head = cleaned[:REPLY_MAX_CHARS]
        ends = [head.rfind(p) for p in "。！？；"]
        cut = max(ends)
        cleaned = head[:cut + 1] if cut >= 0 else head
    return cleaned


def fallback_reply(ctx: ChatContext, question: str) -> str:
    """模型不可用或被质检拦下时的固定话术，按问题内容确定性轮换。"""
    templates = _FALLBACKS.get(ctx.kind) or _FALLBACKS["policy"]
    reply = templates[sum(map(ord, question or " ")) % len(templates)]
    if ctx.kind == "policy" and not ctx.stats.get("verified"):
        reply += "目前政策库里的文件都还没有核验。"
    return reply


def chat_payload(reply: str, generated_by: str, ctx: ChatContext, scope: str) -> dict:
    """对话路线的返回结构：与 answered / no_basis 同级，靠 status 区分。"""
    return {
        "status": "chat",
        "sufficient": False,
        "reply": reply,
        "conclusion": "",
        "supplement": "",
        "reason": "",
        "reason_code": "",
        "manual_confirm": [],
        "citations": [],
        "candidates": [],
        "suggestions": list(ctx.suggestions),
        "scope_hint": ctx.scope_hint,
        "meta": {"scope": scope, "generated_by": generated_by, "kind": ctx.kind, "model": ""},
    }
