"""Two-layer 公文 review and the backend gate.

Layer 1: own deterministic rules (rules.py) on the structured draft.
Layer 2: gongwen-kit `check --json` on the DOCX that gongwen-kit renders from the
same draft; each hit is mapped back to a draft id through the converter's text index.

Output issues have exactly the ReviewIssue keys of web/src/features/gov-office/types.ts.
Everything the frontend type has no field for (rule code, layer, anchor precision,
kit classification, merged duplicates) goes to `issueDetails[issue.id]`.
`suggestion` is never set: neither layer produces a segment-level replacement.
"""
from __future__ import annotations

import hashlib
import logging
import re
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.services.gongwen import catalog, rules
from app.services.gongwen.bridge import render_docx
from app.services.gongwen.checker import KitHit, check_docx
from app.services.gongwen.converter import IndexEntry, build_spec
from app.services.gongwen.runner import GongwenToolError
from app.services.gongwen.schema import Block, NoticeDraft, TextSegment
from app.services.gongwen.settings import GongwenSettings

logger = logging.getLogger("app.gongwen")

REVIEW_ISSUE_KEYS = ("id", "severity", "source", "title", "description", "locationLabel",
                     "anchor", "section", "suggestion", "requiredField")
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "hint": 2}
DRAFT_MARK = "内部草稿 · 未审核 · 不得作为正式公文使用"


def _short_hash(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:10]


# ── layer 1 → ReviewIssue ─────────────────────────────────────────────────
def issue_from_finding(f: rules.Finding) -> tuple[dict, dict]:
    rule = catalog.OWN_RULES[f.code]
    issue = {
        "id": f"own-{f.code.lower()}-{_short_hash(f.code, f.anchor, f.description)}",
        "severity": rule.severity, "source": "rule", "title": rule.title,
        "description": f.description, "locationLabel": f.location_label,
        "anchor": f.anchor, "section": f.section,
    }
    if rule.required_field:
        issue["requiredField"] = rule.required_field
    return issue, {"code": f.code, "layer": "own", "anchorPrecision": f.precision, **f.extra}


# ── layer 2 → ReviewIssue ─────────────────────────────────────────────────
_ASCII_PUNCT = set(",.!?;:()")


def _listed_fragments(detail: str) -> list[str] | None:
    """Fragments listed by 中文里的半角标点: 「… N 处（科(、室)）。…」. None if unparsable/truncated."""
    m = re.match(r"^\S+ (\d+) 处（(.*?)）。", detail)
    if not m:
        return None
    frags = [x for x in m.group(2).split("、") if x]
    return frags if frags and len(frags) < 6 else None   # the tool lists at most 6 unique ones


def dedupe_kit_hits(hits: list[KitHit]) -> list[tuple[KitHit, list[str]]]:
    """Drop exact duplicates and the measured overlaps in catalog.KIT_OVERLAPS."""
    kept: list[tuple[KitHit, list[str]]] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        if (hit.rule, hit.detail) in seen:
            continue
        seen.add((hit.rule, hit.detail))
        kept.append((hit, []))
    for overlap in catalog.KIT_OVERLAPS:
        owners = [k for k in kept if k[0].rule == overlap["kept"]]
        if not owners:
            continue
        for item in list(kept):
            hit = item[0]
            if hit.rule != overlap["suppressed"]:
                continue
            frags = _listed_fragments(hit.detail)
            if frags and all({c for c in f if c in _ASCII_PUNCT} <= set(overlap["chars"]) for f in frags):
                kept.remove(item)
                owners[0][1].append(hit.rule)
    return kept


def _in_table(hit: KitHit) -> bool:
    """The kit marks table anchors as {"text", "table"}; such fragments are only searched in tables."""
    return any(isinstance(a, dict) and "table" in a for a in hit.anchors)


def _fragments(hit: KitHit) -> list[str]:
    out = []
    for a in hit.anchors:
        text = a if isinstance(a, str) else (a.get("text") if isinstance(a, dict) else None)
        if isinstance(text, str) and text.strip():
            out.append(text)
    if out:
        return out
    # check-style hits carry no anchors; their detail lists the fragments instead:
    # 「中文里的半角标点 1 处（求,）。…」「异形词 1 处（GF 1001-2001）：筹画 → 筹划」
    listed = _listed_fragments(hit.detail)
    if listed:
        return listed
    m = re.search(r"：(.+)$", hit.detail)
    if hit.rule == "异形词" and m:
        return [part.split("→")[0].strip() for part in m.group(1).split("、") if "→" in part]
    return []


