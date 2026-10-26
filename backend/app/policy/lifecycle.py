"""政策生命周期：日期归一、状态推导、元数据体检。

状态不是人工随便填的标签，而是可以由「生效/失效日期 + 替代关系」推出来的结论。
人工填写的状态优先，但会和日期打架时给出告警，避免出现「已废止却当作现行依据」。
"""
from __future__ import annotations

import re
from datetime import date

from .models import ALL_STATUSES, BASIS_STATUSES, STATUS_EFFECTIVE, STATUS_PENDING, STATUS_REPEALED

_RE_DATE = re.compile(r"(\d{4})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})")
_RE_YM = re.compile(r"(\d{4})\s*[年\-/.]\s*(\d{1,2})")


#: 示例/占位域名：演示数据常填这些，点开必然打不开，不能当有效来源
_PLACEHOLDER_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "example.com", "example.org",
                      "example.net", "example.gov.cn", "test.gov.cn", "demo.gov.cn"}


def normalize_source_url(raw: str | None) -> tuple[str, str]:
    """校验来源链接，返回 (可用链接, 丢弃原因)。

    政务引用必须能回到官方原文，所以这条链路宁可为空也不能填假地址 ——
    界面上给出一个点开是「无法访问此页面」的链接，比不显示更糟。
    """
    url = (raw or "").strip()
    if not url:
        return "", ""

    if not re.match(r"^https?://", url, re.I):
        return "", "来源链接需以 http:// 或 https:// 开头，已清空"

    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if not host or "." not in host:
        return "", "来源链接域名无法解析，已清空"
    if host in _PLACEHOLDER_HOSTS or host.startswith("example.") or host.endswith(".example.com"):
        return "", "来源链接为示例/占位域名，无法访问，已清空（请填官方原文地址）"
    return url, ""


def parse_date(text: str | None) -> date | None:
    """支持「2026年3月1日」「2026-03-01」「2026/3/1」「2026.03.01」「20260301」。"""
    if not text:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    m = _RE_DATE.search(raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _RE_YM.search(raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return None
    if re.fullmatch(r"\d{8}", raw):
        try:
            return date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
        except ValueError:
            return None
    return None


def normalize_date(text: str | None) -> str:
    d = parse_date(text)
    return d.isoformat() if d else ""


def display_date(value: str | None) -> str:
    """把 YYYY-MM-DD 显示成「2026年3月1日」。"""
    d = parse_date(value)
    return f"{d.year}年{d.month}月{d.day}日" if d else (value or "")


def derive_status(effective: str = "", expire: str = "", explicit: str = "",
                  superseded_by: str = "", today: date | None = None) -> str:
    """推导政策状态。显式状态优先，但会按日期纠偏。"""
    today = today or date.today()
    eff = parse_date(effective)
    exp = parse_date(expire)

    if explicit and explicit in ALL_STATUSES:
        # 已过期却标成现行有效：以日期为准
        if explicit == STATUS_EFFECTIVE and exp and exp < today:
            return STATUS_REPEALED
        return explicit

    if exp and exp < today:
        return STATUS_REPEALED
    if eff and eff > today:
        return "尚未生效"
    if superseded_by:
        return "已修订"
    return STATUS_EFFECTIVE


def is_basis_eligible(status: str) -> bool:
    """是否可以作为「现行依据」引用。"""
    return status in BASIS_STATUSES


def status_label(status: str) -> str:
    return status or "待核实"


def lifecycle_issues(doc) -> list[dict]:
    """元数据体检，返回 [{level, code, message}]。level: error / warn / info。"""
    issues: list[dict] = []

    if not doc.doc_no:
        issues.append({"level": "warn", "code": "doc_no.missing",
                       "message": "未填写文号，引用时无法唯一指认该文件"})
    if not doc.issuer:
        issues.append({"level": "warn", "code": "issuer.missing",
                       "message": "未填写发文机关"})
    if not doc.publish_date:
        issues.append({"level": "info", "code": "publish_date.missing",
                       "message": "未填写发布日期"})
    if not doc.source_url:
        issues.append({"level": "info", "code": "source_url.missing",
                       "message": "未记录原始来源链接，结论无法回溯到官方原文"})

    eff = parse_date(doc.effective_date)
    exp = parse_date(doc.expire_date)
    pub = parse_date(doc.publish_date)

    if eff and exp and exp < eff:
        issues.append({"level": "error", "code": "date.expire_before_effective",
                       "message": f"失效日期（{doc.expire_date}）早于生效日期（{doc.effective_date}）"})
    if pub and eff and eff < pub:
        issues.append({"level": "warn", "code": "date.effective_before_publish",
                       "message": "生效日期早于发布日期，请核对是否「自发布之日起施行」"})
    if doc.status == STATUS_REPEALED and not doc.superseded_by:
        issues.append({"level": "warn", "code": "repealed.no_successor",
                       "message": "已废止但未注明替代文件，检索时无法导向现行规定"})
    if doc.status == STATUS_PENDING:
        issues.append({"level": "warn", "code": "status.pending",
                       "message": "状态待核实，系统不会将其作为现行依据"})
    if doc.supersedes and doc.superseded_by:
        issues.append({"level": "info", "code": "relation.both_sides",
                       "message": "同时登记了「替代旧文件」与「被新文件替代」，请确认是否存在版本链冲突"})
    return issues


def describe_relation(doc) -> str:
    """给前端展示的关系描述。"""
    parts: list[str] = []
    if doc.supersedes:
        parts.append(f"替代：{doc.supersedes}")
    if doc.superseded_by:
        parts.append(f"被替代：{doc.superseded_by}")
    if doc.revision_of:
        parts.append(f"修订自：{doc.revision_of}")
    if doc.version:
        parts.append(f"版本：{doc.version}")
    return "；".join(parts)
