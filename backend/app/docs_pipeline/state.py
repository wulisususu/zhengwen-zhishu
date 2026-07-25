"""PipelineState — LangGraph 全局状态定义."""
from typing import TypedDict, Annotated
import operator


class PipelineState(TypedDict, total=False):
    """docs_pipeline v3 全局状态."""

    # === 输入 ===
    user_input: str
    section_count: int

    # === 节点 ① 输出 ===
    polished_title: str
    outline: dict

    # === 节点 ② 输出 ===
    chapter_prompts: list[dict]
    global_thread: str
    chapter_summaries: Annotated[list[str], operator.add]

    # === 节点 ③ 输出（Annotated 累加）===
    generated_chapters: Annotated[list[dict], operator.add]
    current_idx: int
    chapter_retries: dict

    # === 节点 ④ 输出 ===
    final_md: str
    docx_path: str
    docx_size: int
    docx_valid: bool
    render_retries: int

    # === 控制 ===
    status: str
    graceful_error: str | None
    task_id: str
    user_id: int


def initial_state(user_input: str, section_count: int = 6, task_id: str = "", user_id: int = 1) -> PipelineState:
    """构建初始 state."""
    return PipelineState(
        user_input=user_input,
        section_count=section_count,
        task_id=task_id,
        user_id=user_id,
        polished_title="",
        outline={},
        chapter_prompts=[],
        global_thread="",
        chapter_summaries=[],
        generated_chapters=[],
        current_idx=1,
        chapter_retries={},
        final_md="",
        docx_path="",
        docx_size=0,
        docx_valid=False,
        render_retries=0,
        status="polishing",
        graceful_error=None,
    )
