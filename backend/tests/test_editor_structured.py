"""Editor structured document handling: master/layout inherited elements are
locked/read-only, while placeholder carrier content stays editable."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import File, PPTIncrementalTask, User


@pytest.fixture()
def structured_db_session(tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, username="editor-owner", password_hash="x"))
    svg_path = tmp_path / "slide-1.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720" '
        'data-pptx-master="master-default" data-pptx-layout="layout-title" data-pptx-page-role="cover">'
        '<g data-pptx-role="background"><rect id="bg-1" x="0" y="0" width="1280" height="720" fill="#FFFFFF"/></g>'
        '<g id="slot-title" data-pptx-placeholder="title" data-pptx-placeholder-idx="0" '
        'data-pptx-placeholder-bounds="140,200,1000,120">'
        '<text data-pptx-placeholder-carrier="true" x="640" y="280" text-anchor="middle" font-size="42">Annual Review</text>'
        '</g>'
        '</svg>',
        encoding="utf-8",
    )
    session.add(File(id=11, user_id=1, owner_user_id=1, filename="slide-1.svg", filepath=str(svg_path), real_path=str(svg_path), mime_type="image/svg+xml", project_id="pptproj_structured_001", task_id="pptinc_structured_001"))
    session.add(File(id=101, user_id=1, owner_user_id=1, filename="original.pptx", filepath="/tmp/original.pptx", real_path="/tmp/original.pptx", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", project_id="pptproj_structured_001", task_id="pptinc_structured_001"))
    session.add(PPTIncrementalTask(
        task_id="pptinc_structured_001",
        project_id="pptproj_structured_001",
        user_id=1,
        request_id="editor-structured-001",
        page_count=1,
        status="completed",
        final_file_json='{"file_id": 101}',
        completed_slides_json='[{"slide_id":"slide-1","index":1,"title":"Annual Review","preview_file_id":11}]',
    ))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_structured_background_is_locked(structured_db_session):
    from app.PPT_master.editor_documents import EditorDocumentStore

    store = EditorDocumentStore()
    result = store.get_or_initialize(structured_db_session, project_id="pptproj_structured_001", user_id=1)
    elements = result["document"]["slides"][0]["elements"]

    background = next(item for item in elements if item.get("pptx_role") == "background")
    assert background["locked"] is True


def test_structured_placeholder_carrier_text_is_editable(structured_db_session):
    from app.PPT_master.editor_documents import EditorDocumentStore

    store = EditorDocumentStore()
    result = store.get_or_initialize(structured_db_session, project_id="pptproj_structured_001", user_id=1)
    elements = result["document"]["slides"][0]["elements"]

    placeholder = next(item for item in elements if item.get("placeholder_type") == "title")
    assert placeholder["locked"] is False
    assert placeholder["content"]["text"] == "Annual Review"
    assert placeholder["placeholder_idx"] == 0


def test_structured_placeholder_bounds_are_not_editable_fields(structured_db_session):
    """Placeholder position/size come from the fixed Layout bounds, not free editing."""
    from app.PPT_master.editor_documents import EditorDocumentStore

    store = EditorDocumentStore()
    result = store.get_or_initialize(structured_db_session, project_id="pptproj_structured_001", user_id=1)
    elements = result["document"]["slides"][0]["elements"]

    placeholder = next(item for item in elements if item.get("placeholder_type") == "title")
    # Bounds come from data-pptx-placeholder-bounds: 140,200,1000,120
    assert placeholder["x"] == 140
    assert placeholder["y"] == 200
    assert placeholder["width"] == 1000
    assert placeholder["height"] == 120
    assert placeholder["bounds_locked"] is True
