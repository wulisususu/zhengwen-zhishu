"""PI Agent 客户端 — Chat + Document 双模块通信层."""

from app.services.pi_agent_client.base_client import PiAgentClient, health_check
from app.services.pi_agent_client.chat_client import call_chat_agent
from app.services.pi_agent_client.doc_client import call_doc_agent
from app.services.pi_agent_client.degradation import (
    chat_with_degradation,
    doc_with_degradation,
    _use_pi_agent_chat,
    _use_pi_agent_doc,
)

__all__ = [
    "PiAgentClient",
    "health_check",
    "call_chat_agent",
    "call_doc_agent",
    "chat_with_degradation",
    "doc_with_degradation",
    "_use_pi_agent_chat",
    "_use_pi_agent_doc",
]
