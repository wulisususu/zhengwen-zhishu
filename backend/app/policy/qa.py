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
from app.services.policy.store import PolicyFilter

from . import conversation, corpus, retrieval
from .lifecycle import display_date
from .models import PolicyQaLog, STATUS_PENDING, STATUS_REPEALED, STATUS_EFFECTIVE
from .retrieval import Candidate, DEFAULT_THRESHOLD, build_excerpt

MAX_EVIDENCE = 6
#: 摘录式回答的字数上限：够说清一条规定，又不会把整条条款倒出来
EXTRACT_MAX_CHARS = 220
#: 问题实义词在政策库中的最低覆盖率，低于此值视为库外问题
MIN_CORPUS_COVERAGE = 0.35
#: 未核验前提的固定文案：由后端写进回答开头，不交给模型生成
UNVERIFIED_NOTICE = (
    "以下内容来自已入库但尚未经人工核验的政策，仅供参考；"
    "正式引用前，请审核人在政策库完成核验。"
)
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

def _library_stats(store) -> dict[str, int]:
    """政策库概况：总数与已核验 / 待核实份数（与 /gov/policies/stats 同一口径）。"""
    counts = {status: store.list_policies(PolicyFilter(statuses=(status,)), 1, 1)[1]
              for status in ("current", "abolished", "unverified")}
    return {"total": sum(counts.values()), "verified": counts["current"], "unverified": counts["unverified"]}


