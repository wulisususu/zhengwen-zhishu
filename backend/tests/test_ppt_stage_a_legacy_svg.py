from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace


VALID_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1280 720'>"
    "<rect width='1280' height='720' fill='#ffffff'/>"
    "<text x='80' y='120'>Safe slide</text></svg>"
)


async def _noop_push(_event_type: str, _data: dict) -> None:
    return None


def test_legacy_svg_node_generates_pages_individually(monkeypatch, tmp_path: Path):
    from app.PPT_master import nodes
    from app.PPT_master.incremental_slides import SlideGenerationResult

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    calls: list[int] = []

    async def fake_batch_call(_system: str, _user_prompt: str, _step_name: str) -> str:
        return json.dumps(
            [
                {"page": 1, "svg": VALID_SVG},
                {"page": 2, "svg": VALID_SVG},
                {"page": 3, "svg": VALID_SVG},
            ]
        )

    async def fake_generate_slide(**kwargs):
        calls.append(kwargs["index"])
        svg_dir = project_dir / "svg_output"
        svg_dir.mkdir(exist_ok=True)
        path = svg_dir / f"page_{kwargs['index']:02d}.svg"
        path.write_text(VALID_SVG, encoding="utf-8")
        return SlideGenerationResult(
            svg_path=path,
            title=kwargs["title"],
            errors=[],
            metrics={
                "model_output_count": 1,
                "svg_xml_invalid_count": 0,
                "svg_sanitize_success_count": 0,
                "svg_validation_blocked_count": 0,
                "model_repair_retry_count": 0,
            },
        )

    monkeypatch.setattr(nodes, "_push_sse", _noop_push)
    monkeypatch.setattr(nodes, "_call_glm_with_retry", fake_batch_call)
    monkeypatch.setattr(
        nodes,
        "extract_outline",
        lambda *_args, **_kwargs: [
            {"index": 1, "title": "Page 1"},
            {"index": 2, "title": "Page 2"},
            {"index": 3, "title": "Page 3"},
        ],
        raising=False,
    )
    monkeypatch.setattr(nodes, "generate_slide", fake_generate_slide, raising=False)

    result = asyncio.run(
        nodes.svg_node(
            {
                "task_id": "ppt_legacy_svg_fix_001",
                "user_id": 1,
                "user_input": "Legacy topic",
                "page_count": 3,
                "page_format": "ppt169",
                "project_dir": str(project_dir),
                "design_spec": "### Page 1: A\n### Page 2: B\n### Page 3: C",
            }
        )
    )

    assert calls == [1, 2, 3]
    assert result["status"] == "svg_done"
    assert result["failed_slides"] == []


def test_legacy_validate_node_blocks_export_when_page_generation_failed(monkeypatch, tmp_path: Path):
    from app.PPT_master import nodes

    project_dir = tmp_path / "project"
    (project_dir / "svg_output").mkdir(parents=True)
    (project_dir / "svg_output" / "page_01.svg").write_text(VALID_SVG, encoding="utf-8")

    async def ok_command(*_args, **_kwargs):
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(nodes, "_push_sse", _noop_push)
    monkeypatch.setattr(nodes, "validate_svg_directory", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(nodes, "run_command", ok_command)

    result = asyncio.run(
        nodes.validate_node(
            {
                "project_dir": str(project_dir),
                "page_count": 2,
                "failed_slides": [
                    {
                        "index": 2,
                        "title": "Page 2",
                        "errors": ["svg_xml_invalid"],
                        "diagnostics": [{"category": "truncated_output"}],
                    }
                ],
            }
        )
    )

    assert result["status"] == "validation_failed"
    assert result["validation_result"]["passed"] is False
    assert result["validation_result"]["blocking_errors"] == ["svg_xml_invalid"]
    assert result["failed_slides"][0]["diagnostics"][0]["category"] == "truncated_output"
