"""LangGraph pipeline runner — astream + asyncio.Queue → SSE generator."""
import asyncio
import logging
import uuid
from datetime import datetime

from app.docs_pipeline.state import PipelineState, initial_state
from app.docs_pipeline.graph import build_graph
from app.docs_pipeline.nodes import set_sse_queue

logger = logging.getLogger(__name__)

_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run_pipeline_stream(
    user_input: str,
    section_count: int = 6,
    task_id: str | None = None,
    user_id: int = 1,
) -> str:
    """Run LangGraph pipeline, yield SSE event strings.

    Usage::

        @router.post("/generate")
        async def generate(req: Request):
            async def event_gen():
                async for sse in run_pipeline_stream(req.user_input):
                    yield sse
            return StreamingResponse(event_gen(), media_type="text/event-stream")
    """
    if task_id is None:
        task_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]

    state = initial_state(user_input, section_count, task_id, user_id)
    graph = _get_graph()
    queue = asyncio.Queue(maxsize=4)

    # 注入 queue 到 context（节点通过 get_sse_queue() 获取）
    set_sse_queue(queue)

    # 后台跑 graph
    graph_task = asyncio.ensure_future(_run_graph(state, graph, queue, task_id))

    # 从 queue 取事件 → SSE 字符串
    try:
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=600)
            if event is None:
                break

            if event["type"] in ("done", "fallback"):
                _handle_terminal_event(event)
                yield _format_terminal_sse(event)
                break
            else:
                from app.docs_pipeline.sse_bridge import make_sse_event
                yield make_sse_event(event["type"], event["data"])

    except asyncio.TimeoutError:
        from app.docs_pipeline.sse_bridge import make_sse_event
        yield make_sse_event("fallback", {"message": "生成超时，请稍后重试"})
    finally:
        if not graph_task.done():
            graph_task.cancel()

    logger.info("Pipeline stream ended for task %s", task_id)


async def _run_graph(state: PipelineState, graph, queue: asyncio.Queue, task_id: str):
    """Execute graph.astream, push terminal events to queue."""
    try:
        config = {"configurable": {"thread_id": task_id}}
        async for chunk in graph.astream(state, config, stream_mode="updates"):
            for node_name, node_state in chunk.items():
                logger.debug("Node %s completed for task %s", node_name, task_id)

                status = node_state.get("status", "")
                if status == "done":
                    await queue.put({"type": "done", "data": node_state})
                elif status == "graceful_fallback":
                    await queue.put({"type": "fallback", "data": node_state})

        # 如果正常结束但没收到 done/fallback，手动推 done
        await queue.put({"type": "done", "data": state})

    except Exception as e:
        logger.exception("Graph execution failed for task %s: %s", task_id, e)
        await queue.put({
            "type": "fallback",
            "data": {"message": "服务繁忙，请稍后重试"},
        })
    finally:
        await queue.put(None)  # Sentinel


def _handle_terminal_event(event: dict) -> None:
    """处理 done 事件：创建 File 记录."""
    if event["type"] != "done":
        return
    state_data = event["data"]
    docx_path = state_data.get("docx_path", "")
    if not docx_path or not state_data.get("docx_valid"):
        return

    try:
        import os
        from app.models import File as FileModel
        from app.database import SessionLocal
        db = SessionLocal()
        file_record = FileModel(
            filename=state_data.get("polished_title", "document") + ".docx",
            filepath=docx_path,
            filesize=os.path.getsize(docx_path),
            user_id=state_data.get("user_id", 1),
        )
        db.add(file_record)
        db.commit()
        db.refresh(file_record)
        event["data"]["_file_id"] = file_record.id
        event["data"]["_download_url"] = f"/api/v1/files/{file_record.id}/download"
        db.close()
    except Exception as e:
        logger.warning("Failed to create file record: %s", e)


def _format_terminal_sse(event: dict) -> str:
    """格式化 done/fallback 为 SSE 字符串."""
    from app.docs_pipeline.sse_bridge import make_sse_event, extract_done_event

    if event["type"] == "done":
        state_data = event["data"]
        download_url = state_data.get("_download_url", "")
        done_data = extract_done_event(state_data, download_url)
        return make_sse_event("done", done_data)
    else:
        return make_sse_event("fallback", {
            "message": event["data"].get("message", "服务繁忙，请稍后重试"),
        })
