"""llm_chat（公文起草与政策问答共用的模型客户端）必须遵守 model_policy 出口模式。

回归：审查发现 2 —— 离线模式下配置公网地址，同步与流式调用仍会发出 POST。
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import config
from app.services import llm_chat
from app.services.model_policy import ModelPolicyError

PUBLIC = "https://8.8.8.8/v1"
INTRANET = "http://192.168.10.5:8001/v1"
LOOPBACK = "http://127.0.0.1:8001/v1"


@pytest.fixture()
def mode(monkeypatch):
    monkeypatch.delenv("AI_BOX_MODEL_MODE", raising=False)

    def set_mode(value: str, url: str):
        monkeypatch.setattr(config, "_config", {"model": {"mode": value}, "llm": {"ollama_base_url": url}})
    return set_mode


def _ok_response():
    return SimpleNamespace(raise_for_status=lambda: None, headers={"Content-Type": "application/json"},
                           json=lambda: {"choices": [{"message": {"content": "已生成"}}]}, close=lambda: None)


@pytest.mark.parametrize("value,url", [("offline", PUBLIC), ("offline", INTRANET), ("intranet", PUBLIC)])
def test_sync_call_is_refused_before_any_request(mode, value, url):
    mode(value, url)
    with patch.object(llm_chat.requests, "post") as post, pytest.raises(ModelPolicyError):
        llm_chat.chat([{"role": "user", "content": "x"}])
    post.assert_not_called()


@pytest.mark.parametrize("value,url", [("offline", PUBLIC), ("intranet", PUBLIC)])
def test_stream_call_is_refused_before_any_request(mode, value, url):
    mode(value, url)
    with patch.object(llm_chat.requests, "post") as post, pytest.raises(ModelPolicyError):
        list(llm_chat.stream([{"role": "user", "content": "x"}]))
    post.assert_not_called()


@pytest.mark.parametrize("value,url", [("offline", LOOPBACK), ("intranet", INTRANET), ("intranet", LOOPBACK), ("cloud_allowed", PUBLIC)])
def test_allowed_endpoints_still_work(mode, value, url):
    mode(value, url)
    with patch.object(llm_chat.requests, "post", return_value=_ok_response()) as post:
        assert llm_chat.chat([{"role": "user", "content": "x"}]) == "已生成"
        assert list(llm_chat.stream([{"role": "user", "content": "x"}])) == ["已生成"]
    assert post.call_count == 2 and post.call_args_list[0].args[0].startswith(url.rstrip("/"))


def test_gongwen_draft_falls_back_to_template_without_sending(mode):
    from app.gongwen import service

    mode("offline", PUBLIC)
    with patch.object(llm_chat.requests, "post") as post:
        result = service.draft({"doc_type": "通知", "subject": "加强窗口作风建设", "recipients": "各科室"})
    post.assert_not_called()
    assert result["meta"]["generated_by"] == "template"
    assert "ModelPolicyError" in result["meta"]["error"]
