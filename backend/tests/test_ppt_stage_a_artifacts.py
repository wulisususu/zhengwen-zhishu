from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import File, User


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            User(id=1, username="artifact-owner", password_hash="x", nickname="owner"),
            User(id=2, username="artifact-other", password_hash="x", nickname="other"),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _write_pptx(projects_root: Path) -> Path:
    path = projects_root / "project-1" / "exports" / "result.pptx"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"stage-a-pptx-fixture")
    return path


def test_register_pptx_records_owner_integrity_and_expiry(tmp_path: Path, db_session):
    from app.services.artifact_service import ArtifactService

    projects_root = tmp_path / "projects"
    pptx_path = _write_pptx(projects_root)
    service = ArtifactService(projects_root=projects_root, legacy_roots=[])
    before = datetime.utcnow()

    record = service.register_pptx(
        db_session,
        owner_user_id=1,
        project_id="project-1",
        task_id="task-1",
        real_path=pptx_path,
        expires_in=timedelta(hours=1),
    )

    assert record.id is not None
    assert record.owner_user_id == 1
    assert record.user_id == 1
    assert record.project_id == "project-1"
    assert record.task_id == "task-1"
    assert record.real_path == str(pptx_path.resolve())
    assert record.filepath == record.real_path
    assert record.mime_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    assert record.size == len(b"stage-a-pptx-fixture")
    assert record.filesize == record.size
    assert len(record.sha256) == 64
    assert record.expires_at > before
    assert (pptx_path.stat().st_mode & 0o777) == 0o600

    payload = service.download_payload(record, validation_result={"passed": True, "warnings": [], "errors": [], "blocking_errors": []})
    assert payload == {
        "file_id": record.id,
        "download_url": f"/api/v1/files/{record.id}/download",
        "size": record.size,
        "sha256": record.sha256,
        "valid": True,
        "validation_result": {"passed": True, "warnings": [], "errors": [], "blocking_errors": []},
    }


def test_register_pptx_rejects_outside_root_and_symlink(tmp_path: Path, db_session):
    from app.services.artifact_service import ArtifactSecurityError, ArtifactService

    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    outside = tmp_path / "outside.pptx"
    outside.write_bytes(b"outside")
    service = ArtifactService(projects_root=projects_root, legacy_roots=[])

    with pytest.raises(ArtifactSecurityError):
        service.register_pptx(db_session, 1, "project-1", "task-1", outside)

    link = projects_root / "project-1" / "exports" / "linked.pptx"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    with pytest.raises(ArtifactSecurityError):
        service.register_pptx(db_session, 1, "project-1", "task-1", link)


def test_download_lookup_enforces_owner_and_expiry(tmp_path: Path, db_session):
    from app.services.artifact_service import ArtifactExpiredError, ArtifactNotFoundError, ArtifactService

    projects_root = tmp_path / "projects"
    path = _write_pptx(projects_root)
    service = ArtifactService(projects_root=projects_root, legacy_roots=[])
    record = service.register_pptx(db_session, 1, "project-1", "task-1", path, expires_in=timedelta(hours=1))

    assert service.get_downloadable(db_session, record.id, owner_user_id=1).id == record.id
    with pytest.raises(ArtifactNotFoundError):
        service.get_downloadable(db_session, record.id, owner_user_id=2)

    record.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()
    with pytest.raises(ArtifactExpiredError):
        service.get_downloadable(db_session, record.id, owner_user_id=1)


def test_download_lookup_rejects_registered_path_tampering(tmp_path: Path, db_session):
    from app.services.artifact_service import ArtifactSecurityError, ArtifactService

    projects_root = tmp_path / "projects"
    path = _write_pptx(projects_root)
    service = ArtifactService(projects_root=projects_root, legacy_roots=[])
    record = service.register_pptx(db_session, 1, "project-1", "task-1", path)
    record.real_path = "/etc/passwd"
    record.filepath = "/etc/passwd"
    db_session.commit()

    with pytest.raises(ArtifactSecurityError):
        service.get_downloadable(db_session, record.id, owner_user_id=1)


def test_download_lookup_rejects_registered_content_tampering(tmp_path: Path, db_session):
    from app.services.artifact_service import ArtifactSecurityError, ArtifactService

    projects_root = tmp_path / "projects"
    path = _write_pptx(projects_root)
    service = ArtifactService(projects_root=projects_root, legacy_roots=[])
    record = service.register_pptx(db_session, 1, "project-1", "task-1", path)
    path.write_bytes(b"replaced-after-registration")

    with pytest.raises(ArtifactSecurityError):
        service.get_downloadable(db_session, record.id, owner_user_id=1)


