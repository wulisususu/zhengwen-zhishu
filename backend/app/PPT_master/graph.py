"""LangGraph StateGraph for PPT-master pipeline."""
import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver

from app.PPT_master.state import PipelineState
from app.PPT_master.nodes import (
    parse_node,
    source_md_node,
    spec_node,
    svg_node,
    validate_node,
    export_node,
)

logger = logging.getLogger(__name__)


def build_graph() -> StateGraph:
    builder = StateGraph(PipelineState)

    builder.add_node("parse", parse_node)
    builder.add_node("source_md", source_md_node)
    builder.add_node("spec", spec_node)
    builder.add_node("svg", svg_node)
    builder.add_node("validate", validate_node)
    builder.add_node("export", export_node)

    builder.set_entry_point("parse")
    builder.add_edge("parse", "source_md")
    builder.add_edge("source_md", "spec")
    builder.add_edge("spec", "svg")
    builder.add_edge("svg", "validate")
    builder.add_edge("validate", "export")
    builder.add_edge("export", END)

    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)
    logger.info("PPT-master graph compiled (6 nodes)")
    return graph
