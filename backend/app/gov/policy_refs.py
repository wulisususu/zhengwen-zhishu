"""Resolve saved IDs against the policy library; client metadata is never trusted."""
import json
from fastapi import HTTPException
from . import service


def resolve(ids):
    if not ids:
        return []
    from app.services.policy.library import get_policy_library
    try:
        result = get_policy_library().citations(ids)
    except Exception:
        raise HTTPException(503, "政策库暂不可用，无法核对引用") from None
    if result.get("error"):
        raise HTTPException(503, "政策库暂不可用，无法核对引用")
    if result["missing"]:
        raise HTTPException(422, "引用条款不存在，请重新选择政策依据")
    return result["citations"]


def _reference(c):
    return {"id": c["id"], "title": c["policyTitle"], "clause": c["clause"],
             "status": c["status"], "statusNote": c.get("statusNote", ""),
             "sourceUrl": c["sourceUrl"], "policyId": c["policyId"], "version": c["version"],
             "excerpt": c["excerpt"]}


def references(ids, *, strict=False, snapshot=None):
    if strict:
        return [_reference(c) for c in resolve(ids)]
    if not ids:
        return []
    from app.services.policy.library import get_policy_library
    try:
        result = get_policy_library().citations(ids)
        found = {c["id"]: _reference(c) for c in result["citations"]} if not result.get("error") else {}
    except Exception:
        found = {}
    previous = {r["id"]: r for r in snapshot or []}
    refs = []
    for cid in ids:
        if cid in found:
            refs.append(found[cid])
        else:
            saved = previous.get(cid, {"id": cid, "title": "引用暂不可用", "clause": cid, "sourceUrl": "", "version": 0})
            refs.append({**saved, "status": "unverified", "unresolved": True,
                         "statusNote": "引用暂无法核对，保留原关联和已有来源记录；请恢复政策库或移除此依据。"})
    return refs


def select(db, user, document_id, body):
    doc = service.get_document(db, user, document_id)
    service.editable(doc, user)
    ids = list(dict.fromkeys(body.citationIds))
    refs = references(ids, strict=True)
    payload = json.loads(doc.payload_json)
    payload.pop("_review", None)
    payload["citationIds"] = ids
    payload["_citationSnapshot"] = refs
    service.write_revision(db, doc, body.version, payload=payload)
    service.record(db, doc, user, "更新政策依据", f"关联 {len(ids)} 个可追溯条款；状态以政策库核验记录为准")
    db.commit()
    return service.serialize(db, doc)
