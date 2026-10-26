"""Fixed, auditable tables for the 公文 review: rule codes, severities, error codes.

Two review layers produce ReviewIssue items (web/src/features/gov-office/types.ts):

- own rules (app.services.gongwen.rules): missing elements, numbering continuity,
  stated counts vs listed items, sign date, policy references. Severity is fixed
  per rule code in OWN_RULES below.
- gongwen-kit `check --json`: writing-rule checks. Severity comes from the tool's
  own per-hit classification (`blocking`), mapped by KIT_SEVERITY. The same kit
  rule can be blocking or a hint depending on context (e.g. 合计不符 in a table
  without a declared header row), so severity is never derived from the rule name.

Nothing here is guessed from titles or keywords.
"""
from __future__ import annotations

from dataclasses import dataclass

# Error codes. Kept in this module instead of app/errors.py, which another
# in-flight branch (policy retrieval) also edits.
ERR_GONGWEN_TOOL = 50300   # gongwen-kit / node unavailable or failed; detail in data.error.code
ERR_GATE = 40900           # formal action refused by the backend gate; detail in data.gate

# Tool error codes (data.error.code / formatCheck.errorCode).
TOOL_NODE_NOT_FOUND = "NODE_NOT_FOUND"
TOOL_KIT_NOT_FOUND = "KIT_NOT_FOUND"
TOOL_TIMEOUT = "TIMEOUT"
TOOL_BUSY = "BUSY"
TOOL_FAULT = "TOOL_FAULT"              # kit reported status=fault / exit 2
TOOL_BAD_OUTPUT = "BAD_OUTPUT"          # stdout is not the documented JSON
TOOL_INCONSISTENT = "INCONSISTENT"      # exit code, status and hits disagree
TOOL_INVALID_INPUT = "INVALID_INPUT"    # not an existing .docx
TOOL_RENDER_REJECTED = "RENDER_REJECTED"  # bridge refused the component spec
TOOL_RENDER_FAILED = "RENDER_FAILED"
TOOL_FIX_FAILED = "FIX_FAILED"

SEVERITIES = ("critical", "warning", "hint")


@dataclass(frozen=True)
class OwnRule:
    code: str
    title: str
    severity: str
    required_field: str | None = None


_OWN = [
    # 应有公文要素
    OwnRule("ELEM_TITLE", "缺少公文标题", "critical"),
    OwnRule("ELEM_ISSUER", "缺少发文机关", "critical", "issuer"),
    OwnRule("ELEM_RECIPIENT", "缺少主送机关", "critical", "recipient"),
    OwnRule("ELEM_DOCNO", "缺少发文字号", "critical"),
    OwnRule("ELEM_BODY", "缺少正文", "critical"),
    OwnRule("ELEM_SIGN_DATE", "缺少成文日期", "critical"),
    OwnRule("ELEM_BANJI", "缺少版记（印发机关和印发日期）", "critical"),
    OwnRule("ELEM_UNDERTAKER", "缺少承办部门", "warning", "undertaker"),
    OwnRule("TITLE_DOC_TYPE", "标题未体现文种", "warning"),
    OwnRule("TITLE_LINE_BREAK", "标题回行位置未指定", "hint"),
    # 成文日期与关键字段
    OwnRule("SIGN_DATE_FORMAT", "成文日期不完整或无法识别", "critical"),
    OwnRule("SIGN_DATE_INVALID", "成文日期不是有效日期", "critical"),
    OwnRule("BANJI_DATE_FORMAT", "印发日期不完整或无法识别", "warning"),
    # 层次序号
    OwnRule("NUMBERING_GAP", "层次序号不连续", "critical"),
    OwnRule("NUMBERING_LEVEL", "层次序号与标题层级不符", "warning"),
    # 数量描述
    OwnRule("COUNT_MISMATCH", "数量描述与实际列项不一致", "critical"),
    OwnRule("COUNT_MISMATCH_INLINE", "数量描述与分号列举条数不一致", "warning"),
    # 政策引用（有效性由政策库核验，本层不判断）
    OwnRule("POLICY_REF_UNLINKED", "引用的文件未关联政策依据", "warning"),
    OwnRule("POLICY_REF_UNCITED", "关联的政策依据未在正文引用", "hint"),
    OwnRule("POLICY_REF_UNVERIFIED", "政策有效性未经政策库核验", "hint"),
]
OWN_RULES: dict[str, OwnRule] = {r.code: r for r in _OWN}