def _locate(fragments: list[str], index: list[IndexEntry], in_table: bool = False) -> tuple[IndexEntry | None, list[str]]:
    if in_table:
        index = [e for e in index if e.is_table]
    for frag in fragments:
        for precision in ("segment", "block"):
            found = [e for e in index if e.precision == precision and e.anchor and frag in e.text]
            if found:
                return found[0], sorted({e.anchor for e in found})
        unanchored = [e for e in index if frag in e.text]
        if unanchored:
            return unanchored[0], []
    return None, []


def issue_from_kit_hit(hit: KitHit, merged: list[str], index: list[IndexEntry]) -> tuple[dict, dict]:
    code = catalog.KIT_RULE_CODES.get(hit.rule, catalog.KIT_UNMAPPED)
    if code == catalog.KIT_UNMAPPED:
        logger.warning("gongwen-kit rule not in catalog: %s", hit.rule)
    fragments = _fragments(hit)
    in_table = _in_table(hit)
    entry, candidates = _locate(fragments, index, in_table)
    if entry is None:
        anchor, precision, section, label = "", "none", "document", "表格" if in_table else "全文"
    else:
        anchor, precision, section, label = entry.anchor, entry.precision if entry.anchor else "none", entry.section, entry.label
    if anchor and len(candidates) > 1:
        precision = "text_snippet_ambiguous"
    issue = {
        "id": f"gwk-{_short_hash(hit.rule, hit.detail, anchor)}",
        "severity": catalog.KIT_SEVERITY[hit.blocking], "source": "rule",
        "title": hit.rule, "description": hit.detail, "locationLabel": label,
        "anchor": anchor, "section": section,
    }
    detail = {"code": code, "layer": "gongwen-kit", "check": hit.check, "ruleName": hit.rule,
              "blocking": hit.blocking, "anchorPrecision": precision, "fragments": fragments}
    if len(candidates) > 1:
        detail["candidates"] = candidates
    if merged:
        detail["mergedRules"] = merged
    return issue, detail


# ── gate ──────────────────────────────────────────────────────────────────
def evaluate_gate(issues: list[dict], format_check_ok: bool) -> dict:
    critical = [i["id"] for i in issues if i["severity"] == "critical"]
    reasons = []
    if not format_check_ok:
        reasons.append("格式机检未完成，不能判定通过")
    if critical:
        reasons.append(f"存在 {len(critical)} 个严重问题，须先修改（严重问题的例外审批尚未接入后端）")
    return {
        "canSubmit": True,
        "canExportInternalDraft": True,
        "canApprove": format_check_ok and not critical,
        "canExportFormal": False,
        "blockingIssueIds": critical,
        "reasons": reasons,
        "formalExportReasons": reasons + ["正式导出需要审批记录与正式发文权限，后端审批流程尚未接入"],
    }


def _finish(issues_with_details: list[tuple[dict, dict]], format_check: dict, extra: dict) -> dict:
    by_id: dict[str, tuple[dict, dict]] = {}
    for issue, detail in issues_with_details:
        by_id.setdefault(issue["id"], (issue, detail))
    ordered = sorted(by_id.values(), key=lambda p: _SEVERITY_ORDER[p[0]["severity"]])
    issues = [i for i, _ in ordered]
    summary = {s: sum(1 for i in issues if i["severity"] == s) for s in catalog.SEVERITIES}
    return {
        "origin": "backend",
        "reviewedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "issues": issues,
        "issueDetails": {i["id"]: d for i, d in ordered},
        "formatCheck": format_check,
        "summary": summary,
        "gate": evaluate_gate(issues, format_check["status"] in ("pass", "hit")),
        **extra,
    }


def _kit_layer(docx: Path, index: list[IndexEntry], settings: GongwenSettings) -> tuple[list, dict]:
    result = check_docx(docx, settings)
    if not result["success"]:
        err = result["error"] or {"code": catalog.TOOL_FAULT, "message": "未知错误"}
        return _unavailable(err), {"status": "unavailable", "errorCode": err["code"], "message": err["message"]}
    hits = [KitHit(**h) for h in result["hits"]]
    pairs = [issue_from_kit_hit(h, merged, index) for h, merged in dedupe_kit_hits(hits)]
    return pairs, {
        "status": result["status"], "toolVersion": result["tool_version"], "sha256": result["sha256"],
        "seconds": result["seconds"], "hitCount": len(hits),
        "blockingCount": sum(1 for h in hits if h.blocking), "hintCount": sum(1 for h in hits if not h.blocking),
    }