def test_media_type_falls_back_to_filename_for_legacy_extension(db_session):
    from app.services.artifact_service import ArtifactService, PPTX_MIME_TYPE

    pptx = File(user_id=1, owner_user_id=1, filename="slides.pptx", filepath="/unused", filetype=".pptx", mime_type=PPTX_MIME_TYPE)
    legacy_docx = File(user_id=1, owner_user_id=1, filename="report.docx", filepath="/unused", filetype=".docx", mime_type=".docx")
    assert ArtifactService.media_type_for(pptx) == PPTX_MIME_TYPE
    assert ArtifactService.media_type_for(legacy_docx) == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_cleanup_expired_removes_only_expired_artifacts(tmp_path: Path, db_session):
    from app.services.artifact_service import ArtifactService

    projects_root = tmp_path / "projects"
    expired_path = _write_pptx(projects_root)
    live_path = projects_root / "project-2" / "exports" / "live.pptx"
    live_path.parent.mkdir(parents=True)
    live_path.write_bytes(b"live")
    service = ArtifactService(projects_root=projects_root, legacy_roots=[])
    expired = service.register_pptx(db_session, 1, "project-1", "expired-task", expired_path)
    live = service.register_pptx(db_session, 1, "project-2", "live-task", live_path)
    expired.expires_at = datetime.utcnow() - timedelta(seconds=1)
    live.expires_at = datetime.utcnow() + timedelta(hours=1)
    db_session.commit()

    assert service.cleanup_expired(db_session) == 1
    assert not expired_path.exists()
    assert live_path.exists()
    assert db_session.query(File).filter(File.id == expired.id).first() is None
    assert db_session.query(File).filter(File.id == live.id).first() is not None


def test_register_svg_project_asset_records_owner_and_integrity(tmp_path: Path, db_session):
    from app.services.artifact_service import ArtifactService

    projects_root = tmp_path / "projects"
    svg_path = projects_root / "pptproj-1" / "svg_output" / "page_01.svg"
    svg_path.parent.mkdir(parents=True)
    svg_path.write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'><text x='10' y='20'>Page one</text></svg>",
        encoding="utf-8",
    )
    service = ArtifactService(projects_root=projects_root, legacy_roots=[])

    record = service.register_project_asset(
        db_session,
        owner_user_id=1,
        project_id="pptproj-1",
        task_id="pptinc-1",
        real_path=svg_path,
        mime_type="image/svg+xml",
    )

    assert record.mime_type == "image/svg+xml"
    assert record.filetype == ".svg"
    assert record.owner_user_id == 1
    assert len(record.sha256) == 64
    assert service.get_downloadable(db_session, record.id, owner_user_id=1).id == record.id
    assert service.media_type_for(record) == "image/svg+xml"
    assert (svg_path.stat().st_mode & 0o777) == 0o600


def test_register_svg_project_asset_rejects_unsafe_svg(tmp_path: Path, db_session):
    from app.services.artifact_service import ArtifactSecurityError, ArtifactService

    projects_root = tmp_path / "projects"
    svg_path = projects_root / "pptproj-1" / "svg_output" / "page_01.svg"
    svg_path.parent.mkdir(parents=True)
    svg_path.write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'><image href='https://example.com/a.png'/></svg>",
        encoding="utf-8",
    )
    service = ArtifactService(projects_root=projects_root, legacy_roots=[])

    with pytest.raises(ArtifactSecurityError):
        service.register_project_asset(
            db_session, 1, "pptproj-1", "pptinc-1", svg_path, "image/svg+xml"
        )


def test_register_project_asset_rejects_mime_suffix_mismatch(tmp_path: Path, db_session):
    from app.services.artifact_service import ArtifactSecurityError, ArtifactService

    projects_root = tmp_path / "projects"
    html_path = projects_root / "pptproj-1" / "svg_output" / "page_01.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    service = ArtifactService(projects_root=projects_root, legacy_roots=[])

    with pytest.raises(ArtifactSecurityError):
        service.register_project_asset(
            db_session, 1, "pptproj-1", "pptinc-1", html_path, "image/svg+xml"
        )


def test_download_lookup_rejects_svg_content_tampering(tmp_path: Path, db_session):
    from app.services.artifact_service import ArtifactSecurityError, ArtifactService

    projects_root = tmp_path / "projects"
    svg_path = projects_root / "pptproj-1" / "svg_output" / "page_01.svg"
    svg_path.parent.mkdir(parents=True)
    svg_path.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    service = ArtifactService(projects_root=projects_root, legacy_roots=[])
    record = service.register_project_asset(
        db_session, 1, "pptproj-1", "pptinc-1", svg_path, "image/svg+xml"
    )
    svg_path.write_text("<svg xmlns='http://www.w3.org/2000/svg'><text>changed</text></svg>", encoding="utf-8")

    with pytest.raises(ArtifactSecurityError):
        service.get_downloadable(db_session, record.id, owner_user_id=1)
