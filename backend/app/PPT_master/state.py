"""PipelineState for PPT-master pipeline."""
from typing import TypedDict, Annotated
import operator


class PipelineState(TypedDict, total=False):
    user_input: str
    page_count: int
    page_format: str
    sources: list[str]
    source_context: str
    source_manifest: list[dict]
    design_spec: str
    svg_pages: Annotated[list[dict], operator.add]
    project_dir: str
    pptx_path: str
    pptx_size: int
    pptx_valid: bool
    status: str
    graceful_error: str | None
    svg_security_errors: list[str]
    validation_result: dict
    pptx_structure_mode: str
    structured_workspace_id: str | None
    task_id: str
    user_id: int


def initial_state(
    user_input: str,
    page_count: int = 8,
    page_format: str = "ppt169",
    sources: list[str] | None = None,
    task_id: str = "",
    user_id: int = 1,
    source_context: str = "",
    source_manifest: list[dict] | None = None,
    pptx_structure_mode: str = "flat",
    structured_workspace_id: str | None = None,
) -> PipelineState:
    return PipelineState(
        user_input=user_input,
        page_count=page_count,
        page_format=page_format,
        sources=sources or [],
        source_context=source_context,
        source_manifest=source_manifest or [],
        design_spec="",
        svg_pages=[],
        project_dir="",
        pptx_path="",
        pptx_size=0,
        pptx_valid=False,
        status="starting",
        graceful_error=None,
        svg_security_errors=[],
        validation_result={"passed": False, "warnings": [], "errors": [], "blocking_errors": ["validation_not_run"]},
        pptx_structure_mode=pptx_structure_mode,
        structured_workspace_id=structured_workspace_id,
        task_id=task_id,
        user_id=user_id,
    )
