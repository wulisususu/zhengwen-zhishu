"""公文结构化中间表示（IR）与字段校验。

设计原则：模型只负责「内容语义」，版式由 renderer 按 GB/T 9704-2012 确定性渲染。
模型输出不稳定时，IR 仍然是一个可校验、可编辑、可复现的结构，而不是一段 Markdown。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------- 文种

DOC_TYPES = ("通知", "请示", "报告", "函", "纪要")

#: 上行文（需要标注签发人）
UPWARD_DOC_TYPES = ("请示", "报告")

#: 必须填写主送机关的文种
NEED_RECIPIENT = ("通知", "请示", "报告", "函")

# ---------------------------------------------------------------- 版式常量
# 依据 GB/T 9704-2012《党政机关公文格式》
PAGE_WIDTH_MM = 210
PAGE_HEIGHT_MM = 297
MARGIN_TOP_MM = 37
MARGIN_BOTTOM_MM = 35
MARGIN_LEFT_MM = 28
MARGIN_RIGHT_MM = 26

FONT_DISPLAY = "方正小标宋简体"   # 发文机关标志、标题
FONT_BODY = "仿宋_GB2312"        # 正文
FONT_H1 = "黑体"                 # 一级标题「一、」
FONT_H2 = "楷体_GB2312"          # 二级标题「（一）」
FONT_PAGE_NO = "宋体"            # 页码

SIZE_ER = 22        # 2 号
SIZE_SAN = 16       # 3 号
SIZE_SI = 14        # 4 号

LINE_SPACING_PT = 28.8   # 每面 22 行对应的固定行距

SECRET_LEVELS = ("", "公开", "内部", "秘密", "机密")
URGENCY_LEVELS = ("", "普通", "急件", "特急")


# ---------------------------------------------------------------- 数据结构

@dataclass
class BodyPara:
    """正文段落。level: 0 普通段落 / 1 一级标题（一、）/ 2 二级标题（（一））/ 3 三级标题（1.）"""

    text: str
    level: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "level": self.level}


@dataclass
class GongwenDoc:
    """一份公文的完整结构化表示。字段与版式位置一一对应。"""

    doc_type: str = "通知"
    title: str = ""
    recipients: list[str] = field(default_factory=list)

    issuer_org: str = ""      # 发文机关全称（红头用，渲染为「XXX文件」）
    signer_org: str = ""      # 发文机关署名
    sign_date: str = ""       # 成文日期，如 2026年10月24日

    body: list[BodyPara] = field(default_factory=list)

    doc_number: str = ""      # 发文字号，如 X政服发〔2026〕12号
    secret_level: str = ""    # 密级
    urgency: str = ""         # 紧急程度
    copy_no: str = ""         # 份号（6 位数字）
    signer_name: str = ""     # 签发人（上行文）

    attachments: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)       # 抄送机关
    note: str = ""                                    # 附注
    keywords: list[str] = field(default_factory=list)  # 主题词（部分机关仍用）

    print_org: str = ""       # 印发机关
    print_date: str = ""      # 印发日期

    # ---------------- 序列化 ----------------

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["body"] = [p.to_dict() if isinstance(p, BodyPara) else p for p in self.body]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "GongwenDoc":
        """容错解析：字段缺失、类型不符、body 是字符串等情况都不抛异常。"""
        if not isinstance(data, dict):
            return cls()

        def as_text(key: str) -> str:
            value = data.get(key)
            return "" if value is None else str(value).strip()

        def as_list(key: str) -> list[str]:
            value = data.get(key)
            if value is None or value == "":
                return []
            if isinstance(value, str):
                parts = re.split(r"[、,，;；\n]+", value)
                return [p.strip() for p in parts if p.strip()]
            if isinstance(value, (list, tuple)):
                return [str(p).strip() for p in value if str(p).strip()]
            return [str(value).strip()]

        raw_body = data.get("body") or []
        body: list[BodyPara] = []
        if isinstance(raw_body, str):
            body = normalize_body(raw_body.splitlines())
        elif isinstance(raw_body, (list, tuple)):
            for item in raw_body:
                if isinstance(item, dict):
                    text = str(item.get("text") or item.get("content") or "").strip()
                    if not text:
                        continue
                    try:
                        level = int(item.get("level") or 0)
                    except (TypeError, ValueError):
                        level = 0
                    body.append(BodyPara(text=text, level=max(0, min(3, level))))
                elif isinstance(item, str) and item.strip():
                    body.append(BodyPara(text=item.strip(), level=guess_level(item)))

        return cls(
            doc_type=as_text("doc_type") or "通知",
            title=as_text("title"),
            recipients=as_list("recipients"),
            issuer_org=as_text("issuer_org"),
            signer_org=as_text("signer_org"),
            sign_date=as_text("sign_date"),
            body=body,
            doc_number=as_text("doc_number"),
            secret_level=as_text("secret_level"),
            urgency=as_text("urgency"),
            copy_no=as_text("copy_no"),
            signer_name=as_text("signer_name"),
            attachments=as_list("attachments"),
            cc=as_list("cc"),
            note=as_text("note"),
            keywords=as_list("keywords"),
            print_org=as_text("print_org"),
            print_date=as_text("print_date"),
        )


# ---------------------------------------------------------------- 段落层级识别

_RE_H1 = re.compile(r"^[一二三四五六七八九十]+\s*[、.．]")
_RE_H2 = re.compile(r"^[（(][一二三四五六七八九十]+[)）]")
_RE_H3 = re.compile(r"^\d+\s*[.．、](?!\d)")
_RE_ATTACH = re.compile(r"^附件\s*[:：]")


def guess_level(text: str) -> int:
    """根据序号前缀推断段落层级。用于模型没给 level 时的兜底。"""
    t = (text or "").strip()
    if _RE_H1.match(t):
        return 1
    if _RE_H2.match(t):
        return 2
    if _RE_H3.match(t):
        return 3
    return 0


def is_attachment_line(text: str) -> bool:
    return bool(_RE_ATTACH.match((text or "").strip()))


def normalize_body(lines: list[str] | str) -> list[BodyPara]:
    """把纯文本切成段落：去空行、去 Markdown 装饰、按前缀推断层级。"""
    if isinstance(lines, str):
        lines = lines.splitlines()
    result: list[BodyPara] = []
    for raw in lines:
        text = (raw or "").strip()
        if not text:
            continue
        # 去掉模型爱加的 Markdown 标记
        text = re.sub(r"^#{1,6}\s*", "", text)
        text = re.sub(r"^\*\*(.+?)\*\*$", r"\1", text)
        text = text.strip("　 ")
        if not text:
            continue
        result.append(BodyPara(text=text, level=guess_level(text)))
    return result


# ---------------------------------------------------------------- 校验

@dataclass
class Issue:
    code: str
    level: str      # error / warn / info
    message: str
    hint: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "level": self.level, "message": self.message, "hint": self.hint}


_RE_DATE = re.compile(r"^\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日$")
_RE_DOC_NUMBER = re.compile(r"^[^\s〔〕]+\〔\d{4}\〕\d+号$")
_RE_PUNCT_IN_TITLE = re.compile(r"[，。；！？,;!?]")
_RE_REQUEST_IN_REPORT = re.compile(r"(请批复|请批准|请予批准|妥否|当否|请批示)")


def validate(doc: GongwenDoc) -> list[Issue]:
    """返回全部问题，按 error → warn → info 排序。"""
    issues: list[Issue] = []

    if doc.doc_type not in DOC_TYPES:
        issues.append(Issue("doc_type.unknown", "error",
                            f"文种「{doc.doc_type}」不在支持范围内",
                            "支持：" + "、".join(DOC_TYPES)))

    if not doc.title.strip():
        issues.append(Issue("title.empty", "error", "标题为空", "标题应包含发文机关、事由和文种"))
    else:
        if _RE_PUNCT_IN_TITLE.search(doc.title):
            issues.append(Issue("title.punctuation", "warn",
                                "标题中出现逗号、句号等标点",
                                "公文标题除法规规章名称加书名号外，一般不用标点符号"))
        if len(doc.title) > 60:
            issues.append(Issue("title.too_long", "warn",
                                f"标题 {len(doc.title)} 字，偏长",
                                "建议压缩事由，控制在 50 字以内"))

    if not doc.body:
        issues.append(Issue("body.empty", "error", "正文为空", "至少需要一段正文内容"))

    if doc.doc_type in NEED_RECIPIENT:
        if not doc.recipients:
            issues.append(Issue("recipients.empty", "error",
                                f"{doc.doc_type}缺少主送机关", "主送机关写在标题下空一行、左侧顶格"))
        elif doc.doc_type == "请示" and len(doc.recipients) > 1:
            issues.append(Issue("recipients.multiple_in_request", "error",
                                "请示的主送机关多于一个",
                                "请示应当一文一事、主送一个机关，不得多头主送"))

    if doc.doc_type == "请示":
        has_request = any("请示" in p.text or "报请" in p.text for p in doc.body)
        if doc.body and not has_request:
            issues.append(Issue("body.no_request_sentence", "warn",
                                "请示正文中未出现明确的请示事项表述",
                                "结尾应有「以上请示，请批复」一类明确请求"))

    if doc.doc_type == "报告" and any(_RE_REQUEST_IN_REPORT.search(p.text) for p in doc.body):
        issues.append(Issue("body.request_in_report", "error",
                            "报告中夹带了请示事项",
                            "报告中不得夹带请示事项；需要上级批复的应另行文种为「请示」"))

    if doc.doc_type == "纪要" and doc.recipients:
        issues.append(Issue("recipients.in_minutes", "info",
                            "会议纪要一般不加主送机关",
                            "纪要通常只写报送和印发范围，如需可写入抄送"))

    if doc.sign_date and not _RE_DATE.match(doc.sign_date):
        issues.append(Issue("sign_date.format", "warn",
                            f"成文日期「{doc.sign_date}」格式不规范",
                            "应写作「2026年10月24日」，用阿拉伯数字，不补零"))
    elif not doc.sign_date:
        issues.append(Issue("sign_date.empty", "warn", "成文日期为空", "成文日期位于署名下一行、右空四字"))

    if doc.doc_number and not _RE_DOC_NUMBER.match(doc.doc_number):
        issues.append(Issue("doc_number.format", "warn",
                            f"发文字号「{doc.doc_number}」格式不规范",
                            "格式应为「机关代字〔年份〕序号号」，年份用六角括号〔〕"))

    if doc.doc_type in UPWARD_DOC_TYPES and not doc.signer_name:
        issues.append(Issue("signer.missing", "info",
                            f"{doc.doc_type}属上行文，建议标注签发人",
                            "上行文在发文字号右侧标注「签发人：姓名」"))

    if not doc.signer_org:
        issues.append(Issue("signer_org.empty", "warn", "发文机关署名为空", "署名位于正文下空一行、右空二字"))

    body_text = "".join(p.text for p in doc.body)
    if "附件" in body_text and not doc.attachments and not any(is_attachment_line(p.text) for p in doc.body):
        issues.append(Issue("attachment.missing", "warn",
                            "正文提到「附件」但未提供附件说明",
                            "在正文下空一行、左空二字写「附件：1. XXX」"))

    if not doc.issuer_org:
        issues.append(Issue("issuer_org.empty", "info", "未填写发文机关，红头将不显示", "红头为「发文机关全称 + 文件」"))

    order = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda i: order.get(i.level, 9))
    if not issues:
        issues.append(Issue("ok", "info", "未发现格式问题", ""))
    return issues


def summarize(doc: GongwenDoc) -> dict[str, Any]:
    """给前端用的统计信息。"""
    text = "".join(p.text for p in doc.body)
    return {
        "doc_type": doc.doc_type,
        "paragraph_count": len(doc.body),
        "char_count": len(re.sub(r"\s", "", text)),
        "heading_count": sum(1 for p in doc.body if p.level > 0),
    }
