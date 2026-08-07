"""Unit tests for local_small_model service."""
import unittest
from unittest.mock import patch, MagicMock
import requests


def _mock_config(enabled=True, url="http://127.0.0.1:8001", timeout=12, max_prompt=2000, max_output=1000, api_url=""):
    return {
        "llm": {
            "local_small_model_enabled": enabled,
            "prompt_model_url": url,
            "local_small_model_api_url": api_url,
            "local_small_model_name": "qwen2.5-1.5b-rkllm" if api_url else "deepseek-r1-1.5b-rk3588",
            "prompt_timeout_seconds": timeout,
            "local_small_model_max_prompt_chars": max_prompt,
            "local_small_model_max_output_chars": max_output,
        }
    }


class TestCleanOutput(unittest.TestCase):
    def test_strips_think_tags(self):
        from app.services.local_small_model import clean_local_small_output
        self.assertEqual(clean_local_small_output("<think>reasoning</think>hello"), "hello")

    def test_strips_open_think(self):
        from app.services.local_small_model import clean_local_small_output
        self.assertEqual(clean_local_small_output("<think>partial"), "partial")

    def test_collapses_triple_newlines(self):
        from app.services.local_small_model import clean_local_small_output
        result = clean_local_small_output("a\n\n\n\nb")
        self.assertNotIn("\n\n\n", result)

    def test_strips_whitespace(self):
        from app.services.local_small_model import clean_local_small_output
        self.assertEqual(clean_local_small_output("  hello  "), "hello")


