from __future__ import annotations

import asyncio
import json
from pathlib import Path


def test_cleanup_failed_project_persists_safe_diagnostics(tmp_path: Path):
    from app.PPT_master.admission import cleanup_failed_project

    projects_root = tmp_path / "projects"
    project_dir = projects_root / "pptgen_abc123"
    project_dir.mkdir(parents=True)
    (project_dir / "svg_output").mkdir()
    (project_dir / "svg_output" / "page_01.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'/>",
        encoding="utf-8",
    )
    diagnostics_root = tmp_path / "ppt_failures"

    removed = cleanup_failed_project(
        project_dir,
        task_id="ppt_task_001",
        error_code="validation_failed",
        projects_root=projects_root,
        diagnostics_root=diagnostics_root,
        diagnostics={
            "page_count": 8,
            "failed_slides": [
                {
                    "index": 2,
                    "errors": ["svg_xml_invalid"],
                    "diagnostics": [{"category": "truncated_output", "line": 1, "column": 42}],
                }
            ],
            "validation_result": {
                "passed": False,
                "warnings": [],
                "errors": [],
                "blocking_errors": ["svg_xml_invalid"],
            },
            "metrics": {"svg_xml_invalid_count": 1},
        },
    )

    assert removed is True
    assert not project_dir.exists()
    payload = json.loads((diagnostics_root / "ppt_task_001.json").read_text(encoding="utf-8"))
    assert payload["task_id"] == "ppt_task_001"
    assert payload["page_count"] == 8
    assert payload["failed_slides"][0]["diagnostics"][0]["category"] == "truncated_output"
    assert payload["validation_result"]["blocking_errors"] == ["svg_xml_invalid"]


def test_runner_cleanup_failure_forwards_failed_slide_details(monkeypatch):
    from app.PPT_master import runner

    captured: dict = {}

    def fake_cleanup(project_dir, *, task_id, error_code, diagnostics=None, **_kwargs):
        captured.update(
            {
                "project_dir": str(project_dir),
                "task_id": task_id,
                "error_code": error_code,
                "diagnostics": diagnostics,
            }
        )
        return True

    monkeypatch.setattr(runner, "cleanup_failed_project", fake_cleanup)

    asyncio.run(
        runner._cleanup_failure(
            {
                "project_dir": "/tmp/project",
                "task_id": "ppt_task_002",
                "page_count": 4,
                "failed_slides": [{"index": 3, "errors": ["svg_xml_invalid"]}],
                "validation_result": {
                    "passed": False,
                    "warnings": [],
                    "errors": [],
                    "blocking_errors": ["svg_xml_invalid"],
                },
                "svg_metrics": {"svg_xml_invalid_count": 1},
            },
            "validation_failed",
        )
    )

    assert captured["task_id"] == "ppt_task_002"
    assert captured["error_code"] == "validation_failed"
    assert captured["diagnostics"]["failed_slides"] == [{"index": 3, "errors": ["svg_xml_invalid"]}]
    assert captured["diagnostics"]["metrics"] == {"svg_xml_invalid_count": 1}