# gongwen-kit 0.4.4 rule names (checks/check-doc.js, check-num.js, style-scan.js)
# → stable code. Unknown names still become issues (code GWK_UNMAPPED) and are logged.
KIT_RULE_CODES: dict[str, str] = {
    "样式重复": "GWK_STYLE_DUP",
    "文档无正文": "GWK_EMPTY",
    "段落序列化坏了": "GWK_SERIALIZE",
    "自称": "GWK_SELF_REF",
    "称对方": "GWK_OTHER_REF",
    "数字与单位": "GWK_NUM_UNIT",
    "数值范围": "GWK_NUM_RANGE",
    "纯小数": "GWK_DECIMAL",
    "年份简写": "GWK_YEAR_SHORT",
    "半角括号": "GWK_HALF_PAREN",
    "斜体": "GWK_ITALIC",
    "全角数字": "GWK_FULLWIDTH_DIGIT",
    "数位混用": "GWK_NUM_MIX",
    "日期简写": "GWK_DATE_SHORT",
    "日期顿号": "GWK_DATE_DUN",
    "表格同上": "GWK_TABLE_DITTO",
    "表格空格": "GWK_TABLE_EMPTY",
    "表格句号": "GWK_TABLE_PERIOD",
    "表头夹英文": "GWK_TABLE_HEAD_EN",
    "数值列非数值": "GWK_TABLE_NUMCOL",
    "标题重复编号": "GWK_HEADING_DUPNUM",
    "公文层次序数": "GWK_LEVEL_DOTTED",
    "中文数字日期": "GWK_DATE_CN",
    "月日编虚位": "GWK_DATE_PAD",
    "成文日期": "GWK_DATE_MONTH_ONLY",
    "发文字号": "GWK_DOCNO",
    "公文版式": "GWK_LAYOUT",
    "计数与列举": "GWK_ENUM_COUNT",
    "合计不符": "GWK_TOTAL",
    "跨表同值": "GWK_CROSS_TABLE",
    "正文与表格异值": "GWK_TEXT_TABLE_DIFF",
    "正文同指标异值": "GWK_TEXT_VALUE_DIFF",
    "百分比构成": "GWK_PERCENT",
    "异形词": "GWK_VARIANT_WORD",
    "中文里的半角标点": "GWK_HALF_PUNCT",
}
KIT_UNMAPPED = "GWK_UNMAPPED"

# Per-hit tool classification → ReviewIssue.severity. "warning" has no kit source.
KIT_SEVERITY = {True: "critical", False: "hint"}

# Overlapping kit rules: a hit of `suppressed` is dropped when a hit of `kept`
# exists and every fragment the suppressed hit lists is covered by `kept`
# (see review._dedupe_kit_hits). Measured: 「文书科(208室)」 is reported by both.
KIT_OVERLAPS = [
    {"kept": "半角括号", "suppressed": "中文里的半角标点", "chars": "()"},
]

# Fixed issue text shown when the format check could not run. A tool failure is
# never mapped to "pass".
FORMAT_CHECK_UNAVAILABLE = OwnRule("FORMAT_CHECK_UNAVAILABLE", "格式机检未完成", "critical")

COMPLIANCE_NOTE_FIX = (
    "fix 只调整版式（纸张、版心、行字网格、正文与层次样式、页码），体例写成修订痕迹、数字只加批注。"
    "修复后格式机检通过不代表符合 GB/T 9704 全部要求：标题、层次、列表、表格、落款、版头、版记"
    "必须人工核对；未接受的修订被拒绝后，问题会重新出现。"
)