class TestGenerate(unittest.TestCase):
    @patch("app.services.local_small_model.get_config")
    @patch("app.services.local_small_model.requests.post")
    def test_normal_return(self, mock_post, mock_cfg):
        mock_cfg.return_value = _mock_config()
        resp = MagicMock()
        resp.json.return_value = {"text": "cleaned text", "gen_s": 0.5, "tokens": 10}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        from app.services.local_small_model import generate
        result = generate("hello world", mode="general")

        self.assertEqual(result["text"], "cleaned text")
        self.assertEqual(result["source"], "local-small")
        self.assertFalse(result["fallback"])
        self.assertEqual(result["mode"], "general")

    @patch("app.services.local_small_model.get_config")
    @patch("app.services.local_small_model.requests.post")
    def test_empty_output_fallback(self, mock_post, mock_cfg):
        mock_cfg.return_value = _mock_config()
        resp = MagicMock()
        resp.json.return_value = {"text": ""}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        from app.services.local_small_model import generate
        result = generate("test input")

        self.assertTrue(result["fallback"])
        self.assertEqual(result["text"], "test input")
        self.assertIn("empty", result["error"])

    @patch("app.services.local_small_model.get_config")
    @patch("app.services.local_small_model.requests.post")
    def test_timeout_fallback(self, mock_post, mock_cfg):
        mock_cfg.return_value = _mock_config()
        mock_post.side_effect = requests.exceptions.Timeout("timed out")

        from app.services.local_small_model import generate
        result = generate("test input")

        self.assertTrue(result["fallback"])
        self.assertIn("timeout", result["error"])

    @patch("app.services.local_small_model.get_config")
    @patch("app.services.local_small_model.requests.post")
    def test_connection_error_fallback(self, mock_post, mock_cfg):
        mock_cfg.return_value = _mock_config()
        mock_post.side_effect = requests.exceptions.ConnectionError("refused")

        from app.services.local_small_model import generate
        result = generate("test input")

        self.assertTrue(result["fallback"])
        self.assertIn("unavailable", result["error"])

    @patch("app.services.local_small_model.get_config")
    @patch("app.services.local_small_model.requests.post")
    def test_think_tags_cleaned(self, mock_post, mock_cfg):
        mock_cfg.return_value = _mock_config()
        resp = MagicMock()
        resp.json.return_value = {"text": "<think>internal reasoning</think>final answer"}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        from app.services.local_small_model import generate
        result = generate("test")

        self.assertEqual(result["text"], "final answer")
        self.assertFalse(result["fallback"])

    @patch("app.services.local_small_model.get_config")
    @patch("app.services.local_small_model.requests.post")
    def test_output_truncated(self, mock_post, mock_cfg):
        mock_cfg.return_value = _mock_config(max_output=20)
        resp = MagicMock()
        resp.json.return_value = {"text": "a" * 100}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        from app.services.local_small_model import generate
        result = generate("test")

        self.assertEqual(len(result["text"]), 20)

    @patch("app.services.local_small_model.get_config")
    def test_invalid_mode_returns_error(self, mock_cfg):
        mock_cfg.return_value = _mock_config()

        from app.services.local_small_model import generate
        result = generate("test", mode="invalid_mode")

        self.assertTrue(result["fallback"])
        self.assertIn("invalid mode", result["error"])

    @patch("app.services.local_small_model.get_config")
    def test_disabled_returns_fallback(self, mock_cfg):
        mock_cfg.return_value = _mock_config(enabled=False)

        from app.services.local_small_model import generate
        result = generate("test")

        self.assertTrue(result["fallback"])
        self.assertIn("disabled", result["error"])

    @patch("app.services.local_small_model.get_config")
    @patch("app.services.local_small_model.requests.post")
    def test_voice_refine_mode(self, mock_post, mock_cfg):
        mock_cfg.return_value = _mock_config()
        resp = MagicMock()
        resp.json.return_value = {"text": "refined output"}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        from app.services.local_small_model import generate
        result = generate("口语化输入", mode="voice_refine")

        self.assertEqual(result["mode"], "voice_refine")
        self.assertEqual(result["text"], "refined output")
        call_args = mock_post.call_args
        sent = call_args[1]["json"]["prompt"]
        self.assertIn("整理语音文本", sent)

    @patch("app.services.local_small_model.get_config")
    @patch("app.services.local_small_model.requests.post")
    def test_generate_uses_qwen_chat_completions_when_api_url_configured(self, mock_post, mock_cfg):
        mock_cfg.return_value = _mock_config(api_url="http://127.0.0.1:8088/v1/chat/completions")
        resp = MagicMock()
        resp.json.return_value = {
            "choices": [
                {"message": {"role": "assistant", "content": "整理后的内容"}}
            ]
        }
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        from app.services.local_small_model import generate
        result = generate("口语化输入", mode="tool_args_refine", max_tokens=64)

        self.assertEqual(result["text"], "整理后的内容")
        self.assertEqual(result["model"], "qwen2.5-1.5b-rkllm")
        self.assertFalse(result["fallback"])
        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], "http://127.0.0.1:8088/v1/chat/completions")
        sent = call_args[1]["json"]
        self.assertIn("messages", sent)
        self.assertEqual(sent["model"], "qwen2.5-1.5b-rkllm")
        self.assertEqual(sent["max_tokens"], 64)

    @patch("app.services.local_small_model.get_config")
    @patch("app.services.local_small_model.requests.post")
    def test_intent_normalize_prompt_stays_short_for_qwen_rkllm(self, mock_post, mock_cfg):
        mock_cfg.return_value = _mock_config(api_url="http://127.0.0.1:8088/v1/chat/completions")
        resp = MagicMock()
        resp.json.return_value = {
            "choices": [
                {"message": {"role": "assistant", "content": "生成月度运营报告"}}
            ]
        }
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        from app.services.local_small_model import generate
        generate("请用一句话总结：生成月度运营报告。", mode="intent_normalize", max_tokens=32)

        sent_prompt = mock_post.call_args[1]["json"]["messages"][0]["content"]
        self.assertIn("请用一句话概括", sent_prompt)
        self.assertNotIn("请判断下面用户输入的核心意图", sent_prompt)


if __name__ == "__main__":
    unittest.main()
