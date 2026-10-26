"""Policy retrieval (T1): search and sync policy documents from the gov.cn
policy library into a local SQLite store.

Entry point: :func:`get_policy_service`. Contract: backend/docs/policy-api.md.
"""
from app.services.policy.errors import PolicyError
from app.services.policy.service import PolicyRetrievalService, get_policy_service

__all__ = ["PolicyError", "PolicyRetrievalService", "get_policy_service"]
