"""docs_pipeline v3 — LangGraph-based document generation pipeline.

0.6B outline + 0.6B chapter prompts + 3B per-chapter generation +
hallucination scanning + checkpoint resume + SSE streaming.
"""
from app.docs_pipeline.router import router
from app.docs_pipeline.runner import run_pipeline_stream
from app.docs_pipeline.state import PipelineState, initial_state

# Backward compatibility: v2 run_pipeline (used by document_tasks.py)
from app.docs_pipeline.core import run_pipeline

__all__ = [
    "router",
    "run_pipeline_stream",
    "run_pipeline",
    "PipelineState",
    "initial_state",
]
