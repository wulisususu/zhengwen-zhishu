"""公文起草、政策问答与文稿初稿生成共用的云端模型客户端（app.services.llm_chat）。

架构：不使用本地 NPU 推理，一律经既有云端政务 API（model_config.get_35b_config 的配置）调用。
回归：审查发现 2 —— 出口模式不允许时，同步与流式调用都不得发出请求。
"""
from unittest.mock import patch

import pytest

from app import config
from app.services import llm_chat, model_config
from app.services.model_policy import ModelPolicyError

CLOUD = "https://api.deepseek.com"
KEY = "test-placeholder-key"


@pytest.fixture()
def cloud(monkeypatch, tmp_path):
    """Cloud API configured the same way the settings page does (env / backend .env)."""
    for name in ("EXTERNAL_MODEL_BASE_URL", "EXTERNAL_MODEL_NAME", "EXTERNAL_MODEL_API_KEY", "DEEPSEEK_API_KEY",
                 "35B_BASE_URL", "35B_MODEL", "35B_API_KEY", "AI_BOX_MODEL_MODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(model_config, "ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setattr(model_config, "CONFIG_FILE", tmp_path / "missing.yaml")
    monkeypatch.setenv("EXTERNAL_MODEL_BASE_URL", CLOUD)
    monkeypatch.setenv("EXTERNAL_MODEL_NAME", "deepseek-chat")
    monkeypatch.setenv("EXTERNAL_MODEL_API_KEY", KEY)

    def set_mode(value: str, **llm):
        monkeypatch.setattr(config, "_config", {"model": {"mode": value}, "llm": llm})
    set_mode("cloud_allowed")
    return set_mode


class _Response:
    headers = {"Content-Type": "application/json"}

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "已生成"}}]}

    def close(self):
        return None


def test_cloud_api_is_called_with_the_shared_configuration(cloud):
    with patch.object(llm_chat.requests, "post", return_value=_Response()) as post:
        assert llm_chat.chat([{"role": "user", "content": "x"}]) == "已生成"
        assert list(llm_chat.stream([{"role": "user", "content": "x"}])) == ["已生成"]
    assert post.call_count == 2
    for call in post.call_args_list:
        assert call.args[0] == CLOUD + "/chat/completions"
        assert call.kwargs["headers"]["Authorization"] == "Bearer " + KEY
        assert call.kwargs["json"]["model"] == "deepseek-chat"
    assert "api_key" not in llm_chat.settings()           # 密钥不外露给调用方与日志


def test_old_local_model_setting_is_not_used(cloud):
    cloud("cloud_allowed", ollama_base_url="http://127.0.0.1:8001/v1", ollama_model="local-rkllm")
    with patch.object(llm_chat.requests, "post", return_value=_Response()) as post:
        llm_chat.chat([{"role": "user", "content": "x"}])
    assert post.call_args.args[0] == CLOUD + "/chat/completions"
    assert post.call_args.kwargs["json"]["model"] == "deepseek-chat"


@pytest.mark.parametrize("mode", ["offline", "intranet"])
def test_cloud_api_is_refused_before_any_request_when_mode_forbids(cloud, mode):
    cloud(mode)
    with patch.object(llm_chat.requests, "post") as post:
        with pytest.raises(ModelPolicyError):
            llm_chat.chat([{"role": "user", "content": "x"}])
        with pytest.raises(ModelPolicyError):
            list(llm_chat.stream([{"role": "user", "content": "x"}]))
    post.assert_not_called()


def test_missing_api_key_sends_nothing(cloud, monkeypatch):
    monkeypatch.delenv("EXTERNAL_MODEL_API_KEY")
    with patch.object(llm_chat.requests, "post") as post, pytest.raises(llm_chat.ModelNotConfigured):
        llm_chat.chat([{"role": "user", "content": "x"}])
    post.assert_not_called()


def test_gongwen_draft_falls_back_to_template_without_sending(cloud):
    from app.gongwen import service

    cloud("offline")
    with patch.object(llm_chat.requests, "post") as post:
        result = service.draft({"doc_type": "通知", "subject": "加强窗口作风建设", "recipients": "各科室"})
    post.assert_not_called()
    assert result["meta"]["generated_by"] == "template"
    assert "ModelPolicyError" in result["meta"]["error"]


def test_document_draft_generation_shares_the_cloud_client(cloud):
    from app.gov import generation

    with patch.object(llm_chat.requests, "post", return_value=_Response()) as post:
        assert generation.generate_text("起草要求") == {"text": "已生成"}
    assert post.call_args.args[0] == CLOUD + "/chat/completions"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer " + KEY
    cloud("intranet")
    with patch.object(llm_chat.requests, "post") as post, pytest.raises(ModelPolicyError):
        generation.generate_text("起草要求")
    post.assert_not_called()
