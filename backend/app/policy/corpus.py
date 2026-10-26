"""政策问答的语料：只读既有政策库（T1，policy.db），不另建政策表。

政策的导入（含 PDF 逐页解析与 OCR，T3）、元数据补录与人工核验都走 /gov/policies；
这里只把库中条款适配成检索与问答使用的形状，并给出「能否作为现行依据」的状态。

状态以人工核验为准：
- 未核验（unverified）→ 待核实，不能作为现行依据；
- 已废止（abolished）→ 已废止；
- 已核验现行（current）→ 再按生效 / 失效日期纠偏：已过失效日期视为已废止，
  尚未到生效日期为尚未生效，二者都不能作为现行依据。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.services.policy.library import citation_id
from app.services.policy.store import ClauseHit, PolicyStore, StoredClause, StoredPolicy

from .lifecycle import parse_date
from .models import STATUS_EFFECTIVE, STATUS_NOT_YET, STATUS_PENDING, STATUS_REPEALED
from .retrieval import normalize_search_text

_VERIFIED_LABELS = {"current": STATUS_EFFECTIVE, "abolished": STATUS_REPEALED, "unverified": STATUS_PENDING}


@dataclass(frozen=True)
class PolicyView:
    id: int
    title: str
    doc_no: str
    issuer: str
    status: str            # 现行有效 / 已废止 / 待核实 / 尚未生效
    verified_status: str   # current / abolished / unverified（T1 原值）
    status_note: str
    publish_date: str
    effective_date: str
    expire_date: str
    source_url: str
    version: int
    is_current_version: bool
    region: str = ""


@dataclass(frozen=True)
class ClauseView:
    id: int
    policy_id: int
    seq: int
    clause_no: str
    chapter: str
    heading: str
    content: str
    page: int | None
    source_anchor: str
    needs_review: bool
    search_text: str
    citation_id: str


def effective_status(policy: StoredPolicy, today: date | None = None) -> str:
    label = _VERIFIED_LABELS.get(policy.verified_status, STATUS_PENDING)
    if label != STATUS_EFFECTIVE:
        return label
    today = today or date.today()
    expire = parse_date(policy.expire_date)
    if expire and expire < today:
        return STATUS_REPEALED
    effective = parse_date(policy.effective_date)
    if effective and effective > today:
        return STATUS_NOT_YET
    return STATUS_EFFECTIVE


def _policy_view(p: StoredPolicy, today: date | None) -> PolicyView:
    return PolicyView(
        id=p.id, title=p.title, doc_no=p.doc_number or "", issuer=p.issuer or "",
        status=effective_status(p, today), verified_status=p.verified_status,
        status_note=p.status_note or "", publish_date=p.publish_date or "",
        effective_date=p.effective_date or "", expire_date=p.expire_date or "",
        source_url=p.url if p.url and not p.url.startswith("upload://") else "",
        version=p.version, is_current_version=bool(p.is_current),
    )


def _clause_view(c: StoredClause) -> ClauseView:
    return ClauseView(
        id=c.id, policy_id=c.policy_id, seq=c.sequence, clause_no=c.article_number or "",
        chapter="", heading=c.heading or "", content=c.content, page=c.page_number,
        source_anchor=c.source_anchor or "", needs_review=bool(c.needs_review),
        search_text=normalize_search_text(c.content), citation_id=citation_id(c.id),
    )


def load(store: PolicyStore, *, scope: str = "current", policy_ids: list[int] | None = None,
         today: date | None = None) -> list[tuple[ClauseView, PolicyView]]:
    """检索范围：current 只含现行有效；all 含全部现行版本（任何状态）；policy 只含指定政策。"""
    ids = [int(i) for i in policy_ids] if scope == "policy" and policy_ids else None
    hits: list[ClauseHit] = store.corpus_clauses(ids)
    policies: dict[int, PolicyView] = {}
    rows = []
    for hit in hits:
        view = policies.get(hit.policy.id) or policies.setdefault(hit.policy.id, _policy_view(hit.policy, today))
        if scope == "current" and view.status != STATUS_EFFECTIVE:
            continue
        if _is_title_only(hit.clause, hit.policy):
            continue
        rows.append((_clause_view(hit.clause), view))
    return rows


def _is_title_only(clause: StoredClause, policy: StoredPolicy) -> bool:
    """政策库把首条之前的文字存为「序言」；只有标题时不是可引用的规定，
    否则标题含全部检索词，会排在真正作答的条款前面。有实质内容的序言照常参与检索。"""
    if clause.article_number:
        return False
    body = normalize_search_text(clause.content)
    return not body or body == normalize_search_text(policy.title)
