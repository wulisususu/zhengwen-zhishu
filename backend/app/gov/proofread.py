"""Server-owned notice snapshot shared by review, approval and DOCX generation."""
import hashlib
import json
from fastapi import HTTPException
from pydantic import ValidationError
from app.services.gongwen.schema import NoticeDraft
from app.services.gongwen.rules import parse_number
from app.services.gongwen.review import review_notice, evaluate_gate
from app.services.gongwen.settings import load_settings


def blocks(document_id, payload):
    result = [{"id": document_id + "-recipient", "kind": "recipient", "section": "主送", "segments": [
        {"kind": "field", "id": document_id + "-recipient-field", "field": "recipient"}]}]
    for i, text in enumerate(payload.get("body", "").splitlines()):
        if not text.strip():
            continue
        number = parse_number(text.strip())
        kind = f"heading{number[0]}" if number else "paragraph"
        visible = text.lstrip() if number else text
        result.append({"id": f"{document_id}-p{i}", "kind": kind, "section": "正文", "segments": [
            {"kind": "text", "id": f"{document_id}-s{i}", "text": visible}]})
    for i, table in enumerate(payload.get("tables", [])):
        result.append({"id": f"{document_id}-t{i}", "kind": "table", "section": "正文", "segments": [], "table": table})
    result.append({"id": document_id + "-signature", "kind": "signature", "section": "落款", "segments": [
        {"kind": "field", "id": document_id + "-issuer-field", "field": "issuer"}]})
    if payload.get("fields", {}).get("undertaker", "").strip():
        result.append({"id": document_id + "-undertaker", "kind": "paragraph", "section": "承办", "segments": [
            {"kind": "text", "text": "承办："}, {"kind": "field", "id": document_id + "-undertaker-field", "field": "undertaker"}]})
    return result


def policy_references(payload):
    from .policy_refs import references
    return references(payload.get("citationIds", []), snapshot=payload.get("_citationSnapshot", []))


def notice(document_id, payload):
    data = {**payload, "blocks": blocks(document_id, payload), "policyRefs": [],
            "docNumber": {"id": document_id + "-number", "text": (payload.get("docNumber") or {}).get("text", "")}}
    try:
        return NoticeDraft.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(422, "通知字段不符合生成要求：" + "；".join(e["msg"] for e in exc.errors())) from None


def validate_notice(document_id, payload):
    if payload.get("docType", "notice") == "notice":
        notice(document_id, payload)


def digest(payload):
    data = {k: v for k, v in payload.items() if k != "_review"}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def run_review(draft):
    return review_notice(draft, load_settings())


def review(document_id, payload):
    draft = notice(document_id, payload)
    refs = policy_references(payload)
    # Use short internal identifiers only inside the standalone T2 model. Persisted
    # citation ids and authoritative metadata remain in policyVerification below.
    draft = draft.model_copy(update={"policyRefs": []})
    from app.services.gongwen.schema import PolicyRefIn
    draft.policyRefs = [PolicyRefIn(id=f"policy-{i}", title=r["title"][:200], clause=r["clause"][:100], status="unverified") for i, r in enumerate(refs)]
    result = run_review(draft)
    return refresh_policies(document_id, payload, result)


def refresh_policies(document_id, payload, result):
    # Resolve after the slow Node work. Approval calls this again while holding
    # a SQLite reserved write lock until the document transaction commits.
    refs = policy_references(payload)
    details = result.get("issueDetails", {})
    result["issues"] = [i for i in result["issues"] if details.get(i["id"], {}).get("code") not in {"POLICY_REF_UNVERIFIED", "POLICY_STATUS"}]
    for i, ref in enumerate(refs):
        if ref["status"] != "current" or ref.get("unresolved") or ref.get("isCurrentVersion") is False:
            invalid = ref["status"] == "abolished" or bool(ref.get("unresolved")) or ref.get("isCurrentVersion") is False
            issue = {"id": f"policy-status-{i}", "severity": "critical" if invalid else "warning", "source": "rule",
                     "title": "政策依据不可用" if invalid else "政策依据尚未核验",
                     "description": f"《{ref['title']}》：{ref.get('statusNote') or ('已废止' if invalid else '需人工核验有效性')}。",
                     "anchor": document_id + "-policies", "section": "policy", "locationLabel": "政策依据"}
            result["issues"].append(issue)
            details[issue["id"]] = {"code": "POLICY_STATUS", "layer": "policy", "anchorPrecision": "section"}
    for issue in result["issues"]:
        if not issue.get("anchor"):
            if issue.get("section") == "banji":
                issue["anchor"] = document_id + "-banji"
            elif issue.get("locationLabel") == "标题":
                issue["anchor"] = document_id + "-title"
    result["issueDetails"] = {i["id"]: details.get(i["id"], {}) for i in result["issues"]}
    result["policyVerification"] = {"status": "resolved", "refs": refs, "message": "状态由后端政策库核对；未核验与失效依据均明确提示。"}
    result["summary"] = {s: sum(i["severity"] == s for i in result["issues"]) for s in ("critical", "warning", "hint")}
    result["gate"] = evaluate_gate(result["issues"], result["formatCheck"]["status"] in {"pass", "hit"})
    return {**result, "contentDigest": digest(payload)}


def policy_guard(payload):
    from contextlib import nullcontext
    if not payload.get("citationIds"):
        return nullcontext()
    from app.services.policy.library import get_policy_library
    return get_policy_library().store.approval_guard()


def check(db, user, document_id, version):
    from . import service
    doc = service.get_document(db, user, document_id)
    if doc.version != version:
        raise HTTPException(409, "文稿已更新，请刷新后重试")
    payload = json.loads(doc.payload_json)
    if payload.get("docType", "notice") != "notice":
        raise HTTPException(422, "双层审校目前仅支持通知；其他文种请走人工审核")
    payload["_review"] = review(document_id, payload)
    service.write_revision(db, doc, version, payload=payload)
    service.record(db, doc, user, "双层审校", "确定性规则 + gongwen-kit；政策状态由后端政策库核对")
    db.commit()
    return service.serialize(db, doc)
