"""PI Agent 降级链路测试."""
import os
import pytest
import asyncio
from unittest.mock import patch, AsyncMock

from app.services.pi_agent_client.base_client import health_check, PiAgentClient
from app.services.pi_agent_client.degradation import (
    _use_pi_agent_chat,
    _use_pi_agent_doc,
)


class TestHealthCheck:
    """健康检查测试."""

    @pytest.mark.asyncio
    async def test_health_check_unreachable(self):
        """不可达地址返回 False."""
        result = await health_check("http://127.0.0.1:19999/health", timeout=1.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_timeout(self):
        """超时返回 False — 使用 TEST-NET 不可路由 IP."""
        result = await health_check("http://192.0.2.1:8081/health", timeout=0.5)
        assert result is False


class TestFeatureFlags:
    """Feature Flag 测试."""

    def test_default_disabled_chat(self):
        """默认 PI_AGENT_CHAT 关闭."""
        os.environ.pop("PI_AGENT_CHAT", None)
        assert _use_pi_agent_chat() is False

    def test_default_disabled_doc(self):
        """默认 PI_AGENT_DOC 关闭."""
        os.environ.pop("PI_AGENT_DOC", None)
        assert _use_pi_agent_doc() is False

    def test_env_enabled_chat(self):
        """PI_AGENT_CHAT=true 启用."""
        os.environ["PI_AGENT_CHAT"] = "true"
        assert _use_pi_agent_chat() is True
        os.environ.pop("PI_AGENT_CHAT", None)


class TestDegradation:
    """降级链测试."""

    @pytest.mark.asyncio
    async def test_chat_degradation_fallback(self):
        """Chat: PI Agent 不可用时走降级到 llm_client."""
        from app.services.pi_agent_client.degradation import chat_with_degradation

        frames = []
        async for frame in chat_with_degradation(
            content="你好",
            user_id=1,
            conversation_id=1,
            message_id=1,
        ):
            frames.append(frame)
        assert len(frames) > 0
        assert any("[DONE]" in f for f in frames)

    @pytest.mark.asyncio
    async def test_doc_degradation_pipeline(self):
        """Doc: mock run_pipeline_stream 验证降级链包装与 [DONE] 帧."""
        async def mock_pipeline(user_input, section_count=6, task_id=None, user_id=1):
            yield "data: {\"type\": \"pipeline\", \"content\": \"mock\"}\n\n"

        # run_pipeline_stream 是 lazy import，需要 mock 在真实模块位置
        with patch(
            "app.docs_pipeline.runner.run_pipeline_stream",
            side_effect=mock_pipeline,
        ):
            from app.services.pi_agent_client.degradation import doc_with_degradation

            frames = []
            async for frame in doc_with_degradation(
                content="写一份周报",
                user_id=1,
                conversation_id=1,
                message_id=1,
            ):
                frames.append(frame)
            joined = "".join(frames)
            assert len(frames) > 0, f"Expected frames, got {len(frames)}"
            assert "[DONE]" in joined, f"Expected [DONE] in frames: {repr(frames[:3])}"


    def test_chat_user_event_includes_knowledge_docs(self):
        """Knowledge attachments are returned in the PI Agent user SSE event."""
        import json
        from app.services.pi_agent_client.degradation import chat_with_degradation

        knowledge_docs = [{"doc_id": 7, "filename": "reference.pdf", "file_type": "pdf"}]

        async def collect_user_frame():
            async for frame in chat_with_degradation(
                content="Use the attachment",
                user_id=1,
                conversation_id=1,
                message_id=1,
                msg_knowledge_docs=knowledge_docs,
            ):
                return frame

        payload = json.loads(asyncio.run(collect_user_frame()).removeprefix("data: ").strip())
        assert payload["type"] == "user"
        assert payload["knowledge_docs"] == knowledge_docs
