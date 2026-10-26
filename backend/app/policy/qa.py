"""政策问答：检索 → 阈值判断 → 有据作答 → 引用与原文定位。

三条不可动摇的规则：
1. 只依据检索到的条款作答，每句结论必须带 [n] 引用；
2. 最高分低于阈值时**不生成结论**，只把候选条款如实列出来；
3. 已废止条款不进结论，只能出现在“补充说明/历史对照”里，并显式标注。
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services import llm_chat

from . import corpus, retrieval
from .lifecycle import display_date, is_basis_eligible
from .models import PolicyQaLog, STATUS_PENDING, STATUS_REPEALED
from .retrieval import Candidate, DEFAULT_THRESHOLD, build_excerpt

MAX_EVIDENCE = 6
#: 摘录式回答的字数上限：够说清一条规定，又不会把整条条款倒出来
EXTRACT_MAX_CHARS = 220
#: 问题实义词在政策库中的最低覆盖率，低于此值视为库外问题
MIN_CORPUS_COVERAGE = 0.35
#: 模型明确表示「未作规定」时转为无依据
INSUFFICIENT_MARKERS = ("未作规定", "没有规定", "未涉及", "无法依据", "条款中未", "未找到相关")

SYSTEM_PROMPT = (
    "你是政务政策解读助手。只能依据下面给出的政策条款回答，不得使用条款以外的知识，"
    "不得编造政策名称、文号或条款编号。"
    "每一句结论后面必须用方括号标注来源条款序号，例如 [1]、[2]。"
    "如果给定条款不足以回答问题，直接回答「现有条款未作规定」，不要推测。"
    "只输出中文正文，不要输出标题，不要重复问题，不要用省略号截断原文。"
    "答案控制在 200 字以内，直接给出结论，不要罗列无关条款。"
)


# ---------------------------------------------------------------- 文本处理

def _strip_reasoning(text: str) -> str:
    text = re.sub(r"<think[^>]*>[\s\S]*?</think\s*>", "", text or "", flags=re.IGNORECASE)
    text = re.sub(r"<think[^>]*>[\s\S]*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def _strip_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _split_supplement(text: str) -> tuple[str, str]:
    for marker in ("补充说明：", "补充说明:", "说明：", "说明:"):
        if marker in text:
            head, tail = text.split(marker, 1)
            return head.strip(), tail.strip()
    return text.strip(), ""


def _build_messages(question: str, evidence: list[Candidate]) -> list[dict[str, str]]:
    lines: list[str] = []
    for idx, cand in enumerate(evidence, start=1):
        meta = "，".join(x for x in [
            cand.policy.title,
            f"文号 {cand.policy.doc_no}" if cand.policy.doc_no else "",
            cand.policy.issuer,
            cand.clause.clause_no,
        ] if x)
        lines.append(f"[{idx}] 《{meta}》：{cand.clause.content.strip()}")
    user = "政策条款：\n" + "\n".join(lines) + f"\n\n问题：{question}\n\n请依据上述条款作答，每句结论标注引用序号。"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _citation_payload(cand: Candidate, index: int) -> dict:
    return {
        "index": index,
        "clause_id": cand.clause.id,
        # 与 /gov/citations/batch、文稿 citationIds 同一格式，问答引用可直接带入起草
        "citation_id": cand.clause.citation_id,
        "policy_id": cand.policy.id,
        "policy_version": cand.policy.version,
        "verified_status": cand.policy.verified_status,
        "status_note": cand.policy.status_note,
        "source_anchor": cand.clause.source_anchor,
        "needs_review": cand.clause.needs_review,
        "policy_title": cand.policy.title,
        "doc_no": cand.policy.doc_no,
        "issuer": cand.policy.issuer,
        "status": cand.policy.status,
        "status_label": cand.policy.status,
        "clause_no": cand.clause.clause_no,
        "chapter": cand.clause.chapter,
        "heading": cand.clause.heading,
        "content": cand.clause.content,
        "excerpt": build_excerpt(cand.clause.content, cand.matched_terms),
        "page": cand.clause.page,
        "publish_date": display_date(cand.policy.publish_date),
        "effective_date": display_date(cand.policy.effective_date),
        "expire_date": display_date(cand.policy.expire_date),
        "source_url": cand.policy.source_url,
        "score": round(cand.score, 3),
    }


_META_NOISE = ("文号", "发布机关", "发布日期", "生效日期", "失效日期")


def _answer_is_noisy(conclusion: str, question: str) -> bool:
    """识别两类坏输出：把问题原样抄回来、把条款元信息当正文粘进来。"""
    text = (conclusion or "").strip()
    if len(text) < 8:
        return True
    if question and question.strip() and question.strip() in text:
        return True
    # 「《…》：…」这种整条条款连元信息一起搬运的形态
    if text.count("《") >= 1 and ("：" in text or ":" in text) and len(text) > 60:
        meta_hits = sum(1 for m in _META_NOISE if m in text)
        if meta_hits >= 1:
            return True
    return False


def _sentences(text: str) -> list[str]:
    """按句末标点切句。PDF 提取的换行先压掉，否则一句话会被拆成十几段。"""
    flat = re.sub(r"\s+", "", text or "")
    parts = re.split(r"(?<=[。！？；])", flat)
    return [p for p in (s.strip() for s in parts) if p]


def _sentence_score(sentence: str, terms: list[str], wants_number: bool) -> float:
    score = 0.0
    for term in terms:
        if term and term in sentence:
            score += 2.0
    if wants_number and re.search(r"\d", sentence):
        score += 1.5
    if re.search(r"应当|不得|可以|须", sentence):
        score += 0.5
    return score


_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_NUMBER_ASK = re.compile(r"(多少|几年|多长|多久|比例|上限|额度|期限|时限|几个工作日|百分之|几成)")


def _asks_number(question: str) -> bool:
    return bool(_NUMBER_ASK.search(question or ""))


def _has_ungrounded_number(conclusion: str, evidence: list[Candidate]) -> bool:
    """结论里的数字必须能在条款原文中找到，否则视为模型自行推算。"""
    text = re.sub(r"\[\d+\]", "", conclusion or "")
    # 只校验两位以上的数字：单字符多是列表序号、「第7页」之类，不是事实主张
    numbers = [n for n in _NUM_RE.findall(text) if len(n) >= 2]
    if not numbers:
        return False
    pool = "".join(re.sub(r"\s+", "", c.clause.content or "") for c in evidence[:3])
    return any(n not in pool for n in numbers)


def _extractive_answer(evidence: list[Candidate], question: str = "") -> str:
    """模型没用上引用标记时的兜底：从条款里挑出真正回答问题的那几句原文。

    不能简单截前 N 字 —— 关键数字往往在段落后半段（例如「长寿命锂电池
    循环寿命达到15000次」在千字条款的末尾），截断会把答案本身切掉，
    读者只看到省略号。这里做句子级筛选：按提问词与数字信号打分，
    保留高分句并按原顺序拼接，既不丢答案，也不把整条条款倒出来。
    """
    top = evidence[0]
    sentences = _sentences(top.clause.content)
    if not sentences:
        return f"《{top.policy.title}》{top.clause.clause_no} 未提取到可用原文 [1]"

    terms = [t for t in dict.fromkeys(retrieval.tokenize(question)) if len(t) >= 2]
    wants_number = bool(re.search(r"(多少|几年|多长|比例|上限|期限|时限|几个)", question or ""))

    scored = [(i, s, _sentence_score(s, terms, wants_number)) for i, s in enumerate(sentences)]

    # 问数值时，只保留带数字的句子 —— 其余句子再相关也不是答案
    if wants_number and any(re.search(r"\d", s) for _, s, _ in scored):
        scored = [(i, s, sc) for i, s, sc in scored if re.search(r"\d", s)]

    picked = [item for item in scored if item[2] > 0]

    # 一句都没命中（同义表述）时退回前两句，避免答非所问地空转
    if not picked:
        picked = scored[:2]

    picked.sort(key=lambda x: -x[2])
    chosen: list[tuple[int, str, float]] = []
    total = 0
    for item in picked:
        if chosen and total + len(item[1]) > EXTRACT_MAX_CHARS:
            continue
        chosen.append(item)
        total += len(item[1])
        if total >= EXTRACT_MAX_CHARS * 0.6 and len(chosen) >= 2:
            break
    chosen.sort(key=lambda x: x[0])

    body = "".join(s for _, s, _ in chosen)
    body = re.sub(r"^(?:[（(][一二三四五六七八九十百\d]{1,4}[）)]|\d{1,2}[.．、])", "", body)
    if len(body) > EXTRACT_MAX_CHARS:
        body = body[:EXTRACT_MAX_CHARS]
    head = f"《{top.policy.title}》{top.clause.clause_no}"
    return f"依{head}：{body} [1]"


# ---------------------------------------------------------------- 主流程

def _prepare(
    db: Session,
    question: str,
    *,
    store,
    scope: str,
    policy_ids: list[int] | None,
    include_deprecated: bool,
    threshold: float,
    top_k: int,
    max_evidence: int,
    user_id: int | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """检索 + 两道闸门。返回 (ctx, early)；early 非空表示这一问到此为止。

    检索与「给不给答」的判断都在这里完成，生成部分才能被同步、
    流式两种实现共用，避免两条链路各写一套规则后慢慢跑偏。
    """
    rows = corpus.load(store, scope=scope, policy_ids=policy_ids)
    candidates = retrieval.search(rows, question, top_k=top_k)
    above = [c for c in candidates if c.score >= threshold]

    # ---- 覆盖度闸门：问题里的实义词在库中几乎找不到 → 属于库外问题 ----
    asked_terms = retrieval.content_terms(question)
    matched_terms: set[str] = set()
    for cand in candidates:
        matched_terms.update(cand.matched_terms)
    corpus_coverage = (len(set(asked_terms) & matched_terms) / len(set(asked_terms))) if asked_terms else 0.0
    if candidates and asked_terms and corpus_coverage < MIN_CORPUS_COVERAGE:
        payload = {
            "status": "no_basis",
            "sufficient": False,
            "conclusion": "",
            "supplement": "",
            "reason": (
                f"政策库未收录与该问题直接相关的内容（问题关键词覆盖率 {corpus_coverage:.0%}）。"
                "为避免用无关条款拼凑答案，系统不生成结论，建议先补充相关政策或转人工核实。"
            ),
            "manual_confirm": [],
            "citations": [],
            "candidates": [
                {**cand.to_dict(), "below_threshold": True,
                 "excerpt": build_excerpt(cand.clause.content, cand.matched_terms)}
                for cand in candidates
            ],
            "meta": {**{"corpus_coverage": round(corpus_coverage, 3)}, "threshold": threshold,
                     "scope": scope, "candidates": len(candidates), "generated_by": "none"},
        }
        _log(db, question, payload, scope, user_id)
        return None, payload

    # 可作为现行依据的（已废止需显式允许）
    usable: list[Candidate] = []
    deprecated: list[Candidate] = []
    pending: list[Candidate] = []
    for cand in above:
        if is_basis_eligible(cand.policy.status):
            usable.append(cand)
        elif cand.policy.status == STATUS_REPEALED:
            deprecated.append(cand)
        elif cand.policy.status == STATUS_PENDING:
            pending.append(cand)

    used_deprecated = False
    if not usable and include_deprecated and deprecated:
        usable = deprecated[:max_evidence]
        used_deprecated = True

    meta = {
        "candidates": len(candidates),
        "above_threshold": len(above),
        "cited": 0,
        "deprecated": len(deprecated),
        "pending": len(pending),
        "excluded_deprecated": 0 if used_deprecated else len(deprecated),
        "threshold": threshold,
        "scope": scope,
        "model": "",
        "generated_by": "none",
        "include_deprecated": include_deprecated,
    }

    # ---------- 无依据：不生成结论 ----------
    if not usable:
        # 说明里统计的是全部候选（含未过阈值的），避免"明明有已废止条款却不提示"
        dep_all = [c for c in candidates if c.policy.status == STATUS_REPEALED]
        pend_all = [c for c in candidates if c.policy.status == STATUS_PENDING]
        top_score = max([c.score for c in candidates], default=0.0)
        reason_parts = [
            f"已检索 {len(candidates)} 条相关条款，最高相关度 {top_score:.2f}，"
            f"未达到可信阈值 {threshold:.2f}。"
        ]
        if dep_all:
            reason_parts.append(f"其中 {len(dep_all)} 条来自已废止文件，不能作为现行依据。")
        if pend_all:
            reason_parts.append(f"另有 {len(pend_all)} 条来自尚未人工核验的政策，核验前不能作为现行依据。")
        reason_parts.append("为避免误导，系统不生成结论。")
        meta["excluded_deprecated"] = len(dep_all) if not used_deprecated else 0

        payload = {
            "status": "no_basis",
            "sufficient": False,
            "conclusion": "",
            "supplement": "",
            "reason": "".join(reason_parts),
            "manual_confirm": [],
            "citations": [],
            "candidates": [
                {
                    **cand.to_dict(),
                    "below_threshold": cand.score < threshold,
                    "excerpt": build_excerpt(cand.clause.content, cand.matched_terms),
                }
                for cand in candidates
            ],
            "meta": meta,
        }
        _log(db, question, payload, scope, user_id)
        return None, payload

    return {
        "candidates": candidates,
        "deprecated": deprecated,
        "pending": pending,
        "meta": meta,
        "corpus_coverage": corpus_coverage,
        "evidence": usable[:max_evidence],
        "used_deprecated": used_deprecated,
    }, None


def _apply_guards(conclusion: str, question: str, evidence: list[Candidate],
                  error: str = "") -> tuple[str, str, str]:
    """模型输出质检：无引用 / 噪声 / 数值不可核 → 一律退回原文摘录。"""
    generated_by = "llm"
    supplement = ""

    if not re.search(r"\[\d+\]", conclusion or "") or _answer_is_noisy(conclusion, question):
        conclusion = _extractive_answer(evidence, question)
        generated_by = "extractive" if not error else "extractive_after_error"
        supplement = ""
    elif _asks_number(question) and re.search(r"\d", evidence[0].clause.content or ""):
        # 数值类问题一律引用原文：小模型会把「15000 次」改写成「15000 年」，
        # 数字全对、单位全错，比不答更危险。
        conclusion = _extractive_answer(evidence, question)
        generated_by = "extractive_numeric"
        supplement = "数值类问题直接引用原文表述，避免模型改写单位。"
    elif _has_ungrounded_number(conclusion, evidence):
        # 结论里出现了条款中不存在的数字，说明是模型自己算的，不能采信
        conclusion = _extractive_answer(evidence, question)
        generated_by = "extractive_ungrounded"
        supplement = "模型结论中的数值无法在条款中核对，已改为引用原文。"

    return conclusion, generated_by, supplement


def _assemble(ctx: dict[str, Any], question: str, conclusion: str, generated_by: str,
              supplement: str, error: str, *, db: Session, scope: str,
              user_id: int | None) -> dict[str, Any]:
    """把结论 + 引用 + 补充说明组装成前端可用的结构，并写问答留痕。"""
    evidence: list[Candidate] = ctx["evidence"]
    meta = dict(ctx["meta"])
    candidates = ctx["candidates"]
    deprecated = ctx["deprecated"]
    pending = ctx["pending"]
    threshold = meta["threshold"]

    if any(marker in (conclusion or "") for marker in INSUFFICIENT_MARKERS) and len(conclusion) < 120:
        payload = {
            "status": "no_basis",
            "sufficient": False,
            "conclusion": "",
            "supplement": conclusion,
            "reason": "模型判断：给定条款未对该问题作出规定，系统不生成结论。",
            "manual_confirm": ["建议补充相关政策文件，或转人工核实。"],
            "citations": [],
            "candidates": [
                {**cand.to_dict(), "below_threshold": cand.score < threshold,
                 "excerpt": build_excerpt(cand.clause.content, cand.matched_terms)}
                for cand in candidates
            ],
            "meta": {**meta, "corpus_coverage": round(ctx["corpus_coverage"], 3)},
        }
        _log(db, question, payload, scope, user_id)
        return payload

    cited_ids = sorted({int(x) for x in re.findall(r"\[(\d+)\]", conclusion)})
    cited_ids = [i for i in cited_ids if 1 <= i <= len(evidence)]
    if not cited_ids:
        cited_ids = [1]
        conclusion = conclusion + " [1]"

    citations = [_citation_payload(evidence[i - 1], i) for i in cited_ids]
    meta["cited"] = len(citations)
    meta["generated_by"] = generated_by
    if error:
        meta["error"] = error

    # ---------- 补充说明：已废止 / 待核实 ----------
    notes: list[str] = []
    if supplement:
        notes.append(supplement)

    deprecated_notes = []
    for cand in deprecated[:3]:
        if any(c["clause_id"] == cand.clause.id for c in citations):
            continue
        deprecated_notes.append({
            "policy_title": cand.policy.title,
            "doc_no": cand.policy.doc_no,
            "clause_no": cand.clause.clause_no,
            "content": cand.clause.content,
            "reason": cand.policy.status_note or "该文件已废止",
            "page": cand.clause.page,
        })
    if deprecated_notes:
        names = "、".join(f"《{d['policy_title']}》{d['clause_no']}" for d in deprecated_notes)
        notes.append(f"检索结果中的 {names} 来自已废止文件，仅作历史对照，不作为现行依据。")

    manual_confirm: list[str] = []
    for cand in pending[:3]:
        manual_confirm.append(
            f"《{cand.policy.title}》{cand.clause.clause_no} 尚未经人工核验，不能作为现行依据，请先在政策库核验。"
        )
    if any(c["status"] == STATUS_REPEALED for c in citations):
        manual_confirm.append("结论中引用了已废止条款（因显式允许），正式行文前必须替换为现行规定。")

    cited_statuses = {c["status"] for c in citations}
    sufficient = "full" if cited_statuses <= {"现行有效"} and not manual_confirm else "partial"

    payload = {
        "status": "answered",
        "sufficient": True,
        "sufficiency": sufficient,
        "conclusion": conclusion,
        "supplement": "\n".join(n for n in notes if n).strip(),
        "reason": "",
        "manual_confirm": manual_confirm,
        "deprecated_refs": deprecated_notes,
        "citations": citations,
        "candidates": [
            {**cand.to_dict(), "below_threshold": cand.score < threshold,
             "excerpt": build_excerpt(cand.clause.content, cand.matched_terms)}
            for cand in candidates
        ],
        "meta": meta,
    }
    _log(db, question, payload, scope, user_id)
    return payload


def _evidence_preview(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """流式场景下先发给前端的证据卡，编号与最终 citations 一致。"""
    return [_citation_payload(cand, i + 1) for i, cand in enumerate(ctx["evidence"])]


def answer(
    db: Session,
    question: str,
    *,
    store,
    scope: str = "current",
    policy_ids: list[int] | None = None,
    include_deprecated: bool = False,
    threshold: float = DEFAULT_THRESHOLD,
    top_k: int = 12,
    max_evidence: int = MAX_EVIDENCE,
    user_id: int | None = None,
) -> dict[str, Any]:
    question = (question or "").strip()
    if not question:
        raise ValueError("问题不能为空")

    ctx, early = _prepare(
        db, question, store=store, scope=scope, policy_ids=policy_ids,
        include_deprecated=include_deprecated, threshold=threshold, top_k=top_k,
        max_evidence=max_evidence, user_id=user_id,
    )
    if early is not None:
        return early

    conclusion = ""
    error = ""
    try:
        conf = llm_chat.settings()
        ctx["meta"]["model"] = conf["model"]
        raw = llm_chat.chat(_build_messages(question, ctx["evidence"]), temperature=0.2)
        conclusion = _strip_fence(_strip_reasoning(raw))
        conclusion, supplement = _split_supplement(conclusion)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        supplement = ""

    conclusion, generated_by, guard_supplement = _apply_guards(
        conclusion, question, ctx["evidence"], error
    )
    supplement = guard_supplement or supplement

    return _assemble(
        ctx, question, conclusion, generated_by, supplement, error,
        db=db, scope=scope, user_id=user_id,
    )


def answer_stream(
    db: Session,
    question: str,
    *,
    store,
    scope: str = "current",
    policy_ids: list[int] | None = None,
    include_deprecated: bool = False,
    threshold: float = DEFAULT_THRESHOLD,
    top_k: int = 12,
    max_evidence: int = MAX_EVIDENCE,
    user_id: int | None = None,
):
    """流式问答：先给证据，再逐块吐字，最后给完整结构。

    事件序列：
        stage   —— 检索/生成阶段提示
        evidence—— 命中的引用条款（编号与最终 citations 一致）
        delta   —— 结论文本增量
        final   —— 与 /policy/qa 完全相同的 payload（前端以此为准覆盖）
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("问题不能为空")

    yield {"type": "stage", "stage": "retrieve", "text": "正在检索政策库"}

    ctx, early = _prepare(
        db, question, store=store, scope=scope, policy_ids=policy_ids,
        include_deprecated=include_deprecated, threshold=threshold, top_k=top_k,
        max_evidence=max_evidence, user_id=user_id,
    )
    if early is not None:
        yield {"type": "final", "data": early}
        return

    evidence = ctx["evidence"]
    yield {
        "type": "evidence",
        "citations": _evidence_preview(ctx),
        "meta": {**ctx["meta"], "corpus_coverage": round(ctx["corpus_coverage"], 3)},
    }

    # 数值类问题不必等模型：直接引用原文，省掉整段生成时间
    if _asks_number(question) and re.search(r"\d", evidence[0].clause.content or ""):
        conclusion = _extractive_answer(evidence, question)
        yield {"type": "delta", "text": conclusion}
        payload = _assemble(
            ctx, question, conclusion, "extractive_numeric",
            "数值类问题直接引用原文表述，避免模型改写单位。", "",
            db=db, scope=scope, user_id=user_id,
        )
        yield {"type": "final", "data": payload}
        return

    yield {"type": "stage", "stage": "generate", "text": "正在生成结论"}

    buffer: list[str] = []
    error = ""
    supplement = ""
    try:
        conf = llm_chat.settings()
        ctx["meta"]["model"] = conf["model"]
        for chunk in llm_chat.stream(_build_messages(question, evidence), temperature=0.2):
            buffer.append(chunk)
            yield {"type": "delta", "text": chunk}
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    text = _strip_fence(_strip_reasoning("".join(buffer)))
    conclusion, supplement = _split_supplement(text)
    conclusion, generated_by, guard_supplement = _apply_guards(conclusion, question, evidence, error)
    if guard_supplement:
        supplement = guard_supplement

    payload = _assemble(
        ctx, question, conclusion, generated_by, supplement, error,
        db=db, scope=scope, user_id=user_id,
    )
    # 质检把模型输出换掉时，前端以 final 的结论为准覆盖已渲染的文字
    if payload.get("conclusion") != text.strip():
        yield {"type": "replace", "text": payload.get("conclusion", "")}
    yield {"type": "final", "data": payload}


def _log(db: Session, question: str, payload: dict, scope: str, user_id: int | None) -> None:
    try:
        record = PolicyQaLog(
            question=question,
            answer=payload.get("conclusion") or payload.get("reason") or "",
            citations_json=json.dumps(payload.get("citations") or [], ensure_ascii=False),
            scope=scope,
            status="answered" if payload.get("status") == "answered" else "no_basis",
            generated_by=payload.get("meta", {}).get("generated_by", ""),
            model=payload.get("meta", {}).get("model", ""),
            user_id=user_id,
        )
        db.add(record)
        db.commit()
    except Exception:
        db.rollback()
