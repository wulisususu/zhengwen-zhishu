from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_document_stream_uses_openclaw_agent_bridge_not_backend_orchestrator():
    source = (ROOT / "app" / "routers" / "conversations.py").read_text(encoding="utf-8")

    assert "orchestrate_document_reply" not in source
    assert "iter_openclaw_agent_events" in source
    assert "build_document_input" in source
    assert "build_document_chunk_input" in source
    assert "should_use_document_chunk_mode" in source
    assert "update_document_generation_state" in source
    assert "preflight_openclaw_provider" in source
    assert "extract_document_task_payload" in source
    preview_index = source.index("preview_text = render_document_preview_text")
    preview_block = source[preview_index:preview_index + 900]
    assert '{"type": "replace"' not in preview_block
    assert 'for token in emit_text_chunks(preview_text)' in preview_block


def test_document_stream_does_not_render_partial_openclaw_body_on_failure():
    source = (ROOT / "app" / "routers" / "conversations.py").read_text(encoding="utf-8")

    assert "OpenClaw partial render failed" not in source
    assert 'status": "partial_failed"' in source
    assert "completion_status=\"complete\"" in source


def test_openclaw_orchestrator_no_longer_owns_document_dual_model_flow():
    source = (ROOT / "app" / "services" / "openclaw_orchestrator.py").read_text(encoding="utf-8")

    assert "Dual-model orchestration" not in source
    assert "ThreadPoolExecutor(max_workers=2)" not in source
    assert "_generate_body_markdown" not in source