def _build_chat_ctx(store, question: str, candidates: list[Candidate], *,
                    scope: str, threshold: float, top_k: int) -> conversation.ChatContext:
    """组装对话路线的上下文。candidates 是按请求范围检索出的候选。"""
    kind = conversation.classify(question, has_candidates=any(c.score >= 0.3 for c in candidates))
    known_titles = {view.title for _, view in corpus.load(store, scope="all")}
    scope_hint = ""
    if scope == "current":
        # 严格模式下额外看一眼全库：有待核实的过阈值条款就提示用户切范围
        extra = [c for c in retrieval.search(corpus.load(store, scope="all"), question, top_k=top_k)
                 if c.score >= threshold and c.policy.status == STATUS_PENDING]
        if extra:
            scope_hint = (f"当前范围为『仅已核验现行政策』；另有 {len(extra)} 条相关条款在待核实政策中，"
                          "切换到『全部入库政策』可查看。")
    return conversation.ChatContext(
        kind=kind, stats=_library_stats(store), suggestions=[],
        scope_hint=scope_hint, known_titles=known_titles,
    )


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
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, Any]:
    """检索 + 依据分层。返回 (ctx, early, chat)，三者恰有一个非 None。

    检索与「给不给答」的判断都在这里完成，生成部分才能被同步、
    流式两种实现共用，避免两条链路各写一套规则后慢慢跑偏。
    third（chat）是对话路线的上下文，本任务固定为 None，由对话路线接入。
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
        # 库外问题（如闲聊、与政策无关的技术问题）：走对话路线友好回应
        return None, None, _build_chat_ctx(
            store, question, candidates, scope=scope, threshold=threshold, top_k=top_k,
        )

    # ---- 依据分层：已核验 > （显式允许的）已废止 > 待核实；其余如实拒答 ----
    usable: list[Candidate] = []
    deprecated: list[Candidate] = []
    pending: list[Candidate] = []
    not_in_force: list[Candidate] = []
    for cand in above:
        status = cand.policy.status
        if status == STATUS_EFFECTIVE:
            usable.append(cand)
        elif status == STATUS_REPEALED:
            deprecated.append(cand)
        elif status == STATUS_PENDING:
            pending.append(cand)
        else:
            not_in_force.append(cand)   # 尚未生效等

    basis = ""
    basis_notice = ""
    used_deprecated = False
    if usable:
        basis = "verified"
    elif include_deprecated and deprecated:
        basis = "deprecated"
        used_deprecated = True
    elif pending:
        basis = "unverified"
        basis_notice = UNVERIFIED_NOTICE

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
    if not basis:
        # 库里其实有相关文件、只是不在效力期内 —— 必须如实拒答并说明，不能装作「库里没找到」。
        # 注意这里看的是全部候选：范围限定到某份已废止政策时，其条款分数往往低于阈值，
        # 若只看过阈值的候选就会误入「没找到」的对话路线（test_abolished_policy... 把守这一点）。
        dep_all = [c for c in candidates if c.policy.status == STATUS_REPEALED]
        stale_others = [c for c in candidates
                        if c.policy.status not in (STATUS_EFFECTIVE, STATUS_PENDING, STATUS_REPEALED)]
        if dep_all or stale_others:
            stale = dep_all or stale_others
            titles = "、".join(sorted({f"《{c.policy.title}》" for c in stale}))
            if dep_all and not stale_others:
                state_text = "已废止"
            elif stale_others and not dep_all:
                state_text = "尚未生效"
            else:
                state_text = "已废止或尚未生效"
            reason = (
                f"相关条款来自{state_text}的文件（{titles}），不能作为现行依据。"
                "如需引用，请先在政策库核验现行版本，或在检索时显式允许引用已废止条款。"
            )
            payload = {
                "status": "no_basis",
                "sufficient": False,
                "reason_code": "not_in_force",
                "conclusion": "",
                "supplement": "",
                "reason": reason,
                "manual_confirm": [],
                "citations": [],
                "candidates": [
                    {**cand.to_dict(), "below_threshold": cand.score < threshold,
                     "excerpt": build_excerpt(cand.clause.content, cand.matched_terms)}
                    for cand in candidates
                ],
                "meta": meta,
            }
            _log(db, question, payload, scope, user_id)
            return None, payload, None

        # 库里没有可作依据的内容：说明情况或友好转开，交给对话路线
        return None, None, _build_chat_ctx(
            store, question, candidates, scope=scope, threshold=threshold, top_k=top_k,
        )

    evidence = (usable if basis == "verified"
                else deprecated if basis == "deprecated" else pending)[:max_evidence]
    return {
        "candidates": candidates,
        "deprecated": deprecated,
        "pending": pending,
        "meta": meta,
        "corpus_coverage": corpus_coverage,
        "evidence": evidence,
        "used_deprecated": used_deprecated,
        "basis": basis,
        "basis_notice": basis_notice,
    }, None, None


def _is_insufficient(conclusion: str) -> bool:
    return len(conclusion or "") < 120 and any(marker in (conclusion or "") for marker in INSUFFICIENT_MARKERS)


def _apply_guards(conclusion: str, question: str, evidence: list[Candidate],
                  error: str = "") -> tuple[str, str, str]:
    """模型输出质检：无引用 / 噪声 / 数值不可核 → 一律退回原文摘录。"""
    generated_by = "llm"
    supplement = ""

    if _is_insufficient(conclusion):
        return conclusion, generated_by, supplement

    cited_ids = [int(index) for index in re.findall(r"\[(\d+)\]", conclusion or "")]
    if not cited_ids or any(index < 1 or index > len(evidence) for index in cited_ids) or _answer_is_noisy(conclusion, question):
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
    basis = ctx.get("basis", "")
    basis_notice = ctx.get("basis_notice", "") if basis == "unverified" else ""

    if _is_insufficient(conclusion):
        payload = {
            "status": "no_basis",
            "sufficient": False,
            "reason_code": "model_insufficient",
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
    if basis == "unverified":
        # 依据本身来自未核验政策：按政策去重各提醒一条（不再说「不能作为现行依据」）
        for title in dict.fromkeys(c["policy_title"] for c in citations if c["status"] == STATUS_PENDING):
            manual_confirm.append(f"本次引用的《{title}》尚未经人工核验，正式行文前请审核人在政策库核验。")
    else:
        for cand in pending[:3]:
            manual_confirm.append(
                f"《{cand.policy.title}》{cand.clause.clause_no} 尚未经人工核验，不能作为现行依据，请先在政策库核验。"
            )
    if any(c["status"] == STATUS_REPEALED for c in citations):
        manual_confirm.append("结论中引用了已废止条款（因显式允许），正式行文前必须替换为现行规定。")

    cited_statuses = {c["status"] for c in citations}
    if basis == "unverified":
        sufficient = "partial"      # 依据来自未核验政策：一律不算「依据充分」
    else:
        sufficient = "full" if cited_statuses <= {"现行有效"} and not manual_confirm else "partial"

    payload = {
        "status": "answered",
        "sufficient": True,
        "sufficiency": sufficient,
        "basis": basis,
        "basis_notice": basis_notice,
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


# ---------------------------------------------------------------- 对话路线

def _chat_answer(db: Session, question: str, ctx: conversation.ChatContext, *,
                 scope: str, user_id: int | None,
                 history: list[dict] | None = None) -> dict[str, Any]:
    """对话路线（同步）：受约束提示词生成；质检不过或模型不可用就换兜底话术。"""
    model = ""
    error = ""
    reply = None
    try:
        conf = llm_chat.settings()
        model = conf["model"]
        raw = llm_chat.chat(conversation.build_chat_messages(question, history or [], ctx), temperature=0.6)
        reply = conversation.guard_reply(raw, ctx.known_titles)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    generated_by = "chat_llm"
    if reply is None:
        reply = conversation.fallback_reply(ctx, question)
        generated_by = "chat_fallback"
    payload = conversation.chat_payload(reply, generated_by, ctx, scope)
    payload["meta"]["model"] = model
    if error:
        payload["meta"]["error"] = error
    _log(db, question, payload, scope, user_id)
    return payload


def _chat_stream(db: Session, question: str, ctx: conversation.ChatContext, *,
                 scope: str, user_id: int | None,
                 history: list[dict] | None = None):
    """对话路线（流式）：mode → delta →（被质检换掉时）replace → final。"""
    yield {"type": "mode", "mode": "chat"}
    model = ""
    error = ""
    buffer: list[str] = []
    try:
        conf = llm_chat.settings()
        model = conf["model"]
        for chunk in llm_chat.stream(
                conversation.build_chat_messages(question, history or [], ctx), temperature=0.6):
            buffer.append(chunk)
            yield {"type": "delta", "text": chunk}
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    text = "".join(buffer)
    reply = conversation.guard_reply(text, ctx.known_titles)
    generated_by = "chat_llm"
    if reply is None:
        reply = conversation.fallback_reply(ctx, question)
        generated_by = "chat_fallback"
    if reply != text:
        yield {"type": "replace", "text": reply}
    payload = conversation.chat_payload(reply, generated_by, ctx, scope)
    payload["meta"]["model"] = model
    if error:
        payload["meta"]["error"] = error
    _log(db, question, payload, scope, user_id)
    yield {"type": "final", "data": payload}


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

    ctx, early, chat_ctx = _prepare(
        db, question, store=store, scope=scope, policy_ids=policy_ids,
        include_deprecated=include_deprecated, threshold=threshold, top_k=top_k,
        max_evidence=max_evidence, user_id=user_id,
    )
    if early is not None:
        return early
    if chat_ctx is not None:
        return _chat_answer(db, question, chat_ctx, scope=scope, user_id=user_id)

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

    ctx, early, chat_ctx = _prepare(
        db, question, store=store, scope=scope, policy_ids=policy_ids,
        include_deprecated=include_deprecated, threshold=threshold, top_k=top_k,
        max_evidence=max_evidence, user_id=user_id,
    )
    if early is not None:
        yield {"type": "final", "data": early}
        return
    if chat_ctx is not None:
        yield from _chat_stream(db, question, chat_ctx, scope=scope, user_id=user_id)
        return

    evidence = ctx["evidence"]
    yield {
        "type": "evidence",
        "citations": _evidence_preview(ctx),
        "basis": ctx["basis"],
        "basis_notice": ctx["basis_notice"],
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
        status = payload.get("status") or "no_basis"
        if status not in ("answered", "no_basis", "chat"):
            status = "no_basis"
        record = PolicyQaLog(
            question=question,
            answer=payload.get("conclusion") or payload.get("reply") or payload.get("reason") or "",
            citations_json=json.dumps(payload.get("citations") or [], ensure_ascii=False),
            scope=scope,
            status=status,
            generated_by=payload.get("meta", {}).get("generated_by", ""),
            model=payload.get("meta", {}).get("model", ""),
            user_id=user_id,
        )
        db.add(record)
        db.commit()
    except Exception:
        db.rollback()
