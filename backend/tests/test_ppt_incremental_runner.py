from __future__ import annotations

import asyncio
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import User
from app.PPT_master.incremental_slides import SlideGenerationResult
from app.PPT_master.incremental_store import IncrementalTaskStore
from app.services.artifact_service import ArtifactService


VALID_SVG = "<svg xmlns='http://www.w3.org/2000/svg'><text x='10' y='20'>safe</text></svg>"


@pytest.fixture()
def workflow_context(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runner.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    db.add(User(id=1, username="runner-owner", password_hash="x"))
    db.commit()
    IncrementalTaskStore().create_task(
        db,
        task_id="pptinc_runner_001",
        project_id="pptproj_runner_001",
        user_id=1,
        request_id="incremental-runner-001",
        page_count=4,
    )
    db.close()
    project_dir = tmp_path / "projects" / "physical-project"
    project_dir.mkdir(parents=True)
    service = ArtifactService(projects_root=tmp_path / "projects", legacy_roots=[])
    try:
        yield session_factory, project_dir, service
    finally:
        engine.dispose()


def test_four_page_workflow_emits_contiguous_planning_slides_and_export(workflow_context):
    from app.PPT_master.incremental_runner import PlanningResult, run_incremental_workflow

    session_factory, project_dir, service = workflow_context
    events: list[dict] = []

    async def planner(**_kwargs):
        return PlanningResult(
            project_dir=project_dir,
            design_spec="safe design",
            outline=[{"index": index, "title": f"Page {index}"} for index in range(1, 5)],
            design_summary={"preview": "safe design"},
        )

    async def slide_generator(**kwargs):
        svg_dir = project_dir / "svg_output"
        svg_dir.mkdir(exist_ok=True)
        path = svg_dir / f"page_{kwargs['index']:02d}.svg"
        path.write_text(VALID_SVG, encoding="utf-8")
        return SlideGenerationResult(
            path,
            kwargs["title"],
            [],
            {
                "model_output_count": 1,
                "svg_xml_invalid_count": 0,
                "svg_sanitize_success_count": 0,
                "svg_validation_blocked_count": 0,
                "model_repair_retry_count": 0,
            },
        )

    async def validator(**_kwargs):
        return {"passed": True, "warnings": [], "errors": [], "blocking_errors": []}

    async def exporter(**_kwargs):
        path = project_dir / "exports" / "result.pptx"
        path.parent.mkdir(exist_ok=True)
        members = {
            "[Content_Types].xml": "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>",
            "_rels/.rels": "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"/>",
            "ppt/presentation.xml": "<p:presentation xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\"/>",
            "ppt/_rels/presentation.xml.rels": "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"/>",
        }
        for index in range(1, 5):
            members[f"ppt/slides/slide{index}.xml"] = (
                "<p:sld xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\" "
                "xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\"><p:cSld/>"
                "</p:sld>"
            )
        with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
            for name, text in members.items():
                archive.writestr(name, text)
        return {"pptx_path": str(path), "pptx_valid": True}

    async def sink(event):
        events.append(event)

    asyncio.run(
        run_incremental_workflow(
            task_id="pptinc_runner_001",
            project_id="pptproj_runner_001",
            user_id=1,
            user_input="Four page topic",
            page_count=4,
            page_format="ppt169",
            event_sink=sink,
            session_factory=session_factory,
            artifact_service=service,
            planner=planner,
            slide_generator=slide_generator,
            validator=validator,
            exporter=exporter,
        )
    )

    assert [event["sequence"] for event in events] == list(range(1, 14))
    event_types = [event["event_type"] for event in events]
    assert event_types[:2] == ["planning.started", "planning.completed"]
    assert event_types[2:10] == [
        "slide.started",
        "slide.completed",
        "slide.started",
        "slide.completed",
        "slide.started",
        "slide.completed",
        "slide.started",
        "slide.completed",
    ]
    assert event_types[-3:] == ["validation.completed", "export.ready", "task.completed"]
    first_completed = next(event for event in events if event["event_type"] == "slide.completed")
    assert first_completed["data"]["index"] == 1
    assert first_completed["data"]["preview_url"].startswith("/api/v1/files/")
    assert event_types.index("slide.completed") < event_types.index("slide.started", 3)

    db = session_factory()
    snapshot = IncrementalTaskStore().snapshot(db, "pptinc_runner_001", 1)
    db.close()
    assert snapshot["status"] == "completed"
    assert [slide["index"] for slide in snapshot["completed_slides"]] == [1, 2, 3, 4]
    assert snapshot["metrics"]["svg_validation_block_rate"] == 0
    assert snapshot["final_file"]["valid"] is True


def test_incremental_workflow_passes_selected_source_context_to_planner_and_slides(workflow_context):
    from app.PPT_master.incremental_runner import PlanningResult, run_incremental_workflow

    session_factory, project_dir, service = workflow_context
    captured = {"planner": None, "slide": None}

    async def planner(**kwargs):
        captured["planner"] = kwargs["source_context"]
        return PlanningResult(project_dir, "safe design", [{"index": 1, "title": "Evidence"}], {})

    async def slide_generator(**kwargs):
        captured["slide"] = kwargs["source_context"]
        return SlideGenerationResult(None, kwargs["title"], ["stop_after_capture"], {
            "model_output_count": 0, "svg_xml_invalid_count": 0,
            "svg_sanitize_success_count": 0, "svg_validation_blocked_count": 0,
            "model_repair_retry_count": 0,
        })

    async def sink(_event):
        return None

    asyncio.run(run_incremental_workflow(
        task_id="pptinc_runner_001", project_id="pptproj_runner_001", user_id=1,
        user_input="Build a source-grounded deck", page_count=1, page_format="ppt169",
        source_context="【来源：brief.docx】\n收入增长 18%", source_manifest=[{"file_id": 7}],
        event_sink=sink, session_factory=session_factory, artifact_service=service,
        planner=planner, slide_generator=slide_generator,
    ))

    assert captured["planner"] == "【来源：brief.docx】\n收入增长 18%"
    assert captured["slide"] == "【来源：brief.docx】\n收入增长 18%"


def test_failed_page_keeps_completed_pages_and_continues(workflow_context):
    from app.PPT_master.incremental_runner import PlanningResult, run_incremental_workflow

    session_factory, project_dir, service = workflow_context
    events: list[dict] = []
    exporter_called = False

    async def planner(**_kwargs):
        return PlanningResult(
            project_dir=project_dir,
            design_spec="safe design",
            outline=[{"index": index, "title": f"Page {index}"} for index in range(1, 5)],
            design_summary={"preview": "safe design"},
        )

    async def slide_generator(**kwargs):
        metrics = {
            "model_output_count": 3 if kwargs["index"] == 2 else 1,
            "svg_xml_invalid_count": 3 if kwargs["index"] == 2 else 0,
            "svg_sanitize_success_count": 0,
            "svg_validation_blocked_count": 3 if kwargs["index"] == 2 else 0,
            "model_repair_retry_count": 2 if kwargs["index"] == 2 else 0,
        }
        if kwargs["index"] == 2:
            return SlideGenerationResult(None, kwargs["title"], ["svg_xml_invalid"], metrics)
        svg_dir = project_dir / "svg_output"
        svg_dir.mkdir(exist_ok=True)
        path = svg_dir / f"page_{kwargs['index']:02d}.svg"
        path.write_text(VALID_SVG, encoding="utf-8")
        return SlideGenerationResult(path, kwargs["title"], [], metrics)

    async def exporter(**_kwargs):
        nonlocal exporter_called
        exporter_called = True
        return {}

    async def sink(event):
        events.append(event)

    asyncio.run(
        run_incremental_workflow(
            task_id="pptinc_runner_001",
            project_id="pptproj_runner_001",
            user_id=1,
            user_input="Four page topic",
            page_count=4,
            page_format="ppt169",
            event_sink=sink,
            session_factory=session_factory,
            artifact_service=service,
            planner=planner,
            slide_generator=slide_generator,
            exporter=exporter,
        )
    )

    assert [event["data"]["index"] for event in events if event["event_type"] == "slide.started"] == [1, 2, 3, 4]
    assert [event["data"]["index"] for event in events if event["event_type"] == "slide.completed"] == [1, 3, 4]
    assert [event["data"]["index"] for event in events if event["event_type"] == "slide.failed"] == [2]
    assert events[-2]["event_type"] == "validation.completed"
    assert events[-1]["event_type"] == "task.failed"
    assert exporter_called is False

    db = session_factory()
    snapshot = IncrementalTaskStore().snapshot(db, "pptinc_runner_001", 1)
    db.close()
    assert [slide["index"] for slide in snapshot["completed_slides"]] == [1, 3, 4]
    assert snapshot["errors"][0] == {"index": 2, "errors": ["svg_xml_invalid"]}
    assert snapshot["metrics"] == {
        "model_output_count": 6,
        "svg_xml_invalid_count": 3,
        "svg_sanitize_success_count": 0,
        "svg_validation_blocked_count": 3,
        "model_repair_retry_count": 2,
        "svg_validation_block_rate": 0.5,
    }
