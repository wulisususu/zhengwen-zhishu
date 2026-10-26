"""条款级检索（不引入新框架）。

为什么不用向量库：
    政策问答的召回单元是「第X条」，不是 500 字 chunk。条款通常只有一两百字，
    关键词与条款编号的区分度已经足够；再叠一层 embedding 只会让「为什么召回这条」
    变得不可解释。这里用 BM25 + 查询词覆盖率，分数可拆解、可展示、可调阈值。

检索范围（对应原型的三档）：
    current —— 仅现行有效
    all     —— 全部（含已废止、待核实）
    policy  —— 仅指定政策
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .models import BASIS_STATUSES, PolicyClause, PolicyDocument
from .parser import normalize_search_text

#: 打分权重（可调）
W_BM25 = 0.50
W_COVERAGE = 0.30
W_ANSWER_TYPE = 0.20
#: 分数校准：raw / SCALE 后落在 0-1，使阈值 0.60 大致等价于「强相关」
SCORE_SCALE = 0.70
#: 「立法目的/适用范围」类条款对具体数值问题的干扰惩罚
PURPOSE_PENALTY = 0.15

#: 停用字：含这些字的二元组不参与覆盖率计算（疑问词、虚词）
_STOP_CHARS = set("怎么什哪吗呢几多少如何请问需要可以是得了在和与或及对为这那其就此把被让给从向按据")
#: BM25 饱和常数：越大越平缓
BM25_SATURATION = 6.0
BM25_K1 = 1.2
BM25_B = 0.75

DEFAULT_THRESHOLD = 0.60


@dataclass
class Candidate:
    policy: PolicyDocument
    clause: PolicyClause
    score: float
    bm25: float
    coverage: float
    matched_terms: list[str] = field(default_factory=list)

    def to_dict(self, *, index: int | None = None) -> dict:
        status = self.policy.status
        return {
            "index": index,
            "policy_id": self.policy.id,
            "clause_id": self.clause.id,
            "policy_title": self.policy.title,
            "doc_no": self.policy.doc_no,
            "issuer": self.policy.issuer,
            "status": status,
            "status_label": status,
            "region": self.policy.region,
            "effective_date": self.policy.effective_date,
            "expire_date": self.policy.expire_date,
            "clause_no": self.clause.clause_no,
            "chapter": self.clause.chapter,
            "heading": self.clause.heading,
            "content": self.clause.content,
            "page": self.clause.page,
            "score": round(self.score, 4),
            "bm25": round(self.bm25, 4),
            "coverage": round(self.coverage, 4),
            "matched_terms": self.matched_terms[:8],
        }


# ---------------------------------------------------------------- 分词

_RE_ALNUM = re.compile(r"[a-z0-9]{2,}")


def tokenize(text: str) -> list[str]:
    """中文按二元字组切分，英文数字按词切分。无需结巴分词依赖。"""
    normalized = normalize_search_text(text)
    if not normalized:
        return []
    tokens: list[str] = []
    for run in _RE_ALNUM.findall(normalized):
        tokens.append(run)
    chinese = re.sub(r"[a-z0-9]", "", normalized)
    for i in range(len(chinese) - 1):
        tokens.append(chinese[i:i + 2])
    if len(chinese) == 1:
        tokens.append(chinese)
    return tokens


_PURPOSE_RE = re.compile(r"(为|为了)[^。]{0,40}(制定|规范|加强|促进|支持|保障)|本办法适用于|本办法所称")

#: 问句维度 → (问题触发词, 条款答案特征)
_DIMENSIONS = {
    "ratio": (re.compile(r"(比例|百分之|百分比|幅度|标准|几成)"), re.compile(r"(百分之[一二三四五六七八九十百千两\d]+|\d+\s*[%％]|折|按.{0,8}给予)")),
    "amount": (re.compile(r"(上限|额度|金额|多少钱|封顶|最高)"), re.compile(r"\d+(?:\.\d+)?\s*(?:万元|元|万)")),
    "deadline": (re.compile(r"(多久|时限|期限|几天|几个工作日|何时|什么时候|多长时间)"), re.compile(r"\d+\s*(?:个)?\s*(?:工作日|日|天|个月|月|年)内?|日内|个月内")),
    "condition": (re.compile(r"(条件|资格|要求|能否|可不可以|可以吗|满不满足)"), re.compile(r"(应当|须|条件|不得|符合|具备)")),
    "material": (re.compile(r"(材料|证件|带什么|准备什么|提交什么)"), re.compile(r"(材料|提交|附送|清单)")),
    "subject": (re.compile(r"(适用于|适用|哪些企业|哪些人|对象|范围)"), re.compile(r"(适用于|所称|范围|对象)")),
}

#: 这些维度下，「立法目的」条款几乎不可能是答案
_SPECIFIC_DIMENSIONS = {"ratio", "amount", "deadline", "material", "condition"}


def content_terms(text: str) -> list[str]:
    """查询词里的实义词：过滤疑问词与虚词构成的二元组。"""
    return [t for t in dict.fromkeys(tokenize(text))
            if not any(ch in _STOP_CHARS for ch in t)]


def detect_dimensions(question: str) -> set[str]:
    return {key for key, (q_re, _) in _DIMENSIONS.items() if q_re.search(question or "")}


def _answer_type_match(dimensions: set[str], content: str) -> float:
    if not dimensions:
        return 0.0
    for key in dimensions:
        if _DIMENSIONS[key][1].search(content or ""):
            return 1.0
    return 0.0


def _clause_tokens(clause: PolicyClause) -> list[str]:
    base = clause.search_text or normalize_search_text(clause.content)
    text = f"{clause.clause_no}{clause.chapter}{base}"
    return tokenize(text)


# ---------------------------------------------------------------- 打分

def _bm25_scores(query_tokens: list[str], docs_tokens: list[list[str]]) -> tuple[list[float], dict[str, float]]:
    n = len(docs_tokens)
    if n == 0:
        return [], {}
    df: dict[str, int] = {}
    for tokens in docs_tokens:
        for term in set(tokens):
            df[term] = df.get(term, 0) + 1
    avgdl = sum(len(t) for t in docs_tokens) / n or 1.0

    idf = {
        term: math.log(1 + (n - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
        for term in set(query_tokens)
    }

    scores: list[float] = []
    for tokens in docs_tokens:
        tf: dict[str, int] = {}
        for term in tokens:
            tf[term] = tf.get(term, 0) + 1
        dl = len(tokens) or 1
        total = 0.0
        for term in set(query_tokens):
            freq = tf.get(term, 0)
            if not freq:
                continue
            denom = freq + BM25_K1 * (1 - BM25_B + BM25_B * dl / avgdl)
            total += idf[term] * freq * (BM25_K1 + 1) / denom
        scores.append(total)
    return scores, idf


def search(
    db: Session,
    query: str,
    *,
    scope: str = "current",
    policy_ids: list[int] | None = None,
    top_k: int = 12,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[Candidate]:
    """返回按分数降序的条款候选（不过滤阈值，阈值判断交给调用方）。"""
    q = db.query(PolicyClause, PolicyDocument).join(
        PolicyDocument, PolicyClause.policy_id == PolicyDocument.id
    )

    if scope == "policy" and policy_ids:
        q = q.filter(PolicyClause.policy_id.in_(policy_ids))
    elif scope == "current":
        q = q.filter(PolicyDocument.status.in_(BASIS_STATUSES))
    # scope == "all" → 不加状态过滤

    rows = q.all()
    if not rows:
        return []

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    docs_tokens = [_clause_tokens(clause) for clause, _ in rows]
    bm25_list, idf = _bm25_scores(query_tokens, docs_tokens)

    terms_for_coverage = content_terms(query) or list(dict.fromkeys(query_tokens))
    total_idf = sum(idf.get(t, 0.0) for t in terms_for_coverage) or 1.0
    dimensions = detect_dimensions(query)

    candidates: list[Candidate] = []
    for (clause, policy), tokens, bm25 in zip(rows, docs_tokens, bm25_list):
        token_set = set(tokens)
        matched = [t for t in terms_for_coverage if t in token_set]
        coverage = sum(idf.get(t, 0.0) for t in matched) / total_idf
        bm25_norm = bm25 / (bm25 + BM25_SATURATION) if bm25 > 0 else 0.0

        answer_match = _answer_type_match(dimensions, clause.content)
        penalty = 0.0
        if dimensions & _SPECIFIC_DIMENSIONS and _PURPOSE_RE.search(clause.content or ""):
            penalty = PURPOSE_PENALTY

        raw = W_BM25 * bm25_norm + W_COVERAGE * coverage + W_ANSWER_TYPE * answer_match - penalty
        if raw <= 0:
            continue
        score = min(1.0, raw / SCORE_SCALE)
        candidates.append(Candidate(
            policy=policy,
            clause=clause,
            score=score,
            bm25=bm25,
            coverage=coverage,
            matched_terms=matched,
        ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:top_k]


# ---------------------------------------------------------------- 原文定位

def build_excerpt(content: str, terms: list[str], *, radius: int = 36) -> dict:
    """在条款原文里定位命中片段，返回 前置 / 高亮 / 后置。

    高亮取「命中所在整句」，而不是命中词本身 —— 只有两个字的高亮在界面上没有意义。
    """
    text = content or ""
    if not text:
        return {"pre": "", "hl": "", "post": ""}

    position = -1
    hit = ""
    for term in terms:
        if not term:
            continue
        idx = text.find(term)
        if idx >= 0 and (position < 0 or idx < position):
            position = idx
            hit = term

    if position < 0:
        cut = min(len(text), 180)
        return {"pre": "", "hl": text[:cut], "post": text[cut:]}

    # 向左找最近的句末标点
    left = max(text.rfind("。", 0, position), text.rfind("；", 0, position),
               text.rfind("\n", 0, position))
    begin = left + 1 if left >= 0 else max(0, position - radius)
    # 向右延伸到句末
    stop = len(text)
    for mark in ("。", "；", "\n"):
        idx = text.find(mark, position + len(hit))
        if idx >= 0:
            stop = min(stop, idx + 1)
    end = min(len(text), max(stop, position + len(hit)))

    return {
        "pre": ("…" if begin > 0 else "") + text[max(0, begin - 24):begin],
        "hl": text[begin:end].strip(),
        "post": text[end:end + 24] + ("…" if end < len(text) else ""),
    }
