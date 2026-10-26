"""公文起草服务：结构化表单 + 模型生成 → 可渲染、可校核的 IR。

关键取舍：
- 模型只负责「正文语义」，标题、主送、署名、日期等结构字段来自表单，不交给模型猜；
- 模型输出解析失败时退回骨架稿，并在 meta 里如实标注 generated_by，不冒充模型输出；
- 模型经 app.services.llm_chat 调用既有云端政务 API（与政策问答、文稿初稿生成同一客户端、配置与出口检查），
  绕开 llm_client 里的闲聊兜底逻辑（那些兜底会污染公文正文）；不使用本地模型。
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from typing import Any


from .checker import check, stats
from .schema import (
    DOC_TYPES,
    BodyPara,
    GongwenDoc,
    guess_level,
    normalize_body,
    summarize,
)

DEFAULT_TEMPERATURE = 0.35

SYSTEM_PROMPT = (
    "你是党政机关公文写作助手，熟悉《党政机关公文处理工作条例》和 GB/T 9704-2012。"
    "严格按用户指定的文种写作，语言庄重、简明、务实。"
    "只输出公文正文，不输出标题、不输出主送机关、不输出署名和日期、不输出任何解释或思考过程。"
)

#: 各文种在模型失效时的骨架标题（用来保证结构像公文，而不是一段空话）
FALLBACK_OUTLINE = {
    "通知": ["提高思想认识", "明确重点任务", "加强组织保障"],
    "请示": ["基本情况", "请示事项"],
    "报告": ["主要工作情况", "存在问题", "下一步工作安排"],
    "函": ["事项背景", "具体意见"],
    "纪要": ["会议基本情况", "议定事项"],
}

FALLBACK_ENDING = {
    "通知": "特此通知。",
    "请示": "以上请示，请批复。",
    "报告": "特此报告。",
    "函": "特此函告。",
    "纪要": "",
}

REPAIR_PROMPT = (
    "上一次输出只有标题、缺少正文内容。请保留已有的标题结构，在每个标题下面补充"
    "一个不少于 50 字的自然段，写清具体要求、责任主体和完成时限。"
    "仍然只输出正文，不要输出任何解释。"
)

_CN = "一二三四五六七八九十"


# ---------------------------------------------------------------- 配置

def _llm_settings() -> dict[str, Any]:
    from app.services import llm_chat

    return llm_chat.settings()


def _chat(messages: list[dict[str, str]], *, max_tokens: int | None = None,
          temperature: float = DEFAULT_TEMPERATURE) -> str:
    from app.services import llm_chat

    return llm_chat.chat(messages, max_tokens=max_tokens, temperature=temperature)


# ---------------------------------------------------------------- 文本清洗

def _strip_reasoning(text: str) -> str:
    text = re.sub(r"<think[^>]*>[\s\S]*?</think\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<think[^>]*>[\s\S]*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*(?:思考过程|推理过程)[:：][\s\S]*?\n\s*\n", "", text)
    return text.strip()


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _looks_like_meta_line(text: str, doc: GongwenDoc) -> bool:
    """过滤模型自作主张加上的标题、主送、署名、日期等行。"""
    t = text.strip()
    if not t:
        return True
    if doc.title and t.replace(" ", "") == doc.title.replace(" ", ""):
        return True
    if re.match(r"^(标题|主送机关|发文机关|成文日期|抄送|附件)\s*[:：]", t):
        return True
    if re.fullmatch(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", t):
        return True
    if t in {"正文", "公文正文", "以下是正文", "以下为正文",
             "日期", "成文日期", "署名", "发文机关署名", "盖章", "（盖章）"}:
        return True
    # 模型常把署名/机关名写进正文
    if doc.signer_org and t == doc.signer_org:
        return True
    if doc.issuer_org and t == doc.issuer_org:
        return True
    if re.fullmatch(r"[XxＸ×]{2,}[\u4e00-\u9fa5]{0,15}(局|厅|办公室|委员会|政府|部|院)", t):
        return True
    if re.fullmatch(r"[\u4e00-\u9fa5]{4,20}(局|厅|办公室|委员会|政府)", t):
        return True
    return False


def _parse_body(raw: str, doc: GongwenDoc) -> list[BodyPara]:
    """优先按 JSON 数组解析，失败则按行解析并按序号推断层级。"""
    text = _strip_fence(_strip_reasoning(raw or ""))
    if not text:
        return []

    if text[:1] in "[{":
        try:
            data = json.loads(text)
            items = data.get("body") if isinstance(data, dict) else data
            if isinstance(items, list):
                paras: list[BodyPara] = []
                for item in items:
                    if isinstance(item, dict):
                        body_text = str(item.get("text") or "").strip()
                        if not body_text or _looks_like_meta_line(body_text, doc):
                            continue
                        try:
                            level = int(item.get("level") or 0)
                        except (TypeError, ValueError):
                            level = guess_level(body_text)
                        paras.append(BodyPara(text=body_text, level=max(0, min(3, level))))
                    elif isinstance(item, str) and item.strip():
                        if _looks_like_meta_line(item, doc):
                            continue
                        paras.append(BodyPara(text=item.strip(), level=guess_level(item)))
                if paras:
                    return paras
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    paras = normalize_body(text.splitlines())
    return [p for p in paras if not _looks_like_meta_line(p.text, doc)]


# ---------------------------------------------------------------- 提示词

def _build_messages(payload: dict[str, Any], doc: GongwenDoc) -> list[dict[str, str]]:
    subject = str(payload.get("subject") or "").strip()
    extra = str(payload.get("extra") or "").strip()
    outline = FALLBACK_OUTLINE.get(doc.doc_type, [])
    ending = FALLBACK_ENDING.get(doc.doc_type, "")

    lines = [
        f"文种：{doc.doc_type}",
        f"事由：{subject or doc.title}",
    ]
    if doc.recipients:
        lines.append("主送机关：" + "、".join(doc.recipients))
    if doc.issuer_org:
        lines.append("发文机关：" + doc.issuer_org)
    if extra:
        lines.append("补充要求：" + extra)

    refs = payload.get("references") or []
    if isinstance(refs, list) and refs:
        lines.append("")
        lines.append("起草依据（只能引用下列条款，不得编造政策名称或文号）：")
        for i, ref in enumerate(refs[:6], start=1):
            if not isinstance(ref, dict):
                continue
            title = str(ref.get("policy_title") or "").strip()
            clause_no = str(ref.get("clause_no") or "").strip()
            doc_no = str(ref.get("doc_no") or "").strip()
            body = str(ref.get("content") or "").strip()
            head = f"[{i}] 《{title}》" + (f"{doc_no}" if doc_no else "") + (f" {clause_no}" if clause_no else "")
            lines.append(f"{head}：{body}")
        lines.append("正文中如需引用依据，写成「根据《政策名称》（文号）规定」的表述。")

    lines.append("写作要求：")
    lines.append("1. 只输出正文，每行一个自然段，不要输出标题、主送机关、署名、日期、任何说明。")
    lines.append("2. 一级标题用「一、二、三、」，二级标题用「（一）（二）」，三级用「1. 2.」，标题独占一行。")
    lines.append("3. 全文 400 至 800 字，每个自然段不超过 150 字，语言务实，不写空话。")
    lines.append("4. 每个标题下面必须写正文段落，不得只列标题；只列标题视为不合格。")
    if outline:
        lines.append("5. 主体围绕以下方面展开：" + "、".join(outline) + "。")
    if ending:
        lines.append(f"6. 最后一个自然段使用惯用结尾语「{ending}」。")
    lines.append("")
    lines.append("格式示例（仅示意结构，不要照抄内容）：")
    lines.append("为做好……工作，现就有关事项通知如下。")
    lines.append("一、……")
    lines.append("（一）……。这里写出具体要求、责任分工和时限。")
    lines.append(ending or "特此通知。")

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


_ENDING_TOKENS = ("特此通知。", "特此报告。", "特此函告。", "以上请示，请批复。", "妥否，请批示。")


def _clean_paras(paras: list[BodyPara]) -> list[BodyPara]:
    """清掉小模型常见的重复段落与重复结尾语。"""
    out: list[BodyPara] = []
    for para in paras:
        text = para.text.strip()
        if not text:
            continue
        if out and out[-1].text.strip() == text:
            continue
        if text in _ENDING_TOKENS:
            continue  # 结尾统一由 _ensure_ending 补
        out.append(para)
    return out


def _body_chars(paras: list[BodyPara]) -> int:
    return len("".join(p.text for p in paras))


def _too_thin(paras: list[BodyPara]) -> bool:
    """只有标题、没有实质正文，视为不合格输出。"""
    if not paras:
        return True
    if _body_chars(paras) < 150:
        return True
    substantive = [p for p in paras if p.level == 0 and not p.text.endswith(("特此通知。", "请批复。", "特此报告。", "特此函告。"))]
    return len(substantive) < 2


# ---------------------------------------------------------------- 兜底骨架

def _fallback_body(payload: dict[str, Any], doc: GongwenDoc) -> list[BodyPara]:
    """模型不可用时的骨架稿：结构正确、内容留白，明确标注为模板。"""
    subject = str(payload.get("subject") or doc.title or "本项工作").strip()
    outline = FALLBACK_OUTLINE.get(doc.doc_type, ["工作事项"])
    paras: list[BodyPara] = [
        BodyPara(f"为做好{subject}相关工作，根据有关部署要求，现就有关事项明确如下。", 0)
    ]
    for idx, title in enumerate(outline):
        num = _CN[idx] if idx < len(_CN) else str(idx + 1)
        paras.append(BodyPara(f"{num}、{title}", 1))
        paras.append(BodyPara(
            f"（此处补充「{title}」的具体内容：现状、要求、责任分工与完成时限。）", 0
        ))
    ending = FALLBACK_ENDING.get(doc.doc_type, "")
    if ending:
        paras.append(BodyPara(ending, 0))
    return paras


def _ensure_ending(paras: list[BodyPara], doc: GongwenDoc) -> list[BodyPara]:
    if not paras:
        return paras
    ending = FALLBACK_ENDING.get(doc.doc_type, "")
    if not ending:
        return paras
    tail = "".join(p.text for p in paras[-2:])
    if any(key in tail for key in ("特此通知", "请批复", "请批示", "特此报告", "特此函告", "请予函复", "妥否")):
        return paras
    return paras + [BodyPara(ending, 0)]


# ---------------------------------------------------------------- 字段推导

def _default_title(payload: dict[str, Any], doc_type: str) -> str:
    subject = str(payload.get("subject") or "").strip()
    issuer = str(payload.get("issuer_org") or "").strip()
    if not subject:
        return ""
    core = subject if subject.startswith("关于") else f"关于{subject}"
    core = core.rstrip("。.；;，,")
    title = f"{core}的{doc_type}"
    if issuer and not title.startswith(issuer):
        title = issuer + title
    return title


def _normalize_recipients(value: Any) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[、,，;；\n]+", value)
        return [p.strip() for p in parts if p.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def build_ir(payload: dict[str, Any]) -> GongwenDoc:
    """把前端表单装配成 IR（不含正文）。"""
    doc_type = str(payload.get("doc_type") or "通知").strip()
    if doc_type not in DOC_TYPES:
        doc_type = "通知"

    doc = GongwenDoc.from_dict({})
    doc.doc_type = doc_type
    doc.recipients = _normalize_recipients(payload.get("recipients"))
    doc.issuer_org = str(payload.get("issuer_org") or "").strip()
    doc.signer_org = str(payload.get("signer_org") or "").strip() or doc.issuer_org
    doc.sign_date = str(payload.get("sign_date") or "").strip() or date.today().strftime("%Y年%m月%d日").replace("年0", "年").replace("月0", "月")
    doc.title = str(payload.get("title") or "").strip() or _default_title(payload, doc_type)
    doc.doc_number = str(payload.get("doc_number") or "").strip()
    doc.secret_level = str(payload.get("secret_level") or "").strip()
    doc.urgency = str(payload.get("urgency") or "").strip()
    doc.copy_no = str(payload.get("copy_no") or "").strip()
    doc.signer_name = str(payload.get("signer_name") or "").strip()
    doc.attachments = _normalize_recipients(payload.get("attachments"))
    doc.cc = _normalize_recipients(payload.get("cc"))
    doc.note = str(payload.get("note") or "").strip()
    doc.print_org = str(payload.get("print_org") or "").strip()
    doc.print_date = str(payload.get("print_date") or "").strip()
    return doc


# ---------------------------------------------------------------- 对外入口

def draft(payload: dict[str, Any]) -> dict[str, Any]:
    """起草：生成正文 → 装配 IR → 校核。"""
    started = time.time()
    doc = build_ir(payload)

    generated_by = "llm"
    model = ""
    error = ""
    paras: list[BodyPara] = []

    try:
        conf = _llm_settings()
        model = conf["model"]
        messages = _build_messages(payload, doc)
        raw = _chat(messages)
        paras = _clean_paras(_parse_body(raw, doc))

        # 小模型常常只列标题，补一次正文
        if _too_thin(paras):
            retry_messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": REPAIR_PROMPT},
            ]
            repaired = _clean_paras(_parse_body(_chat(retry_messages), doc))
            if _body_chars(repaired) > _body_chars(paras):
                paras = repaired
                generated_by = "llm_repaired"
    except Exception as exc:  # 网络、超时、模型不可用都走骨架
        error = f"{type(exc).__name__}: {exc}"

    # 仍然只有标题、没有正文，就退回骨架稿，不把半成品当成品交付
    if _body_chars(paras) < 60 or _too_thin(paras):
        paras = _fallback_body(payload, doc)
        generated_by = "template"

    doc.body = _ensure_ending(paras, doc)

    issues = check(doc)
    return {
        "ir": doc.to_dict(),
        "issues": [i.to_dict() for i in issues],
        "stats": stats(issues),
        "summary": summarize(doc),
        "meta": {
            "generated_by": generated_by,
            "model": model,
            "error": error,
            "reference_count": len(payload.get("references") or []),
            "elapsed_ms": int((time.time() - started) * 1000),
        },
    }


def ir_from_payload(payload: dict[str, Any]) -> GongwenDoc:
    """从请求体取 IR：优先 ir 字段，其次按表单字段重建。"""
    ir = payload.get("ir")
    if isinstance(ir, dict) and ir:
        doc = GongwenDoc.from_dict(ir)
        if not doc.body:
            doc = build_ir(payload)
            doc.body = normalize_body(payload.get("body_text") or "")
        return doc

    doc = build_ir(payload)
    body_text = payload.get("body_text")
    if isinstance(body_text, str) and body_text.strip():
        doc.body = normalize_body(body_text)
    return doc
