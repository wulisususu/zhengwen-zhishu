import asyncio
import inspect
from pathlib import Path

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
            User(id=1, username="idem-owner", password_hash="x", nickname="owner"),
            User(id=2, username="idem-other", password_hash="x", nickname="other"),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_generation_limiter_enforces_global_limit():
    from app.PPT_master.admission import GenerationBusyError, GenerationLimiter

    async def scenario():
        limiter = GenerationLimiter(max_global=1, max_per_user=1)
        first = await limiter.acquire_nowait(user_id=1)
        with pytest.raises(GenerationBusyError) as exc_info:
            await limiter.acquire_nowait(user_id=2)
        assert exc_info.value.code == "global_generation_limit_reached"
        await first.release()
        second = await limiter.acquire_nowait(user_id=2)
        await second.release()

    asyncio.run(scenario())


def test_generation_limiter_enforces_per_user_limit():
    from app.PPT_master.admission import GenerationBusyError, GenerationLimiter

    async def scenario():
        limiter = GenerationLimiter(max_global=2, max_per_user=1)
        first = await limiter.acquire_nowait(user_id=1)
        with pytest.raises(GenerationBusyError) as exc_info:
            await limiter.acquire_nowait(user_id=1)
        assert exc_info.value.code == "user_generation_limit_reached"
        second_user = await limiter.acquire_nowait(user_id=2)
        await second_user.release()
        await first.release()

    asyncio.run(scenario())


def test_sqlite_idempotency_replays_completed_request_without_new_row(db_session):
    from app.PPT_master.admission import IdempotencyService
    from app.models import PPTGenerationRequest

    service = IdempotencyService()
    first = service.begin(db_session, user_id=1, request_id="same-request-001", task_id="task-1")
    assert first.kind == "new"
    active = service.begin(db_session, user_id=1, request_id="same-request-001", task_id="task-2")
    assert active.kind == "active"

    payload = {"file_id": 9, "download_url": "/api/v1/files/9/download", "valid": True}
    service.mark_completed(db_session, first.record.id, file_id=9, payload=payload)
    replay = service.begin(db_session, user_id=1, request_id="same-request-001", task_id="task-3")
    assert replay.kind == "replay"
    assert replay.event_type == "done"
    assert replay.payload == payload
    assert db_session.query(PPTGenerationRequest).count() == 1


def test_sqlite_idempotency_isolated_by_user(db_session):
    from app.PPT_master.admission import IdempotencyService
    from app.models import PPTGenerationRequest

    service = IdempotencyService()
    assert service.begin(db_session, 1, "shared-key-001", "task-a").kind == "new"
    assert service.begin(db_session, 2, "shared-key-001", "task-b").kind == "new"
    assert db_session.query(PPTGenerationRequest).count() == 2


def test_failed_idempotent_request_replays_failure(db_session):
    from app.PPT_master.admission import IdempotencyService

    service = IdempotencyService()
    first = service.begin(db_session, 1, "failed-key-001", "task-failed")
    service.mark_failed(db_session, first.record.id, "pipeline_failed", {"message": "generation failed", "valid": False})
    replay = service.begin(db_session, 1, "failed-key-001", "unused-task")
    assert replay.kind == "replay"
    assert replay.event_type == "fallback"
    assert replay.payload["valid"] is False


def test_request_id_selection_requires_one_matching_valid_key():
    from app.PPT_master.admission import InvalidRequestIdError, select_request_id

    assert select_request_id("body-key-001", None) == "body-key-001"
    assert select_request_id(None, "header-key-001") == "header-key-001"
    assert select_request_id("same-key-001", "same-key-001") == "same-key-001"
    with pytest.raises(InvalidRequestIdError):
        select_request_id(None, None)
    with pytest.raises(InvalidRequestIdError):
        select_request_id("body-key-001", "different-key-001")
    with pytest.raises(InvalidRequestIdError):
        select_request_id("../unsafe", None)


def test_project_quota_rejects_oversized_directory(tmp_path: Path):
    from app.PPT_master.admission import ProjectQuotaError, enforce_directory_quota

    project = tmp_path / "project"
    project.mkdir()
    (project / "payload.bin").write_bytes(b"x" * 33)
    with pytest.raises(ProjectQuotaError):
        enforce_directory_quota(project, max_bytes=32)
    assert enforce_directory_quota(project, max_bytes=33) == 33


def test_failed_project_cleanup_keeps_only_sanitized_diagnostic(tmp_path: Path):
    from app.PPT_master.admission import cleanup_failed_project

    projects_root = tmp_path / "projects"
    project = projects_root / "pptgen_project-1"
    project.mkdir(parents=True)
    (project / "sensitive.txt").write_text("private prompt", encoding="utf-8")
    diagnostics = tmp_path / "diagnostics"

    assert cleanup_failed_project(
        project,
        task_id="task-cleanup-001",
        error_code="export_failed",
        projects_root=projects_root,
        diagnostics_root=diagnostics,
    ) is True
    assert not project.exists()
    diagnostic_files = list(diagnostics.glob("*.json"))
    assert len(diagnostic_files) == 1
    diagnostic = diagnostic_files[0].read_text(encoding="utf-8")
    assert "private prompt" not in diagnostic
    assert str(project) not in diagnostic
    assert "export_failed" in diagnostic


def test_deployment_entrypoint_is_fixed_to_one_worker():
    import run

    source = Path(run.__file__).read_text(encoding="utf-8")
    assert "workers=1" in source
    assert "workers=2" not in source


def test_ppt_nodes_do_not_use_blocking_subprocess_run():
    import app.PPT_master.nodes as nodes

    source = inspect.getsource(nodes)
    assert "subprocess.run" not in source
    assert "run_command(" in source


def test_ppt_runtime_python_defaults_outside_repository(monkeypatch):
    import app.PPT_master.nodes as nodes

    monkeypatch.delenv("PPT_MASTER_PYTHON", raising=False)
    selected = Path(nodes._python()).expanduser().absolute()
    repository = Path(nodes.__file__).resolve().parents[2]
    assert repository not in selected.parents
    assert selected.name == "python3"
