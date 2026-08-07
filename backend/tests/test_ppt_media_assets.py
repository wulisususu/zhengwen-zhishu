from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import File, PPTIncrementalTask, User


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, username="editor-owner", password_hash="x"))
    session.add_all([
        PPTIncrementalTask(task_id="pptinc_editor_001", project_id="pptproj_editor_001", user_id=1, request_id="one", status="completed", page_count=1),
        PPTIncrementalTask(task_id="pptinc_editor_002", project_id="pptproj_editor_002", user_id=1, request_id="two", status="completed", page_count=1),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close(); engine.dispose()


def test_project_media_asset_is_deduplicated_and_authorized_per_project(db_session, tmp_path):
    from PIL import Image
    from app.PPT_master.media_assets import PptMediaResolver

    image_path = tmp_path / "provided.png"
    Image.new("RGB", (32, 18), "#336699").save(image_path)
    db_session.add(File(id=301, user_id=1, owner_user_id=1, filename="provided.png", filepath=str(image_path), real_path=str(image_path), mime_type="image/png"))
    db_session.commit()

    resolver = PptMediaResolver()
    first = resolver.register_file(db_session, file_id=301, owner_user_id=1, source_type="uploaded", project_id="pptproj_editor_001")
    second = resolver.register_file(db_session, file_id=301, owner_user_id=1, source_type="uploaded", project_id="pptproj_editor_002")

    assert first["asset_id"] == second["asset_id"]
    assert resolver.manifest(db_session, project_id="pptproj_editor_001", owner_user_id=1)["assets"] == [first]
    assert resolver.manifest(db_session, project_id="pptproj_editor_002", owner_user_id=1)["assets"] == [second]


def test_extracts_docx_embedded_images_into_the_project_media_manifest(db_session, tmp_path):
    from zipfile import ZipFile
    from PIL import Image
    from app.PPT_master.media_assets import PptMediaAdapter

    image_path = tmp_path / "embedded.png"
    Image.new("RGB", (20, 10), "#112233").save(image_path)
    source_path = tmp_path / "source.docx"
    with ZipFile(source_path, "w") as archive:
        archive.write(image_path, "word/media/image1.png")
    db_session.add(File(id=302, user_id=1, owner_user_id=1, filename="source.docx", filepath=str(source_path), real_path=str(source_path), mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
    db_session.commit()

    assets = PptMediaAdapter(storage_root=tmp_path / "media").extract_document_images(
        db_session, project_id="pptproj_editor_001", owner_user_id=1, source_file_id=302,
    )

    assert len(assets) == 1
    assert assets[0]["source"] == "document_extracted"
    assert assets[0]["source_file_id"] == 302
    assert assets[0]["width"] == 20
