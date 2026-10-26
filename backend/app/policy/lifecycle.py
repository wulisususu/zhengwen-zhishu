"""政策状态与日期：日期解析与展示、状态是否可作现行依据。

状态以既有政策库（T1）的人工核验结果为准，再按生效 / 失效日期纠偏（见 corpus.effective_status）；
本模块不推导、也不放宽状态。
"""
from __future__ import annotations

import re
from datetime import date

from .models import BASIS_STATUSES

_RE_DATE = re.compile(r"(\d{4})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})")
_RE_YM = re.compile(r"(\d{4})\s*[年\-/.]\s*(\d{1,2})")


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


def is_basis_eligible(status: str) -> bool:
    """是否可以作为「现行依据」引用。"""
    return status in BASIS_STATUSES


def status_label(status: str) -> str:
    return status or "待核实"
