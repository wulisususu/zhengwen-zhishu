from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable

from app.services.openclaw_contracts import (
    validate_asr_stream_chunk,
    validate_final_polish,
    validate_partial_fix,
    validate_sentence_fix,
    validate_voice_input_completion,
)
from app.services.voice_refiner_prompts import (
    FINAL_POLISH_INSTRUCTION,
    PARTIAL_FIX_INSTRUCTION,
    SENTENCE_FIX_INSTRUCTION,
)


StageRunner = Callable[[str], str]

_STAGE_EXECUTOR = ThreadPoolExecutor(max_workers=4)
_SENTENCE_BOUNDARY_RE = re.compile(r"[。！？!?]\s*$")


class VoiceInputPipeline:
    def __init__(
        self,
        *,
        task_id: str,
        mode: str = "streaming_voice_input",
        backend: str = "asr + deterministic_text_refiner",
        partial_fix_runner: StageRunner | None = None,
        sentence_fix_runner: StageRunner | None = None,
        final_polish_runner: StageRunner | None = None,
        partial_fix_timeout_ms: int = 200,
        sentence_fix_timeout_ms: int = 500,
        final_polish_timeout_ms: int = 1500,
        sentence_pause_ms: int = 500,
        final_pause_ms: int = 2000,
        initial_revision_id: int = 0,
    ) -> None:
        self.task_id = str(task_id or "").strip()
        self.mode = str(mode or "").strip() or "streaming_voice_input"
        self.backend = str(backend or "").strip() or "asr + 1.5b_text_refiner"
        self.partial_fix_runner = partial_fix_runner
        self.sentence_fix_runner = sentence_fix_runner
        self.final_polish_runner = final_polish_runner
        self.partial_fix_timeout_ms = max(1, int(partial_fix_timeout_ms))
        self.sentence_fix_timeout_ms = max(1, int(sentence_fix_timeout_ms))
        self.final_polish_timeout_ms = max(1, int(final_polish_timeout_ms))
        self.sentence_pause_ms = max(0, int(sentence_pause_ms))
        self.final_pause_ms = max(self.sentence_pause_ms, int(final_pause_ms))

        self.started = False
        self.latest_revision_id = max(0, int(initial_revision_id or 0))
        self.current_raw_revision_id = 0
        self.current_provisional_revision_id = 0
        self.current_raw_text = ""
        self.current_provisional_text = ""
        self.committed_raw_segments: list[str] = []
        self.committed_sentence_segments: list[str] = []
        self.final_text = ""
        self.stages_seen: list[str] = []
        self.latency_ms = {
            "partial_fix_p95": 0,
            "sentence_fix_p95": 0,
            "final_polish_p95": 0,
        }

    def snapshot(self) -> dict[str, str | int]:
        return {
            "provisional_text": self._current_best_text(),
            "committed_sentence_text": self._join_segments(self.committed_sentence_segments),
            "final_text": self.final_text,
            "latest_revision_id": self.latest_revision_id,
        }

    def reset_segments(self) -> None:
        """Clear accumulated segments before processing final combined transcription."""
        self.committed_raw_segments.clear()
        self.committed_sentence_segments.clear()
        self.current_raw_text = ""
        self.current_provisional_text = ""
        self.current_raw_revision_id = 0
        self.current_provisional_revision_id = 0

    def start(self) -> list[dict]:
        if self.started:
            return []
        self.started = True
        return [
            {
                "type": "audio_start",
                "capability": "asr",
                "task_id": self.task_id,
                "mode": self.mode,
                "status": "running",
            }
        ]

    def push_raw_asr(self, text: str, *, is_final: bool = False) -> list[dict]:
        normalized_text = self._merge_chunk_text(str(text or "").strip(), is_final=is_final)
        if not normalized_text:
            return []
        revision_id, previous_revision_id = self._next_revision_pair()
        result = validate_asr_stream_chunk(
            task_id=self.task_id,
            revision_id=revision_id,
            text=normalized_text,
            is_final=is_final,
            previous_revision_id=previous_revision_id,
        )
        if result["status"] != "completed":
            return []
        self.latest_revision_id = revision_id
        self.current_raw_revision_id = revision_id
        self.current_provisional_revision_id = revision_id
        self.current_raw_text = normalized_text
        self.current_provisional_text = normalized_text
        self._remember_stage("raw_asr")
        return [self._build_audio_chunk_event(result["validated_payload"])]

    def push_partial_fix(self, text: str, *, source_revision_id: int) -> list[dict]:
        if int(source_revision_id or 0) != int(self.current_raw_revision_id or 0):
            return []
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return []
        revision_id, previous_revision_id = self._next_revision_pair()
        result = validate_partial_fix(
            task_id=self.task_id,
            revision_id=revision_id,
            text=normalized_text,
            source_revision_id=int(source_revision_id),
            previous_revision_id=previous_revision_id,
        )
        if result["status"] != "completed":
            return []
        self.latest_revision_id = revision_id
        self.current_provisional_revision_id = revision_id
        self.current_provisional_text = normalized_text
        self._remember_stage("partial_fix")
        return [self._build_audio_chunk_event(result["validated_payload"])]

    def push_sentence_fix(self, text: str, *, source_revision_id: int | None = None) -> list[dict]:
        active_revision_id = int(source_revision_id or self._active_revision_id() or 0)
        if active_revision_id != self._active_revision_id():
            return []
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return []
        revision_id, previous_revision_id = self._next_revision_pair()
        sentence_id = f"{self.task_id}-sentence-{len(self.committed_sentence_segments) + 1}"
        result = validate_sentence_fix(
            task_id=self.task_id,
            revision_id=revision_id,
            text=normalized_text,
            sentence_id=sentence_id,
            previous_revision_id=previous_revision_id,
        )
        if result["status"] != "completed":
            return []
        self.latest_revision_id = revision_id
        self._remember_stage("sentence_fix")
        self._commit_current_sentence(normalized_text)
        return [self._build_audio_chunk_event(result["validated_payload"])]

    def finalize(self, *, explicit: bool = False, pause_ms: int = 0) -> list[dict]:
        if not explicit and int(pause_ms or 0) < self.final_pause_ms:
            return []
        events: list[dict] = []
        if self.current_raw_text:
            current_text = self._current_best_text()
            self._commit_current_sentence(current_text)

        transcript = self._join_segments(self.committed_sentence_segments)
        raw_transcript = self._join_segments(self.committed_raw_segments)
        if not transcript or not raw_transcript:
            return events

        polished_text = transcript
        preview_text, elapsed_ms, completed = self._run_stage(
            stage="final_polish",
            text=transcript,
            runner=self.final_polish_runner,
            timeout_ms=self.final_polish_timeout_ms,
        )
        if completed:
            preview_events = self._push_final_polish_preview(preview_text)
            events.extend(preview_events)
            if preview_events:
                polished_text = preview_text

        self._record_latency("final_polish", elapsed_ms)
        completion_revision_id, _ = self._next_revision_pair()
        completion = validate_voice_input_completion(
            task_id=self.task_id,
            transcript=polished_text,
            raw_transcript=raw_transcript,
            mode=self.mode,
            backend=self.backend,
            stages=self._completion_stages(),
            latency_ms=dict(self.latency_ms),
            revision_id=completion_revision_id,
            done_seen=True,
        )
        if completion["status"] != "completed":
            return events

        self.latest_revision_id = completion_revision_id
        self.final_text = polished_text
        payload = dict(completion["validated_payload"])
        payload.pop("done_seen", None)
        payload["type"] = "audio_done"
        payload["status"] = "completed"
        events.append(payload)
        events.append({"type": "done", "content": polished_text, "status": "done"})
        return events

    def process_chunk(
        self,
        text: str,
        *,
        pause_ms: int = 0,
        is_final: bool = False,
        explicit_finalize: bool = False,
    ) -> list[dict]:
        events = self.start()
        raw_events = self.push_raw_asr(text, is_final=is_final)
        events.extend(raw_events)
        if not raw_events:
            return events

        raw_revision_id = self.current_raw_revision_id
        partial_text, partial_elapsed_ms, partial_completed = self._run_stage(
            stage="partial_fix",
            text=self.current_raw_text,
            runner=self.partial_fix_runner,
            timeout_ms=self.partial_fix_timeout_ms,
        )
        self._record_latency("partial_fix", partial_elapsed_ms)
        if partial_completed:
            events.extend(self.push_partial_fix(partial_text, source_revision_id=raw_revision_id))

        if self._should_commit_sentence(text=self._current_best_text(), pause_ms=pause_ms, is_final=is_final):
            source_text = self._current_best_text()
            source_revision_id = self._active_revision_id()
            sentence_text, sentence_elapsed_ms, sentence_completed = self._run_stage(
                stage="sentence_fix",
                text=source_text,
                runner=self.sentence_fix_runner,
                timeout_ms=self.sentence_fix_timeout_ms,
            )
            self._record_latency("sentence_fix", sentence_elapsed_ms)
            if sentence_completed:
                sentence_events = self.push_sentence_fix(sentence_text, source_revision_id=source_revision_id)
                events.extend(sentence_events)
                if not sentence_events:
                    self._commit_current_sentence(source_text)
            else:
                self._commit_current_sentence(source_text)

        if explicit_finalize or int(pause_ms or 0) >= self.final_pause_ms:
            events.extend(self.finalize(explicit=explicit_finalize, pause_ms=pause_ms))
        return events

    def process_pause(self, *, pause_ms: int = 0, explicit_finalize: bool = False) -> list[dict]:
        events = self.start()
        current_text = self._current_best_text()
        if current_text and self._should_commit_sentence(text=current_text, pause_ms=pause_ms, is_final=False):
            source_revision_id = self._active_revision_id()
            sentence_text, sentence_elapsed_ms, sentence_completed = self._run_stage(
                stage="sentence_fix",
                text=current_text,
                runner=self.sentence_fix_runner,
                timeout_ms=self.sentence_fix_timeout_ms,
            )
            self._record_latency("sentence_fix", sentence_elapsed_ms)
            if sentence_completed:
                sentence_events = self.push_sentence_fix(sentence_text, source_revision_id=source_revision_id)
                events.extend(sentence_events)
                if not sentence_events:
                    self._commit_current_sentence(current_text)
            else:
                self._commit_current_sentence(current_text)

        if explicit_finalize or int(pause_ms or 0) >= self.final_pause_ms:
            events.extend(self.finalize(explicit=explicit_finalize, pause_ms=pause_ms))
        return events

    def _push_final_polish_preview(self, text: str) -> list[dict]:
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return []
        revision_id, previous_revision_id = self._next_revision_pair()
        result = validate_final_polish(
            task_id=self.task_id,
            revision_id=revision_id,
            text=normalized_text,
            previous_revision_id=previous_revision_id,
        )
        if result["status"] != "completed":
            return []
        self.latest_revision_id = revision_id
        self._remember_stage("final_polish")
        return [self._build_audio_chunk_event(result["validated_payload"])]

    def _next_revision_pair(self) -> tuple[int, int]:
        previous_revision_id = int(self.latest_revision_id or 0)
        return previous_revision_id + 1, previous_revision_id

    def _active_revision_id(self) -> int:
        return int(self.current_provisional_revision_id or self.current_raw_revision_id or 0)

    def _current_best_text(self) -> str:
        return str(self.current_provisional_text or self.current_raw_text or "").strip()

    def _remember_stage(self, stage: str) -> None:
        if stage and stage not in self.stages_seen:
            self.stages_seen.append(stage)

    def _record_latency(self, stage: str, elapsed_ms: int) -> None:
        key = f"{stage}_p95"
        self.latency_ms[key] = max(int(self.latency_ms.get(key) or 0), int(elapsed_ms or 0))

    def _run_stage(
        self,
        *,
        stage: str,
        text: str,
        runner: StageRunner | None,
        timeout_ms: int,
    ) -> tuple[str, int, bool]:
        if runner is None:
            return "", 0, False
        started = time.monotonic()
        future = _STAGE_EXECUTOR.submit(runner, text)
        try:
            result = future.result(timeout=max(timeout_ms, 1) / 1000.0)
        except FutureTimeoutError:
            future.cancel()
            return "", int((time.monotonic() - started) * 1000), False
        except Exception:
            return "", int((time.monotonic() - started) * 1000), False
        elapsed_ms = int((time.monotonic() - started) * 1000)
        normalized = str(result or "").strip()
        return normalized, elapsed_ms, bool(normalized)

    def _should_commit_sentence(self, *, text: str, pause_ms: int, is_final: bool) -> bool:
        if not str(text or "").strip():
            return False
        if is_final:
            return True
        if int(pause_ms or 0) >= self.sentence_pause_ms:
            return True
        return bool(_SENTENCE_BOUNDARY_RE.search(str(text or "").strip()))

    def _commit_current_sentence(self, text: str) -> None:
        normalized_text = str(text or "").strip()
        normalized_raw_text = str(self.current_raw_text or "").strip()
        self._append_unique_segment(self.committed_raw_segments, normalized_raw_text)
        self._append_unique_segment(self.committed_sentence_segments, normalized_text)
        self.current_raw_text = ""
        self.current_provisional_text = ""
        self.current_raw_revision_id = 0
        self.current_provisional_revision_id = 0

    @staticmethod
    def _append_unique_segment(segments: list[str], text: str) -> None:
        normalized = str(text or "").strip()
        if not normalized:
            return
        committed = "".join(str(segment or "").strip() for segment in segments if str(segment or "").strip())
        if not committed:
            segments.append(normalized)
            return
        if normalized == committed or normalized in committed:
            return
        if committed in normalized:
            suffix = normalized[len(committed):].strip()
            if suffix:
                segments.append(suffix)
            return
        last = str(segments[-1] or "").strip() if segments else ""
        if normalized == last or last.endswith(normalized) or normalized.endswith(last):
            if len(normalized) > len(last):
                segments[-1] = normalized
            return
        segments.append(normalized)

    def _completion_stages(self) -> list[str]:
        stages = list(self.stages_seen)
        if self.final_polish_runner is not None and "final_polish" not in stages:
            stages.append("final_polish")
        return stages

    @staticmethod
    def _join_segments(segments: list[str]) -> str:
        return "".join(str(segment or "").strip() for segment in segments if str(segment or "").strip())

    @staticmethod
    def _build_audio_chunk_event(payload: dict) -> dict:
        event = dict(payload)
        event["type"] = "audio_chunk"
        return event

    def _merge_chunk_text(self, incoming_text: str, *, is_final: bool) -> str:
        normalized_incoming = str(incoming_text or "").strip()
        if not normalized_incoming:
            return ""
        current_text = str(self.current_raw_text or "").strip()
        if is_final and current_text:
            if normalized_incoming.startswith(current_text):
                return normalized_incoming
            if current_text.startswith(normalized_incoming):
                return current_text
            overlap_size = min(len(current_text), len(normalized_incoming))
            for size in range(overlap_size, 0, -1):
                if current_text.endswith(normalized_incoming[:size]):
                    return f"{current_text}{normalized_incoming[size:]}"
            return f"{current_text}{normalized_incoming}"
        if is_final:
            return normalized_incoming
        if not current_text:
            return normalized_incoming
        if normalized_incoming.startswith(current_text):
            return normalized_incoming
        if current_text.startswith(normalized_incoming):
            return current_text
        overlap_size = min(len(current_text), len(normalized_incoming))
        for size in range(overlap_size, 0, -1):
            if current_text.endswith(normalized_incoming[:size]):
                return f"{current_text}{normalized_incoming[size:]}"
        if len(normalized_incoming) >= len(current_text):
            return normalized_incoming
        return f"{current_text}{normalized_incoming}"
