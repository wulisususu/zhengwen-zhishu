"""公文校核规则。

分两层：
1. 结构层（schema.validate）：文种、主送、日期、发文字号等字段级问题
2. 内容层（本模块）：序号连续性、结尾用语、模糊时间、标点、段长等写作问题

校核结果不改动文档，只给出定位与建议——改动权始终在人手上。
"""
from __future__ import annotations

import re

from .schema import GongwenDoc, Issue, validate

_CN_NUM = "一二三四五六七八九十"

#: 各文种的惯用结尾语
ENDING_HINTS = {
    "通知": ("特此通知", "请遵照执行", "请认真贯彻执行", "请抓好落实"),
    "请示": ("请批复", "请批示", "妥否", "请予批准"),
    "报告": ("特此报告", "专此报告", "请审阅"),
    "函": ("特此函告", "请予函复", "盼复", "此复"),
    "纪要": ("",),
}

_RE_HALF_PAREN = re.compile(r"\([一二三四五六七八九十]+\)")
_RE_VAGUE_TIME = re.compile(r"(今年|去年|明年|上个月|本月|下个月|近期|日前)")
_RE_DUP_PUNCT = re.compile(r"([，。、；：])\1")
_RE_SALUTATION = re.compile(r"(贵单位|贵局|你单位|你局|我单位|我局)")


def _check_heading_sequence(doc: GongwenDoc) -> list[Issue]:
    issues: list[Issue] = []
    level1 = [p.text.strip() for p in doc.body if p.level == 1]
    if len(level1) < 2:
        return issues

    numbers: list[int] = []
    for text in level1:
        head = text[0] if text else ""
        if head in _CN_NUM:
            numbers.append(_CN_NUM.index(head) + 1)

    if len(numbers) != len(level1):
        return issues

    for idx, num in enumerate(numbers):
        if num != idx + 1:
            issues.append(Issue(
                "heading.sequence", "warn",
                f"一级标题序号不连续：第 {idx + 1} 个标题为「{_CN_NUM[num - 1] if 1 <= num <= 10 else num}、」",
                "一级标题应按「一、二、三、」顺序排列，不跳号、不重复",
            ))
            break
    return issues


def _check_ending(doc: GongwenDoc) -> list[Issue]:
    if not doc.body:
        return []
    hints = ENDING_HINTS.get(doc.doc_type, ())
    if not hints or not any(hints):
        return []
    tail = "".join(p.text for p in doc.body[-2:])
    if any(h in tail for h in hints if h):
        return []
    return [Issue(
        "ending.missing", "info",
        f"{doc.doc_type}的结尾未使用惯用语",
        "可用：" + " / ".join(h for h in hints if h),
    )]


def _check_wording(doc: GongwenDoc) -> list[Issue]:
    issues: list[Issue] = []
    text = "".join(p.text for p in doc.body)

    half = _RE_HALF_PAREN.findall(text)
    if half:
        issues.append(Issue(
            "punct.half_width_paren", "warn",
            f"出现半角括号序号 {len(half)} 处，如「{half[0]}」",
            "公文中的层级序号应使用全角括号「（一）」",
        ))

    vague = sorted(set(_RE_VAGUE_TIME.findall(text)))
    if vague:
        issues.append(Issue(
            "wording.vague_time", "warn",
            "出现模糊时间表述：" + "、".join(vague),
            "公文中时间应写明年份，避免「今年」「去年」等随文种时效失效的表述",
        ))

    dup = _RE_DUP_PUNCT.search(text)
    if dup:
        issues.append(Issue("punct.duplicated", "warn",
                            f"出现重复标点「{dup.group(0)}」", "核对标点使用"))

    salutations = sorted(set(_RE_SALUTATION.findall(text)))
    if len(salutations) > 1:
        issues.append(Issue(
            "wording.salutation_mixed", "info",
            "称谓混用：" + "、".join(salutations),
            "全文对受文机关的称谓应保持一致",
        ))

    long_paras = [p for p in doc.body if len(p.text) > 400]
    if long_paras:
        issues.append(Issue(
            "body.paragraph_too_long", "info",
            f"有 {len(long_paras)} 个段落超过 400 字",
            "建议拆分为「一、二、」分条，便于执行和引用",
        ))

    if doc.title and doc.doc_type and not doc.title.rstrip("）)").endswith(doc.doc_type):
        issues.append(Issue(
            "title.doc_type_mismatch", "warn",
            f"标题未以文种「{doc.doc_type}」结尾",
            "公文标题一般由发文机关、事由和文种三部分组成，文种置于最后",
        ))
    return issues


def check(doc: GongwenDoc) -> list[Issue]:
    """结构层 + 内容层全部规则。"""
    issues = validate(doc)
    issues = [i for i in issues if i.code != "ok"]
    issues.extend(_check_heading_sequence(doc))
    issues.extend(_check_ending(doc))
    issues.extend(_check_wording(doc))

    order = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda i: order.get(i.level, 9))
    if not issues:
        issues.append(Issue("ok", "info", "未发现格式与写作问题", ""))
    return issues


def stats(issues: list[Issue]) -> dict[str, int]:
    return {
        "error": sum(1 for i in issues if i.level == "error"),
        "warn": sum(1 for i in issues if i.level == "warn"),
        "info": sum(1 for i in issues if i.level == "info"),
    }
