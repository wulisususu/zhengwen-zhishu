"""FastAPI router — docs_pipeline v3 SSE endpoint."""
import logging
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.docs_pipeline.runner import run_pipeline_stream

logger = logging.getLogger(__name__)

router = APIRouter(tags=["docs-pipeline"])


class DocPipelineRequest(BaseModel):
    user_input: str = Field(..., min_length=5, description="文档主题")
    section_count: int = Field(default=6, ge=2, le=10, description="章节数")


@router.post("/docs-pipeline/generate")
async def docs_pipeline_generate(
    req: DocPipelineRequest,
    current_user=Depends(get_current_user),
):
    """新建文档生成任务，返回 SSE 流."""

    async def event_generator():
        async for sse in run_pipeline_stream(
            user_input=req.user_input,
            section_count=req.section_count,
            user_id=current_user.id,
        ):
            yield sse

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
