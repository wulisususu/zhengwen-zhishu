"""按政策名称匹配：用户说「帮我看看某某政策」时找到对应的文件。

只看「问题里的名称」与「标题」的字组重叠，不碰检索阈值：
- ≥ 0.8 且明显高出第二名 → 唯一强匹配，介绍这份政策；
- ≥ 0.5 → 只用来列「名称相近」的建议供点选；
- 判断「是不是在找政策」的门槛：有书名号、含「看看/介绍/了解」、
  或去掉填充词后以「办法/通知/…」结尾。
阈值按样例估算；样例对不上时在 ±0.1 内调整（计划已注明）。
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .retrieval import tokenize

#: 唯一强匹配阈值
STRONG = 0.8
#: 进入「名称相近」建议的门槛
SUGGEST = 0.5

_FILL_RE = re.compile(r"帮我|看看|看一下|介绍|了解|一下|能|吗|请|这个|政策|文件")
_LOOKING_RE = re.compile(r"看看|看一下|介绍|了解")
_SUFFIX_RE = re.compile(r"(办法|通知|规定|条例|意见|细则|方案)$")
_CLAUSE_RE = re.compile(r"《([^》]{1,80})》")
#: 标题里的元信息与标点：不参与名称比对
_NOISE_RE = re.compile(r"关于|印发|的通知|（试行）|\(试行\)|[《》「」『』\s，,。.．：:；;、！!？?\-—()（）　]")


@dataclass
class TitleMatch:
    policy: object
    score: float


def title_core(title: str) -> str:
    """去掉「关于/印发/的通知/（试行）」和标点后的标题核心。"""
    return _NOISE_RE.sub("", title or "")


def strip_fillers(question: str) -> str:
    return _FILL_RE.sub("", question or "").strip()


def _looking_for_policy(question: str) -> bool:
    """是不是在按名称找政策：书名号、明确的「看看/介绍」动词，或去掉填充词后以文种结尾。"""
    if _CLAUSE_RE.search(question or ""):
        return True
    if _LOOKING_RE.search(question or ""):
        return True
    stripped = strip_fillers(question)
    return bool(stripped) and bool(_SUFFIX_RE.search(stripped))


def _question_name(question: str) -> tuple[str, bool]:
    """问题一侧的名称，以及它是否带书名号。"""
    quoted = _CLAUSE_RE.search(question or "")
    if quoted:
        return quoted.group(1).strip(), True
    return strip_fillers(question), False


def _score(name: str, title: str, quoted: bool) -> float:
    name_tokens = set(tokenize(name))
    title_tokens = set(tokenize(title))
    if not name_tokens or not title_tokens:
        return 0.0
    if quoted and (name in title or title in name):
        return 1.0
    cover_title = len(title_tokens & name_tokens) / len(title_tokens)
    cover_name = len(name_tokens & title_tokens) / len(name_tokens)
    return max(cover_title, cover_name)


def match_titles(question: str, policies: list) -> list[TitleMatch]:
    """按名称给政策打分，返回 ≥ SUGGEST 的项，按分数降序。"""
    if not _looking_for_policy(question or ""):
        return []
    name, quoted = _question_name(question or "")
    name = title_core(name)
    if not name:
        return []
    matches: list[TitleMatch] = []
    for policy in policies or []:
        score = _score(name, title_core(policy.title), quoted)
        if score >= SUGGEST:
            matches.append(TitleMatch(policy=policy, score=round(score, 3)))
    matches.sort(key=lambda m: (-m.score, getattr(m.policy, "id", 0)))
    return matches


def remaining_question(question: str, title: str) -> str:
    """去掉政策名之后的问题：书名号整段删除；否则删填充词再删与标题核心的最长公共子串。"""
    quoted = _CLAUSE_RE.search(question or "")
    if quoted:
        rest = (question[:quoted.start()] + " " + question[quoted.end():])
    else:
        rest = strip_fillers(question)
        core = title_core(title)
        if rest and core:
            m = difflib.SequenceMatcher(None, rest, core).find_longest_match(0, len(rest), 0, len(core))
            if m.size >= 4:
                rest = rest[:m.a] + rest[m.a + m.size:]
    return rest.strip()
