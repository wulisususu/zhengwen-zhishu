import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.routers import asr as asr_router  # noqa: E402
from app.services.voice_input_pipeline import VoiceInputPipeline  # noqa: E402


class AsrRouterTests(unittest.TestCase):
    def setUp(self):
        asr_router._reset_voice_pipeline_sessions()

    @patch.dict("os.environ", {}, clear=False)
    @patch("app.routers.asr._cpu_transcribe", return_value="CPU识别结果")
    @patch("app.routers.asr._rknn_transcribe", side_effect=AssertionError("RKNN should not be used by default"))
    def test_preferred_transcribe_uses_cpu_by_default(self, _rknn_mock, _cpu_mock):
        text, backend = asr_router._preferred_transcribe("/tmp/demo.wav")

        self.assertEqual("CPU识别结果", text)
        self.assertEqual("cpu", backend)

    @patch.dict("os.environ", {"ASR_BACKEND": "rknn"}, clear=False)
    @patch("app.routers.asr._rknn_transcribe", return_value="NPU识别结果")
    def test_preferred_transcribe_can_use_rknn_when_explicitly_enabled(self, _rknn_mock):
        text, backend = asr_router._preferred_transcribe("/tmp/demo.wav")

        self.assertEqual("NPU识别结果", text)
        self.assertEqual("rknn", backend)

    def test_build_voice_input_pipeline_supports_internal_asr(self):
        pipeline = asr_router.build_voice_input_pipeline("internal_asr")

        self.assertIsInstance(pipeline, VoiceInputPipeline)
        self.assertTrue(str(pipeline.task_id).startswith("voice_"))

    @patch("app.routers.asr._preferred_transcribe", return_value=("我觉的这个方", "rknn"))
    @patch(
        "app.routers.asr.build_voice_input_pipeline",
        return_value=VoiceInputPipeline(
            task_id="voice_chunk_router_1",
            partial_fix_runner=lambda text: text.replace("觉的", "觉得"),
        ),
        create=True,
    )
    def test_recognize_saved_path_chunk_includes_additive_voice_events(self, _pipeline_mock, _transcribe_mock):
        payload = asr_router._recognize_saved_path("/tmp/demo.wav", "chunk")

        self.assertEqual("我觉得这个方", payload["text"])
        self.assertEqual("voice_chunk_router_1", payload["task_id"])
        self.assertIn("voice_events", payload)
        stages = [event.get("stage") for event in payload["voice_events"] if event.get("type") == "audio_chunk"]
        self.assertEqual(["raw_asr", "partial_fix"], stages)

    @patch("app.routers.asr._preferred_transcribe", return_value=("嗯 我觉得这个方案可以", "rknn"))
    @patch(
        "app.routers.asr.build_voice_input_pipeline",
        return_value=VoiceInputPipeline(
            task_id="voice_final_router_1",
            sentence_fix_runner=lambda text: text + "。",
            final_polish_runner=lambda text: text.replace("嗯 ", ""),
        ),
        create=True,
    )
    def test_recognize_saved_path_final_includes_audio_done_summary(self, _pipeline_mock, _transcribe_mock):
        payload = asr_router._recognize_saved_path("/tmp/demo.wav", "final")

        self.assertEqual("我觉得这个方案可以。", payload["text"])
        self.assertEqual("voice_final_router_1", payload["task_id"])
        self.assertEqual("audio_done", payload["voice_event"]["type"])
        self.assertEqual("我觉得这个方案可以。", payload["voice_event"]["transcript"])
        self.assertEqual("嗯 我觉得这个方案可以", payload["voice_event"]["raw_transcript"])

    @patch("app.routers.asr._preferred_transcribe", return_value=("嗯 我觉得这个方案可以", "rknn"))
    def test_recognize_saved_path_internal_asr_uses_enhanced_final_pipeline(self, _transcribe_mock):
        payload = asr_router._recognize_saved_path("/tmp/demo.wav", "internal_asr")

        self.assertEqual("internal_asr", payload["mode"])
        self.assertIn("voice_events", payload)
        self.assertIn("voice_event", payload)
        self.assertEqual("audio_done", payload["voice_event"]["type"])
        self.assertEqual("asr", payload["voice_event"]["capability"])
        self.assertEqual("internal_asr", payload["voice_event"]["mode"])
        self.assertEqual(payload["text"], payload["voice_event"]["transcript"])

    @patch("app.routers.asr._preferred_transcribe", return_value=("你好，世界", "rknn"))
    def test_recognize_saved_path_legacy_keeps_original_shape(self, _transcribe_mock):
        payload = asr_router._recognize_saved_path("/tmp/demo.wav", "legacy")

        self.assertEqual("你好，世界", payload["text"])
        self.assertEqual("legacy", payload["mode"])
        self.assertEqual("rknn", payload["backend"])
        self.assertNotIn("voice_events", payload)

    @patch("app.routers.asr._preferred_transcribe", side_effect=[("我觉的这个", "rknn"), ("方案可以", "rknn")])
    @patch(
        "app.routers.asr.build_default_voice_refiner",
        return_value=type(
            "StubRefiner",
            (),
            {
                "refine_partial": staticmethod(lambda text: text.replace("觉的", "觉得")),
                "refine_sentence": staticmethod(lambda text: text),
                "refine_final": staticmethod(lambda text: text),
            },
        )(),
    )
    def test_recognize_saved_path_chunk_session_reuses_task_id_and_advances_revision(self, _refiner_mock, _transcribe_mock):
        first = asr_router._recognize_saved_path("/tmp/demo.wav", "chunk", session_id="voice-session-1")
        second = asr_router._recognize_saved_path("/tmp/demo.wav", "chunk", session_id="voice-session-1")

        self.assertEqual(first["task_id"], second["task_id"])
        self.assertLess(first["voice_state"]["latest_revision_id"], second["voice_state"]["latest_revision_id"])
        self.assertEqual("我觉得这个方案可以", second["voice_state"]["provisional_text"])

    @patch("app.routers.asr.build_default_voice_refiner")
    def test_advance_voice_session_can_trigger_sentence_fix_on_pause(self, _refiner_mock):
        pipeline = VoiceInputPipeline(
            task_id="voice_chunk_router_1",
            partial_fix_runner=lambda text: text.replace("觉的", "觉得"),
            sentence_fix_runner=lambda text: text + "。",
        )
        asr_router._VOICE_PIPELINES["voice-session-2"] = pipeline
        pipeline.process_chunk("我觉的这个方案可以", pause_ms=0)

        payload = asr_router._advance_voice_session("voice-session-2", pause_ms=600)

        self.assertEqual("voice_chunk_router_1", payload["task_id"])
        self.assertEqual("我觉得这个方案可以。", payload["text"])
        stages = [event.get("stage") for event in payload["voice_events"] if event.get("type") == "audio_chunk"]
        self.assertEqual(["sentence_fix"], stages)


if __name__ == "__main__":
    unittest.main()
