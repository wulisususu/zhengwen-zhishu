from __future__ import annotations

import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import User


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            User(id=1, username="incremental-owner", password_hash="x"),
            User(id=2, username="incremental-other", password_hash="x"),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _create_task(db_session):
    from app.PPT_master.incremental_store import IncrementalTaskStore

    store = IncrementalTaskStore()
    store.create_task(
        db_session,
        task_id="pptinc_store_001",
        project_id="pptproj_store_001",
        user_id=1,
        request_id="incremental-store-001",
        page_count=2,
    )
    return store


def test_event_store_assigns_contiguous_standard_envelopes(db_session):
    store = _create_task(db_session)

    first = store.append_event(db_session, "pptinc_store_001", "planning.started", {})
    second = store.append_event(
        db_session,
        "pptinc_store_001",
        "planning.completed",
        {"page_count": 2, "outline": [], "design_summary": {}},
    )

    assert [first["sequence"], second["sequence"]] == [1, 2]
    assert first["event_id"].startswith("evt_")
    assert first["event_type"] == "planning.started"
    assert first["task_id"] == "pptinc_store_001"
    assert first["project_id"] == "pptproj_store_001"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T.*Z$", first["timestamp"])
    assert first["data"] == {}


def test_planning_completed_updates_task_snapshot(db_session):
    store = _create_task(db_session)
    store.append_event(db_session, "pptinc_store_001", "planning.started", {})
    outline = [{"index": 1, "title": "Opening"}, {"index": 2, "title": "Conclusion"}]
    store.append_event(
        db_session,
        "pptinc_store_001",
        "planning.completed",
        {"page_count": 2, "outline": outline, "design_summary": {"preview": "safe"}},
    )

    snapshot = store.snapshot(db_session, "pptinc_store_001", owner_user_id=1)
    assert snapshot["status"] == "planning_completed"
    assert snapshot["sequence"] == 2
    assert snapshot["outline"] == outline


def test_snapshot_preserves_completed_slide_after_later_failure(db_session):
    store = _create_task(db_session)
    store.append_event(
        db_session,
        "pptinc_store_001",
        "slide.completed",
        {
            "slide_id": "pptinc_store_001:slide:1",
            "index": 1,
            "title": "Opening",
            "status": "completed",
            "preview_file_id": 11,
            "preview_url": "/api/v1/files/11/download",
            "thumbnail_file_id": 11,
            "thumbnail_url": "/api/v1/files/11/download",
        },
    )
    store.append_event(
        db_session,
        "pptinc_store_001",
        "slide.failed",
        {
            "slide_id": "pptinc_store_001:slide:2",
            "index": 2,
            "title": "Conclusion",
            "status": "failed",
            "errors": ["svg_xml_invalid"],
        },
    )

    snapshot = store.snapshot(db_session, "pptinc_store_001", owner_user_id=1)
    assert [slide["index"] for slide in snapshot["completed_slides"]] == [1]
    assert snapshot["errors"] == [{"index": 2, "errors": ["svg_xml_invalid"]}]
    assert snapshot["current_slide"] is None


def test_task_completed_snapshot_contains_metrics_and_final_file(db_session):
    store = _create_task(db_session)
    metrics = {
        "model_output_count": 3,
        "svg_xml_invalid_count": 1,
        "svg_validation_blocked_count": 1,
        "svg_validation_block_rate": 1 / 3,
        "model_repair_retry_count": 1,
    }
    final_file = {
        "file_id": 99,
        "download_url": "/api/v1/files/99/download",
        "size": 1234,
        "sha256": "a" * 64,
        "valid": True,
    }
    store.append_event(
        db_session,
        "pptinc_store_001",
        "validation.completed",
        {"passed": True, "warnings": [], "errors": [], "blocking_errors": [], "metrics": metrics},
    )
    store.append_event(db_session, "pptinc_store_001", "export.ready", {"final_file": final_file})
    store.append_event(db_session, "pptinc_store_001", "task.completed", {"final_file": final_file})

    snapshot = store.snapshot(db_session, "pptinc_store_001", owner_user_id=1)
    assert snapshot["status"] == "completed"
    assert snapshot["metrics"] == metrics
    assert snapshot["final_file"] == final_file


def test_task_snapshot_is_owner_scoped(db_session):
    from app.PPT_master.incremental_store import IncrementalTaskNotFound

    store = _create_task(db_session)
    with pytest.raises(IncrementalTaskNotFound):
        store.snapshot(db_session, "pptinc_store_001", owner_user_id=2)


def test_find_by_request_is_scoped_to_user(db_session):
    store = _create_task(db_session)
    assert store.find_by_request(db_session, 1, "incremental-store-001").task_id == "pptinc_store_001"
    assert store.find_by_request(db_session, 2, "incremental-store-001") is None