def _unavailable(err: dict) -> list[tuple[dict, dict]]:
    rule = catalog.FORMAT_CHECK_UNAVAILABLE
    issue = {"id": f"own-{rule.code.lower()}", "severity": rule.severity, "source": "rule", "title": rule.title,
             "description": f"格式机检没能完成（{err['code']}：{err['message']}），本次不能判定格式通过。",
             "locationLabel": "全文", "anchor": "", "section": "document"}
    return [(issue, {"code": rule.code, "layer": "gongwen-kit", "anchorPrecision": "none", "toolError": err["code"]})]


# ── entry points ──────────────────────────────────────────────────────────
def review_notice(draft: NoticeDraft, settings: GongwenSettings) -> dict:
    start = time.monotonic()
    findings, verification = rules.run_all(draft)
    pairs = [issue_from_finding(f) for f in findings]
    spec, index = build_spec(draft)
    with tempfile.TemporaryDirectory(prefix="gongwen-review-") as tmp:
        out = Path(tmp) / "notice.docx"
        try:
            render_docx(spec, out, settings)
            kit_pairs, format_check = _kit_layer(out, index, settings)
        except GongwenToolError as exc:
            kit_pairs, format_check = _unavailable(exc.to_dict()), {
                "status": "unavailable", "errorCode": exc.code, "message": exc.message}
    result = _finish(pairs + kit_pairs, format_check, {"docType": "notice", "policyVerification": verification})
    logger.info("gongwen review notice blocks=%d seconds=%.3f critical=%d warning=%d hint=%d format=%s",
                len(draft.blocks), time.monotonic() - start, result["summary"]["critical"],
                result["summary"]["warning"], result["summary"]["hint"], format_check["status"])
    return result


def render_notice(draft: NoticeDraft, out: Path, settings: GongwenSettings, internal_draft: bool) -> dict:
    spec, _ = build_spec(draft, DRAFT_MARK if internal_draft else None)
    return render_docx(spec, out, settings)


# External DOCX: kit check + the text-level own rules (numbering, counts).
# Element rules need the structured fields and are not applied here.
_P_RE = re.compile(r"<w:p[ >].*?</w:p>", re.S)
_T_RE = re.compile(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>")
_ENTITIES = {"&lt;": "<", "&gt;": ">", "&amp;": "&", "&quot;": '"', "&apos;": "'"}


def _paragraphs(docx: Path) -> list[str]:
    xml = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"<w:tbl\b.*?</w:tbl>", "", xml, flags=re.S)
    out = []
    for p in _P_RE.findall(xml):
        text = "".join(_T_RE.findall(p))
        for k, v in _ENTITIES.items():
            text = text.replace(k, v)
        if text.strip():
            out.append(text)
    return out


def review_external_docx(docx: Path, settings: GongwenSettings) -> dict:
    start = time.monotonic()
    try:
        paragraphs = _paragraphs(docx)
    except (KeyError, zipfile.BadZipFile):
        paragraphs = []
    blocks = []
    for i, text in enumerate(paragraphs, start=1):
        parsed = rules.parse_number(text)
        heading = parsed and len(text) <= 40 and not re.search(r"[。；]$", text)
        blocks.append(Block.model_construct(
            id=f"p-{i}", kind=f"heading{parsed[0]}" if heading else "paragraph", section="body",
            segments=[TextSegment.model_construct(kind="text", id=None, text=text)], table=None))
    pseudo = NoticeDraft.model_construct(docType="notice", blocks=blocks, fields=None, policyRefs=[])
    findings = rules.check_numbering(pseudo) + rules.check_counts(pseudo)
    for f in findings:
        if f.anchor.startswith("p-"):
            f.location_label = f"第 {f.anchor[2:]} 段"
    pairs = [issue_from_finding(f) for f in findings]
    index = [IndexEntry(f"p-{i}", "block", "body", f"第 {i} 段", t) for i, t in enumerate(paragraphs, start=1)]
    kit_pairs, format_check = _kit_layer(docx, index, settings)
    result = _finish(pairs + kit_pairs, format_check, {
        "docType": "external_docx",
        "coverage": "外来文件只做格式机检与层次序号、数量描述检查；公文要素、政策引用需在结构化稿中检查。",
    })
    logger.info("gongwen review external paragraphs=%d seconds=%.3f critical=%d format=%s",
                len(paragraphs), time.monotonic() - start, result["summary"]["critical"], format_check["status"])
    return result
