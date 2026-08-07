from __future__ import annotations

import os
import re
from typing import Callable

import requests

from app.config import get_config
from app.services.voice_refiner_prompts import (
    build_final_polish_prompt,
    build_partial_fix_prompt,
    build_sentence_fix_prompt,
)


StageRunner = Callable[[str, str], str]
_THINK_TAG_RE = re.compile(r"</?think>", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_TRAILING_PUNCT_RE = re.compile(r"[。！？!?；;，,、]+$")
_FILLER_PREFIX_RE = re.compile(r"^(?:嗯|呃|这个|那个|然后|就是|所以)[，,、 ]*")
_COMMON_PARTIAL_REPLACEMENTS = (
    ("觉的", "觉得"),
    ("五各", "五个"),
    ("父亲行", "并行"),
    ("链化", "量化"),
    ("状转写", "转写"),
    ("半秒秒", "半秒"),
    ("低空间", "低空经济"),
    ("低空经济已是", "低空经济是"),
)


# ---------------------------------------------------------------------------
# Sentence-breaking rules (Phase 1: conservative)
# ---------------------------------------------------------------------------

# Strong period triggers — insert 。 before these
_PERIOD_TRIGGERS = ("总之", "总的来说", "综上所述", "归根结底")

# Comma triggers — insert ， before these
_COMMA_TRIGGERS = (
    "但是", "可是", "然而", "而且", "并且", "同时", "不过", "虽然", "即使",
    "所以", "因此", "然后", "接着", "于是",
    "比如", "例如", "也就是说", "换句话说",
    "其中", "另外", "此外", "除此之外", "与此同时",
    "最后",
)

# Combined pattern: match any trigger at a word boundary (not at start of text)
_TRIGGERS_PATTERN = re.compile(
    r"(?<!^)(?=("
    + "|".join(re.escape(t) for t in sorted(set(_PERIOD_TRIGGERS + _COMMA_TRIGGERS), key=len, reverse=True))
    + r"))"
)

# Duplicate punctuation: 。，。 or ，， etc.
_DUP_PUNCT_RE = re.compile(r"([。，！？；、])\1+")

# Consecutive different punctuation: 。， or ，。
_MIXED_PUNCT_RE = re.compile(r"[。！？]\s*[，,、]+")

# Segment length threshold for forced comma insertion
_FORCE_BREAK_LEN = 50

# Characters that count as punctuation for segment length tracking
_PUNCT_CHARS = set("。，！？；、.!?;,:")


def _insert_sentence_breaks(text: str) -> str:
    """Insert punctuation into long unpunctuated Chinese text.

    Priority order:
    1. Insert punctuation before explicit connective triggers
    2. Clean up duplicate / mixed punctuation
    3. Force comma at ~50 chars if segment still has no punctuation (fallback)
    """
    if not text:
        return ""

    # Step 0: Protect compound words that contain trigger substrings
    # "与此同时" contains "同时" as a trigger — protect it from being split
    _COMPOUND_PROTECT_RE = re.compile(r"与此＀[，,]?同时")

    text = text.replace("与此同时", "与此＀同时")

    # Step 1: Insert punctuation before triggers
    result = _TRIGGERS_PATTERN.sub(_pick_punct, text)

    # Step 1b: Restore protected compound words (handle comma insertion)
    result = _COMPOUND_PROTECT_RE.sub("与此同时", result)

    # Step 2: Clean up duplicate / mixed punctuation
    result = _DUP_PUNCT_RE.sub(r"\1", result)
    result = _MIXED_PUNCT_RE.sub("。", result)

    # Step 3: Force-break long unpunctuated segments
    result = _force_break_long_segments(result)

    return result


def _pick_punct(match: re.Match) -> str:
    """Decide which punctuation to insert based on the matched trigger word."""
    # The trigger is in group 1
    trigger = match.group(1)
    if trigger in _PERIOD_TRIGGERS:
        return "。"
    return "，"


def _force_break_long_segments(text: str) -> str:
    """If a segment between punctuations exceeds _FORCE_BREAK_LEN chars,
    insert ， at the most recent plausible break point."""
    # Split on existing punctuation
    parts = []
    current = ""
    for ch in text:
        current += ch
        if ch in _PUNCT_CHARS:
            parts.append(current)
            current = ""
    if current:
        parts.append(current)

    result_parts = []
    for part in parts:
        if len(part) <= _FORCE_BREAK_LEN:
            result_parts.append(part)
            continue
        # Try to insert commas within this long segment
        broken = _break_long_segment(part)
        result_parts.append(broken)

    return "".join(result_parts)


def _break_long_segment(segment: str) -> str:
    """Break a single long segment by inserting commas."""
    # If segment already ends with punctuation, just check interior
    # Find positions of trigger words within the segment
    pieces = []
    last_cut = 0

    for m in re.finditer(
        "|".join(re.escape(t) for t in _COMMA_TRIGGERS),
        segment,
    ):
        # Only break if the sub-segment so far is long enough
        sub = segment[last_cut:m.start()]
        if len(sub) >= 15:  # don't break very short sub-segments
            pieces.append(sub + "，")
            last_cut = m.start()

    if last_cut > 0:
        pieces.append(segment[last_cut:])
        joined = "".join(pieces)
    else:
        joined = segment

    # If still too long with no break found, search for nearest trigger word
    if len(joined) > _FORCE_BREAK_LEN:
        mid = len(joined) // 2
        best_pos = -1
        for trigger in _COMMA_TRIGGERS:
            pos = joined.find(trigger, max(0, mid - 25))
            if 10 <= pos < len(joined) - 5:
                if best_pos < 0 or abs(pos - mid) < abs(best_pos - mid):
                    best_pos = pos
        if best_pos >= 0:
            joined = joined[:best_pos] + "，" + joined[best_pos:]

    return joined


# ---------------------------------------------------------------------------
# Existing utilities (unchanged)
# ---------------------------------------------------------------------------


class VoiceRefiner:
    def __init__(
        self,
        *,
        partial_runner: StageRunner | None = None,
        sentence_runner: StageRunner | None = None,
        final_runner: StageRunner | None = None,
        backend_name: str = "asr + deterministic_text_refiner",
    ) -> None:
        self.partial_runner = partial_runner
        self.sentence_runner = sentence_runner
        self.final_runner = final_runner
        self.backend_name = str(backend_name or "").strip() or "asr + deterministic_text_refiner"

    def refine_partial(self, text: str) -> str:
        return self._run(self.partial_runner, build_partial_fix_prompt(text), text)

    def refine_sentence(self, text: str) -> str:
        return self._run(self.sentence_runner, build_sentence_fix_prompt(text), text)

    def refine_final(self, text: str) -> str:
        return self._run(self.final_runner, build_final_polish_prompt(text), text)

    @staticmethod
    def _run(runner: StageRunner | None, prompt: str, text: str) -> str:
        if runner is None:
            return ""
        return str(runner(prompt, str(text or "").strip()) or "").strip()


def _normalize_text(text: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", str(text or "").strip())
    return normalized.strip()


def _clean_llm_output(text: str, fallback_text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    normalized = _THINK_TAG_RE.sub("", normalized).strip()
    if "用户原文" in normalized or "只输出处理后的文本" in normalized:
        return str(fallback_text or "").strip()
    if "\n" in normalized:
        normalized = normalized.splitlines()[-1].strip()
    return normalized.strip()


def _apply_common_partial_replacements(text: str) -> str:
    normalized = _normalize_text(text)
    for source, target in _COMMON_PARTIAL_REPLACEMENTS:
        normalized = normalized.replace(source, target)
    return normalized



# ── Regex pre-normalization ──
import re as _re_mod
_FILLER_START_RE = _re_mod.compile(
    r"^(?:就是说呢|然后就是说|就是说|就是)[，, ]*|"
    r"^(?:那个那个|这个这个|那个|这个|然后)[，, ]*|"
    r"^(?:嗯|呃|啊|哦|噢|呢|说)[，, ]*|"
    r"^(?:反正|其实|吧)[，, ]*|"
    r"^[，, ]+",
)

def _regex_normalize(text):
    if not text:
        return text
    prev = None
    while prev != text:
        prev = text
        text = _FILLER_START_RE.sub("", text)
    text = _re_mod.sub(r"^[说吧呢][，, ]*", "", text)
    # Remove middle filler phrases
    text = _re_mod.sub(r"[,， ]*(?:就是说呢|然后就是说|就是说|就是)[,， ]*", "，", text)
    text = _re_mod.sub(r"，，+", "，", text)
    text = _re_mod.sub(r"  +", " ", text)
    text = _re_mod.sub(r"^[，, ]+", "", text)
    return text.strip()



def _repair_asr_boundary_artifacts(text: str) -> str:
    """Repair high-confidence ASR/punctuation artifacts without broad rewriting."""
    normalized = str(text or "")
    replacements = (
        ("低空间", "低空经济"),
        ("中。中国", "中国"),
        ("中，中国", "中国"),
        ("中中国", "中国"),
        ("围绕一。下", "围绕以下"),
        ("围绕一，下", "围绕以下"),
        ("一。下几个", "以下几个"),
        ("一，下几个", "以下几个"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    normalized = _re_mod.sub(r"([一-龥])\s+([一-龥])", r"\1\2", normalized)
    normalized = _re_mod.sub(r"([。！？])([。！？])+", r"\1", normalized)
    normalized = _re_mod.sub(r"[，,、]\s*([。！？])", r"\1", normalized)
    return normalized.strip()


def _dedupe_repeated_text(text: str) -> str:
    """Collapse exact repeated halves commonly produced by cumulative ASR chunks."""
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    compact = _TRAILING_PUNCT_RE.sub("", normalized)
    mid = len(compact) // 2
    if len(compact) >= 12 and len(compact) % 2 == 0 and compact[:mid] == compact[mid:]:
        return compact[:mid].strip()
    parts = [part for part in re.split(r"(?<=[。！？!?])", normalized) if part.strip()]
    if len(parts) >= 2:
        half = len(parts) // 2
        if len(parts) % 2 == 0 and parts[:half] == parts[half:]:
            return "".join(parts[:half]).strip()
        if parts[-1].strip() == "".join(parts[:-1]).strip():
            return "".join(parts[:-1]).strip()
    return normalized

def _append_sentence_punctuation(text: str, *, ensure_final: bool = False) -> str:
    """Insert conservative punctuation; only final output gets a forced period."""
    normalized = _repair_asr_boundary_artifacts(_normalize_text(text))
    if not normalized:
        return ""
    normalized = _insert_sentence_breaks(normalized)
    normalized = _repair_asr_boundary_artifacts(normalized)
    if not ensure_final:
        return normalized
    normalized = _TRAILING_PUNCT_RE.sub("", normalized)
    return f"{normalized}。"


def _merge_fragments(text):
    """Merge short adjacent sentences: <10 chars joined with ，"""
    if not text:
        return text
    parts = [p.strip() for p in text.split('。') if p.strip()]
    if len(parts) <= 1:
        return text
    merged = []
    buf = []
    for p in parts:
        if len(p) < 10:
            buf.append(p)
        else:
            if buf:
                merged.append('，'.join(buf) + '。')
                buf = []
            merged.append(p + '。')
    if buf:
        merged.append('，'.join(buf) + '。')
    return ''.join(merged)

def _strip_fillers(text: str) -> str:
    normalized = _normalize_text(text)
    previous = None
    while normalized and previous != normalized:
        previous = normalized
        normalized = _FILLER_PREFIX_RE.sub("", normalized).strip()
    return normalized


def build_deterministic_stage_runner(stage: str) -> StageRunner:
    normalized_stage = str(stage or "").strip().lower()

    def _runner(_prompt: str, text: str) -> str:
        normalized = _apply_common_partial_replacements(text)
        if not normalized:
            return ""
        if normalized_stage == "partial":
            # partial: light corrections only, NO punctuation
            return normalized
        if normalized_stage == "sentence":
            return _append_sentence_punctuation(normalized, ensure_final=False)
        if normalized_stage == "final":
            cleaned = _repair_asr_boundary_artifacts(_regex_normalize(normalized))
            cleaned = _dedupe_repeated_text(_strip_fillers(cleaned))
            return _merge_fragments(_append_sentence_punctuation(cleaned, ensure_final=True))
        return normalized

    return _runner


_LIGHT_FILLER_RE = re.compile(
    r"(^|[，,。！？!?；;、\s])(?:呃|嗯|啊|额|这个|那个|就是说|就是)(?=([，,。！？!?；;、\s]|$))"
)
_LIGHT_DUP_PUNCT_RE = re.compile(r"([，,。！？!?；;、])\1+")
_LIGHT_SPACE_BETWEEN_CJK_RE = re.compile(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])")
_LIGHT_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?])")
_LIGHT_PROTECTED_TERMS = (
    "低空经济",
    "新兴产业方向",
    "中国重点布局",
)


def _light_rule_clean(text: str) -> str:
    """Conservative ASR cleanup before optional LLM polish.

    This intentionally avoids broad sentence insertion. It only removes obvious
    filler words, exact repeated text, duplicate punctuation, and a few
    high-confidence domain artifacts.
    """
    normalized = _normalize_text(text)
    if not normalized:
        return ""

    replacements = (
        ("然后就是说", "，"),
        ("就是说", ""),
        ("那个那个", "那个"),
        ("这个这个", "这个"),
        ("低空间经济", "低空经济"),
        ("低空间", "低空经济"),
        ("重点布局。，新兴产业方向", "重点布局的新兴产业方向"),
        ("重点布局。新兴产业方向", "重点布局的新兴产业方向"),
        ("重点布局，新兴产业方向", "重点布局的新兴产业方向"),
        ("重点布局的新型产业方向", "重点布局的新兴产业方向"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)

    previous = None
    while previous != normalized:
        previous = normalized
        normalized = _LIGHT_FILLER_RE.sub(lambda m: m.group(1) or "", normalized)

    normalized = _LIGHT_SPACE_BETWEEN_CJK_RE.sub(r"\1\2", normalized)
    normalized = _LIGHT_DUP_PUNCT_RE.sub(r"\1", normalized)
    normalized = re.sub(r"[，,、]\s*([。！？!?])", r"\1", normalized)
    normalized = normalized.replace("重点布局。，新兴产业方向", "重点布局的新兴产业方向")
    normalized = normalized.replace("重点布局。新兴产业方向", "重点布局的新兴产业方向")
    normalized = normalized.replace("重点布局，新兴产业方向", "重点布局的新兴产业方向")
    normalized = re.sub(r"^[，,。！？!?；;、\s]+", "", normalized)
    normalized = _dedupe_repeated_text(normalized.strip())
    normalized = _dedupe_light_sentence_sequence(normalized)
    return normalized.strip()


def _dedupe_light_sentence_sequence(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    compact = _TRAILING_PUNCT_RE.sub("", normalized)
    if len(compact) >= 12 and len(compact) % 2 == 0:
        mid = len(compact) // 2
        if compact[:mid] == compact[mid:]:
            return compact[:mid].strip()

    sentences = [part.strip() for part in _LIGHT_SENTENCE_SPLIT_RE.split(normalized) if part.strip()]
    if len(sentences) >= 2 and len(sentences) % 2 == 0:
        half = len(sentences) // 2
        if sentences[:half] == sentences[half:]:
            return "".join(sentences[:half]).strip()
    return normalized


def _looks_like_bad_llama_polish(candidate: str, source: str) -> bool:
    cleaned = str(candidate or "").strip()
    original = str(source or "").strip()
    if not cleaned:
        return True
    lowered = cleaned.lower()
    bad_markers = (
        "i cannot",
        "i can't",
        "please provide",
        "as an ai",
        "无法",
        "抱歉",
        "请提供",
        "原文：",
        "润色后：",
    )
    if any(marker in lowered for marker in bad_markers):
        return True
    if original and len(cleaned) < max(8, int(len(original) * 0.65)):
        return True
    for term in _LIGHT_PROTECTED_TERMS:
        if term in original and term not in cleaned:
            return True
    if "发展" not in original and "发展" in cleaned:
        return True
    return False


def _build_llama_cpp_light_prompt(text: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "你是中文语音转文字后处理器。只做轻量整理：去除明显口语词，"
                "删除连续重复，合并明显错误断句，补充必要标点。禁止摘要，"
                "禁止扩写，禁止改变原句顺序。无法确定的错词保持原样。只输出处理后的文本。"
            ),
        },
        {"role": "user", "content": str(text or "").strip()},
    ]


def build_llama_cpp_light_stage_runner() -> StageRunner:
    cfg = get_config() if isinstance(get_config(), dict) else {}
    llm_cfg = (cfg.get("llm") or {}) if isinstance(cfg, dict) else {}
    api_url = str(
        llm_cfg.get("llama_cpp_api_url")
        or os.environ.get("LLAMA_CPP_API_URL")
        or "http://127.0.0.1:8090/v1/chat/completions"
    ).strip()
    model = str(llm_cfg.get("llama_cpp_model") or "qwen3-0.6b-q4_k_m").strip()
    timeout_seconds = float(llm_cfg.get("voice_refine_timeout_seconds") or 6)
    max_tokens = int(llm_cfg.get("llama_cpp_voice_max_tokens") or 96)

    def _runner(_prompt: str, text: str) -> str:
        cleaned = _light_rule_clean(text)
        if not cleaned:
            return ""
        if len(cleaned) > 600:
            return cleaned
        try:
            response = requests.post(
                api_url,
                json={
                    "model": model,
                    "messages": _build_llama_cpp_light_prompt(cleaned),
                    "temperature": 0.1,
                    "top_p": 0.8,
                    "max_tokens": max_tokens,
                    "repeat_penalty": 1.15,
                    "presence_penalty": 0.2,
                    "stream": False,
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json() if response.content else {}
            choices = payload.get("choices") or []
            message = (choices[0].get("message") or {}) if choices else {}
            candidate = _clean_llm_output(str(message.get("content") or ""), cleaned)
            if _looks_like_bad_llama_polish(candidate, cleaned):
                return cleaned
            return _light_rule_clean(candidate)
        except Exception:
            return cleaned

    return _runner


def _voice_refiner_mode() -> str:
    explicit = str(os.environ.get("VOICE_REFINER_MODE") or "").strip().lower()
    if explicit:
        return explicit
    cfg = get_config() if isinstance(get_config(), dict) else {}
    llm_cfg = (cfg.get("llm") or {}) if isinstance(cfg, dict) else {}
    return str(llm_cfg.get("voice_refiner_mode") or "deterministic").strip().lower()


def build_http_stage_runner(*, timeout_seconds: float | None = None) -> StageRunner:
    llm_cfg = (get_config().get("llm") or {}) if isinstance(get_config(), dict) else {}
    base_url = str(llm_cfg.get("prompt_model_url") or "http://127.0.0.1:8001").rstrip("/")
    request_timeout = float(timeout_seconds or llm_cfg.get("prompt_timeout_seconds") or 12)

    def _runner(prompt: str, _text: str) -> str:
        response = requests.post(
            base_url + "/v1/completions",
            json={"prompt": str(prompt or ""), "stream": False},
            timeout=request_timeout,
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        return _clean_llm_output(str(payload.get("text") or ""), _text)

    return _runner


def build_default_voice_refiner() -> VoiceRefiner:
    mode = _voice_refiner_mode()
    if mode in {"http", "llm", "remote"}:
        shared_runner = build_http_stage_runner()
        return VoiceRefiner(
            partial_runner=shared_runner,
            sentence_runner=shared_runner,
            final_runner=shared_runner,
            backend_name="asr + 1.5b_text_refiner",
        )

    if mode in {"asr_only", "none", "off"}:
        # Pass-through: no polish at all
        _identity = lambda _prompt, text: str(text or "").strip()
        return VoiceRefiner(
            partial_runner=_identity,
            sentence_runner=_identity,
            final_runner=_identity,
            backend_name="asr (no refiner)",
        )

    if mode in {"llama_cpp_light", "llama-cpp-light", "qwen3_light"}:
        _light_runner = lambda _prompt, text: _light_rule_clean(text)
        return VoiceRefiner(
            partial_runner=_light_runner,
            sentence_runner=_light_runner,
            final_runner=build_llama_cpp_light_stage_runner(),
            backend_name="asr + light_rules + qwen3_0.6b_llama_cpp",
        )

    return VoiceRefiner(
        partial_runner=build_deterministic_stage_runner("partial"),
        sentence_runner=build_deterministic_stage_runner("sentence"),
        final_runner=build_deterministic_stage_runner("final"),
        backend_name="asr + deterministic_text_refiner",
    )
