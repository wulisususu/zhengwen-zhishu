"""LangGraph pipeline runner: astream + asyncio.Queue to SSE generator."""
import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path

from app.PPT_master.state import PipelineState, initial_state
from app.PPT_master.graph import build_graph
from app.PPT_master.nodes import set_sse_queue
from app.PPT_master.sse_bridge import make_sse_event
from app.database import SessionLocal
from app.services.artifact_service import ArtifactError, ArtifactService
from app.PPT_master.admission import IdempotencyService, cleanup_failed_project

logger = logging.getLogger(__name__)
_graph = None
_artifact_service = ArtifactService()
_idempotency_service = IdempotencyService()
_TASK_TIMEOUT_SECONDS = 900


def _failure_diagnostics(state: dict) -> dict:
    project_dir = state.get("project_dir", "")
    project_id = Path(project_dir).name if project_dir else ""
    return {
        "project_id": project_id,
        "page_count": state.get("page_count"),
        "failed_slides": state.get("failed_slides") or [],
        "validation_result": state.get("validation_result") or {},
        "metrics": state.get("svg_metrics") or {},
    }


def _register_done_artifact(state_data: dict) -> tuple[str, dict]:
    pptx_path = state_data.get("pptx_path", "")
    if not pptx_path or not state_data.get("pptx_valid"):
        return "fallback", {"message": "PPTX artifact unavailable", "valid": False}
    validation_result = state_data.get("validation_result") or {
        "passed": True,
        "warnings": [],
        "errors": [],
        "blocking_errors": [],
    }
    db = SessionLocal()
    try:
        project_dir = state_data.get("project_dir", "")
        record = _artifact_service.register_pptx(
            db,
            owner_user_id=state_data.get("user_id", 1),
            project_id=Path(project_dir).name if project_dir else "",
            task_id=state_data.get("task_id", ""),
            real_path=pptx_path,
        )
        return "done", _artifact_service.download_payload(record, validation_result)
    except ArtifactError:
        logger.exception("PPT artifact registration rejected")
        return "fallback", {"message": "PPTX artifact registration failed", "valid": False}
    except Exception:
        logger.exception("PPT artifact registration failed")
        return "fallback", {"message": "PPTX artifact registration failed", "valid": False}
    finally:
        db.close()


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run_pipeline_stream(
    user_input: str,
    page_count: int = 8,
    page_format: str = "ppt169",
    sources: list[str] | None = None,
    task_id: str | None = None,
    user_id: int = 1,
    idempotency_record_id: int | None = None,
    task_timeout_seconds: float = _TASK_TIMEOUT_SECONDS,
):
    """Run LangGraph pipeline, yield SSE event strings."""
    if task_id is None:
        task_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]

    state = initial_state(user_input, page_count, page_format, sources, task_id, user_id)
    graph = _get_graph()
    queue = asyncio.Queue(maxsize=4)
    set_sse_queue(queue)
    if idempotency_record_id is not None:
        db = SessionLocal()
        try:
            _idempotency_service.mark_running(db, idempotency_record_id)
        finally:
            db.close()

    graph_task = asyncio.ensure_future(_run_graph(state, graph, queue))
    deadline = asyncio.get_running_loop().time() + task_timeout_seconds
    terminal_stored = False

    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            event = await asyncio.wait_for(queue.get(), timeout=remaining)
            if event is None:
                break
            if event["type"] in ("done", "fallback"):
                if event["type"] == "done":
                    event_type, payload = _register_done_artifact(event["data"])
                    yield make_sse_event(event_type, payload)
                else:
                    payload = dict(event["data"])
                    payload.pop("pptx_path", None)
                    payload.pop("project_dir", None)
                    payload.pop("user_input", None)
                    payload["valid"] = False
                    event_type = "fallback"
                if idempotency_record_id is not None:
                    _store_terminal(idempotency_record_id, event_type, payload)
                    terminal_stored = True
                yield make_sse_event(event_type, payload)
                break
            else:
                yield make_sse_event(event["type"], event["data"])
    except asyncio.TimeoutError:
        payload = {
            "message": "PPT generation timed out",
            "valid": False,
            "validation_result": {
                "passed": False,
                "warnings": [],
                "errors": [],
                "blocking_errors": ["task_timeout"],
            },
        }
        if idempotency_record_id is not None:
            _store_terminal(idempotency_record_id, "fallback", payload, "task_timeout")
            terminal_stored = True
        yield make_sse_event("fallback", payload)
    except asyncio.CancelledError:
        if idempotency_record_id is not None and not terminal_stored:
            _store_terminal(
                idempotency_record_id,
                "fallback",
                {"message": "PPT generation interrupted", "valid": False},
                "stream_cancelled",
            )
            terminal_stored = True
        raise
    finally:
        if not graph_task.done():
            graph_task.cancel()
        await asyncio.gather(graph_task, return_exceptions=True)
        if idempotency_record_id is not None and not terminal_stored:
            _store_terminal(
                idempotency_record_id,
                "fallback",
                {"message": "PPT generation ended without a terminal artifact", "valid": False},
                "stream_ended_without_terminal",
            )

    logger.info("PPT pipeline stream ended for task %s", task_id)


def _store_terminal(
    record_id: int,
    event_type: str,
    payload: dict,
    error_code: str = "pipeline_failed",
) -> None:
    db = SessionLocal()
    try:
        if event_type == "done":
            _idempotency_service.mark_completed(
                db,
                record_id,
                file_id=int(payload["file_id"]),
                payload=payload,
            )
        else:
            _idempotency_service.mark_failed(db, record_id, error_code, payload)
    finally:
        db.close()


async def _cleanup_failure(state: dict, error_code: str) -> None:
    project_dir = state.get("project_dir")
    if not project_dir:
        return
    await asyncio.to_thread(
        cleanup_failed_project,
        project_dir,
        task_id=state.get("task_id", "unknown"),
        error_code=error_code,
        diagnostics=_failure_diagnostics(state),
    )


async def _run_graph(state: PipelineState, graph, queue: asyncio.Queue):
    latest_state = dict(state)
    try:
        config = {"configurable": {"thread_id": state["task_id"]}}
        async for chunk in graph.astream(state, config, stream_mode="updates"):
            for node_name, node_state in chunk.items():
                latest_state.update(node_state)
                logger.debug("Node %s completed", node_name)
                status = node_state.get("status", "")
                if status == "done":
                    await queue.put({"type": "done", "data": latest_state})
                    return
                elif status == "graceful_fallback":
                    error_code = node_state.get("graceful_error") or "pipeline_failed"
                    await _cleanup_failure(latest_state, str(error_code))
                    await queue.put({
                        "type": "fallback",
                        "data": {
                            "message": "PPT 生成失败",
                            "valid": False,
                            "validation_result": node_state.get("validation_result"),
                            "failed_slides": node_state.get("failed_slides") or [],
                            "metrics": node_state.get("svg_metrics") or {},
                        },
                    })
                    return
        await _cleanup_failure(latest_state, "pipeline_missing_terminal")
        await queue.put({"type": "fallback", "data": {"message": "PPT 生成失败", "valid": False}})
    except asyncio.CancelledError:
        await _cleanup_failure(latest_state, "pipeline_cancelled")
        raise
    except Exception:
        logger.exception("Graph execution failed")
        await _cleanup_failure(latest_state, "pipeline_exception")
        await queue.put({"type": "fallback", "data": {"message": "服务繁忙，请稍后重试", "valid": False}})
    finally:
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
