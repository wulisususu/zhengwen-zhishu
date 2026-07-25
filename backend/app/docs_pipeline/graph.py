"""LangGraph StateGraph 构建 — docs_pipeline v3."""
import logging
import os
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver

from app.docs_pipeline.state import PipelineState
from app.docs_pipeline.nodes import (
    polish_outline_node,
    build_chapter_prompts_node,
    generate_next_chapter_node,
    assemble_render_validate_node,
)

logger = logging.getLogger(__name__)


def _should_continue_generating(state: PipelineState) -> str:
    """条件路由：是否还有剩余章节."""
    if state["current_idx"] <= state["section_count"]:
        return "generate_chapter"
    return "render_validate"


def _should_retry_render(state: PipelineState) -> str:
    """条件路由：渲染是否成功."""
    if state["docx_valid"]:
        return END
    if state.get("render_retries", 0) < 2:
        return "render_validate"
    return END  # graceful_fallback


def build_graph() -> StateGraph:
    """构建并编译 StateGraph（使用 InMemorySaver 做 checkpoint）."""
    builder = StateGraph(PipelineState)

    # 注册节点
    builder.add_node("polish_outline", polish_outline_node)
    builder.add_node("build_prompts", build_chapter_prompts_node)
    builder.add_node("generate_chapter", generate_next_chapter_node)
    builder.add_node("render_validate", assemble_render_validate_node)

    # 边
    builder.set_entry_point("polish_outline")
    builder.add_edge("polish_outline", "build_prompts")
    builder.add_edge("build_prompts", "generate_chapter")

    # 条件边：章节循环
    builder.add_conditional_edges(
        "generate_chapter",
        _should_continue_generating,
        {
            "generate_chapter": "generate_chapter",
            "render_validate": "render_validate",
        },
    )

    # 条件边：渲染重试
    builder.add_conditional_edges(
        "render_validate",
        _should_retry_render,
        {
            "render_validate": "render_validate",
            END: END,
        },
    )

    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    logger.info("Graph compiled with InMemorySaver")
    return graph
