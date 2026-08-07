from __future__ import annotations
import re

_TRAILING_PUNCT_RE = re.compile(r'[。！？!?；;，,、]+$')
_CJK_SPACE_RE = re.compile(r'(?<=[一-鿿㐀-䶿])\s+(?=[一-鿿㐀-䶿])')

# Trigger words for comma insertion (natural break points, NO period)
_COMMA_TRIGGERS = (
    "但是", "可是", "然而", "而且", "并且", "同时", "不过", "虽然", "即使",
    "所以", "因此", "然后", "接着", "于是",
    "比如", "例如", "也就是说", "换句话说",
    "其中", "另外", "此外", "除此之外", "与此同时",
    "最后", "特别是", "尤其是", "具体来说", "总的来说",
    "嗯", "呃", "那个", "就是说",
)
_COMMA_TRIGGER_RE = re.compile(
    r"(?<=.)(?=("
    + "|".join(re.escape(t) for t in sorted(set(_COMMA_TRIGGERS), key=len, reverse=True))
    + r"))"
)
# Mid-text filler words to replace with comma
_FILLER_MID_RE = re.compile(r"[,， ]*(?:嗯|呃|啊|哦|噢)[,， ]*")


def _normalize_asr_text(text: str) -> str:
    """Post-process raw ASR output: remove CJK spaces, add commas at natural breaks, avoid periods."""
    t = str(text or "").strip()
    if not t:
        return t
    # 1. Remove spaces between CJK characters (raw Paraformer token format)
    prev = None
    while prev != t:
        prev = t
        t = _CJK_SPACE_RE.sub("", t)
    # 2. Remove mid-text filler words, replace with comma
    t = _FILLER_MID_RE.sub("，", t)
    # 3. Remove filler words at start of text
    t = re.sub(r"^[嗯呃啊那个就是然后说]+[，, ]*", "", t)
    # 4. Insert commas before trigger words (but NOT at position 0)
    t = _COMMA_TRIGGER_RE.sub("，", t)
    # 5. Clean up: collapse multiple commas, remove comma before existing punctuation
    t = re.sub(r"，，+", "，", t)
    t = re.sub(r"[,，]\s*([。！？!?])", r"", t)
    # 6. Remove trailing punctuation (we only want commas inside, not periods at end)
    t = _TRAILING_PUNCT_RE.sub("", t)
    return t.strip()



def _pick_voice_text(payload: dict, events: list[dict]) -> str:
    completion_event = next((event for event in reversed(events) if event.get("type") == "audio_done"), None)
    if completion_event:
        transcript = str(completion_event.get("transcript") or "").strip()
        if transcript:
            return transcript
    snapshot = payload.get("voice_state") or {}
    for key in ("final_text", "committed_sentence_text", "provisional_text"):
        text = str(snapshot.get(key) or "").strip()
        if text:
            return text
    return str(payload.get("text") or "").strip()


def recognize_saved_path(file_path: str, response_kind: str, transcribe_fn, *, pipeline=None) -> dict:
    text, backend = transcribe_fn(file_path)
    # Normalize ASR output: merge CJK spaces, add commas at breaks, avoid periods
    text = _normalize_asr_text(text)
    payload = {"text": text, "mode": response_kind, "backend": backend}
    if pipeline is None:
        return payload

    normalized_kind = str(response_kind or "").strip().lower()
    if normalized_kind == "final":
        # B2 fix: use combined WAV text, replace (not append) accumulated chunk texts
        pipeline.reset_segments()
        events = pipeline.process_chunk(text, pause_ms=pipeline.final_pause_ms, is_final=True, explicit_finalize=True)
    else:
        events = pipeline.process_chunk(text, pause_ms=0, is_final=False, explicit_finalize=False)

    payload["voice_events"] = events
    payload["voice_state"] = pipeline.snapshot()
    payload["task_id"] = str(getattr(pipeline, "task_id", "") or "").strip()
    completion_event = next((event for event in reversed(events) if event.get("type") == "audio_done"), None)
    if completion_event:
        payload["voice_event"] = completion_event
    payload["text"] = _pick_voice_text(payload, events)
    return payload
