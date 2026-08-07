import json
import unittest
from pathlib import Path


class ToolRegistryTests(unittest.TestCase):
    def test_registry_uses_transcribe_audio_for_asr_entry(self):
        path = Path(__file__).resolve().parents[1] / ".openclaw" / "tools" / "tool-registry.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        tool_names = {item["name"] for item in payload["tools"]}

        self.assertIn("transcribe_audio", tool_names)
        self.assertNotIn("recognize_audio", tool_names)

        asr_tool = next(item for item in payload["tools"] if item["name"] == "transcribe_audio")
        self.assertEqual("phase1-priority", asr_tool["status"])
        self.assertEqual("/api/v1/internal/asr", asr_tool["backend_endpoint"])
        self.assertTrue(asr_tool["requires_conversation_scope"])
        self.assertTrue(asr_tool["requires_user_scope"])

    def test_registry_declares_voice_sse_contracts_for_tts_and_asr(self):
        path = Path(__file__).resolve().parents[1] / ".openclaw" / "tools" / "tool-registry.json"
        payload = json.loads(path.read_text(encoding="utf-8"))

        tts_tool = next(item for item in payload["tools"] if item["name"] == "synthesize_speech")
        asr_tool = next(item for item in payload["tools"] if item["name"] == "transcribe_audio")

        self.assertEqual(["audio_start", "audio_done", "done"], tts_tool["sse_events"])
        self.assertEqual(["audio_start", "audio_done", "done"], asr_tool["sse_events"])

        tts_output = payload["definitions"]["tts_output"]
        self.assertEqual(["task_id", "audio_url", "mime_type", "audio_bytes"], tts_output["required"])

        asr_output = payload["definitions"]["transcribe_audio_output"]
        self.assertEqual(["text", "backend", "mode"], asr_output["required"])

    def test_document_render_docx_accepts_markdown_body_protocol(self):
        path = Path(__file__).resolve().parents[1] / ".openclaw" / "tools" / "tool-registry.json"
        payload = json.loads(path.read_text(encoding="utf-8"))

        tool_names = {item["name"] for item in payload["tools"]}
        self.assertIn("document_render_docx", tool_names)
        self.assertIn("document_task_status", tool_names)
        self.assertIn("download_url", tool_names)

        legacy = next(item for item in payload["tools"] if item["name"] == "generate_document")
        self.assertEqual("legacy-fallback", legacy["status"])

        render_tool = next(item for item in payload["tools"] if item["name"] == "document_render_docx")
        self.assertEqual("document-mainpath", render_tool["status"])
        self.assertEqual("/api/v1/internal/document-render-docx", render_tool["backend_endpoint"])

        doc_input = payload["definitions"]["document_render_docx_input"]
        properties = doc_input["properties"]

        self.assertIn("instruction", properties)
        self.assertIn("filename", properties)
        self.assertIn("content_type", properties)
        self.assertIn("content", properties)
        self.assertEqual(["markdown", "html", "plaintext"], properties["content_type"]["enum"])



    def test_registry_includes_local_small_model(self):
        path = Path(__file__).resolve().parents[1] / ".openclaw" / "tools" / "tool-registry.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        tool_names = {item["name"] for item in payload["tools"]}

        self.assertIn("local_small_model", tool_names)

        lsm_tool = next(item for item in payload["tools"] if item["name"] == "local_small_model")
        self.assertEqual("phase2-light-router", lsm_tool["status"])
        self.assertEqual("/api/v1/internal/local-small/generate", lsm_tool["backend_endpoint"])

        lsm_input = payload["definitions"]["local_small_model_input"]
        self.assertIn("prompt", lsm_input["properties"])
        self.assertIn("mode", lsm_input["properties"])
        self.assertEqual(["general", "voice_refine", "intent_normalize", "tool_args_refine"], lsm_input["properties"]["mode"]["enum"])

if __name__ == "__main__":
    unittest.main()
