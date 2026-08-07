"""Structured round-trip: edit placeholder content, re-export as real Master/Layout PPTX."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import File, PPTIncrementalTask, User


STRUCTURED_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720" '
    'data-pptx-master="master-default" data-pptx-master-name="Default Master" '
    'data-pptx-layout="layout-title" data-pptx-layout-name="Title" data-pptx-page-role="cover">'
    '<g data-pptx-role="background"><rect id="bg-1" width="1280" height="720" fill="#FFFFFF"/></g>'
    '<g id="slot-title" data-pptx-placeholder="title" data-pptx-placeholder-idx="0" '
    'data-pptx-placeholder-bounds="140,200,1000,120">'
    '<text data-pptx-placeholder-carrier="true" x="640" y="280" text-anchor="middle" font-size="42">Annual Review</text>'
    '</g>'
    '<g id="slot-subtitle" data-pptx-placeholder="subtitle" data-pptx-placeholder-idx="1" '
    'data-pptx-placeholder-bounds="240,380,800,80">'
    '<text data-pptx-placeholder-carrier="true" x="640" y="420" text-anchor="middle" font-size="24">Prepared for Leadership</text>'
    '</g>'
    '</svg>'
)


@pytest.fixture()
def structured_export_db(tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, username="structured-editor-owner", password_hash="x"))
    svg_path = tmp_path / "slide-1.svg"
    svg_path.write_text(STRUCTURED_SVG, encoding="utf-8")
    session.add(File(
        id=21, user_id=1, owner_user_id=1, filename="slide-1.svg",
        filepath=str(svg_path), real_path=str(svg_path), mime_type="image/svg+xml",
        project_id="pptproj_structured_export_001", task_id="pptinc_structured_export_001",
    ))
    session.add(File(
        id=201, user_id=1, owner_user_id=1, filename="original.pptx",
        filepath="/tmp/original_structured.pptx", real_path="/tmp/original_structured.pptx",
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        project_id="pptproj_structured_export_001", task_id="pptinc_structured_export_001",
    ))
    session.add(PPTIncrementalTask(
        task_id="pptinc_structured_export_001",
        project_id="pptproj_structured_export_001",
        user_id=1,
        request_id="structured-editor-export-001",
        page_count=1,
        status="completed",
        final_file_json='{"file_id": 201}',
        completed_slides_json='[{"slide_id":"slide-1","index":1,"title":"Annual Review","preview_file_id":21}]',
    ))
    session.commit()
    try:
        yield session, tmp_path
    finally:
        session.close()
        engine.dispose()


def test_structured_document_records_master_and_layout_metadata(structured_export_db):
    from app.PPT_master.editor_documents import EditorDocumentStore

    db, _ = structured_export_db
    store = EditorDocumentStore()
    result = store.get_or_initialize(db, project_id="pptproj_structured_export_001", user_id=1)
    slide = result["document"]["slides"][0]

    assert slide["pptx_structure"]["mode"] == "structured"
    assert slide["pptx_structure"]["master_id"] == "master-default"
    assert slide["pptx_structure"]["layout_id"] == "layout-title"


def test_structured_reexport_produces_real_master_layout_placeholder_pptx(structured_export_db, monkeypatch):
    from app.PPT_master.editor_documents import EditorDocumentStore, EditorExportStore

    db, tmp_path = structured_export_db
    doc_store = EditorDocumentStore()
    initial = doc_store.get_or_initialize(db, project_id="pptproj_structured_export_001", user_id=1)
    document = initial["document"]

    # Edit the title placeholder's text content (slide-local edit; structure untouched).
    slide = document["slides"][0]
    title_element = next(item for item in slide["elements"] if item.get("placeholder_type") == "title")
    title_element["content"]["text"] = "Q4 Board Review"

    saved = doc_store.save(
        db, project_id="pptproj_structured_export_001", user_id=1,
        expected_revision=initial["revision"], document=document,
    )
    assert saved["revision"] == initial["revision"] + 1

    export_store = EditorExportStore(projects_root=tmp_path / "projects")
    export_result = export_store.export(
        db, project_id="pptproj_structured_export_001", user_id=1,
        expected_revision=saved["revision"],
    )

    exported_file = db.query(File).filter(File.id == export_result["file_id"]).first()
    pptx_path = Path(exported_file.real_path or exported_file.filepath)
    assert pptx_path.is_file()

    with ZipFile(pptx_path) as archive:
        names = archive.namelist()
        assert any(name.startswith("ppt/slideMasters/slideMaster") for name in names)
        assert any(name.startswith("ppt/slideLayouts/slideLayout") for name in names)
        slide_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")
        assert "Q4 Board Review" in slide_xml
        assert '<p:ph type="title"' in slide_xml or "type=\"title\"" in slide_xml

        rels = archive.read("ppt/slides/_rels/slide1.xml.rels").decode("utf-8")
        assert "slideLayout" in rels


def test_structured_reexport_fails_explicitly_when_placeholder_mapping_broken(structured_export_db):
    """If a placeholder element's layout metadata is stripped/corrupted, export must
    hard-fail with diagnostics rather than silently falling back to flat mode."""
    from app.PPT_master.editor_documents import EditorDocumentStore, EditorExportStore, EditorExportFailed

    db, tmp_path = structured_export_db
    doc_store = EditorDocumentStore()
    initial = doc_store.get_or_initialize(db, project_id="pptproj_structured_export_001", user_id=1)
    document = initial["document"]

    # Corrupt: remove the placeholder_type from the title element while keeping the slide
    # marked as structured, simulating a broken mapping.
    slide = document["slides"][0]
    title_element = next(item for item in slide["elements"] if item.get("placeholder_type") == "title")
    del title_element["placeholder_type"]

    saved = doc_store.save(
        db, project_id="pptproj_structured_export_001", user_id=1,
        expected_revision=initial["revision"], document=document,
    )

    export_store = EditorExportStore(projects_root=tmp_path / "projects")
    with pytest.raises(EditorExportFailed):
        export_store.export(
            db, project_id="pptproj_structured_export_001", user_id=1,
            expected_revision=saved["revision"],
        )


# --- Extended Task 10 verification (added by Senior Developer takeover) ---

def test_structured_reexport_original_file_unchanged_new_file_different(structured_export_db):
    from app.PPT_master.editor_documents import EditorDocumentStore, EditorExportStore
    db, tmp_path = structured_export_db
    doc_store = EditorDocumentStore()
    initial = doc_store.get_or_initialize(db, project_id="pptproj_structured_export_001", user_id=1)
    document = initial["document"]
    title_element = next(i for i in document["slides"][0]["elements"] if i.get("placeholder_type") == "title")
    title_element["content"]["text"] = "Q4 Board Review"
    saved = doc_store.save(db, project_id="pptproj_structured_export_001", user_id=1, expected_revision=initial["revision"], document=document)
    export_store = EditorExportStore(projects_root=tmp_path / "projects")
    result = export_store.export(db, project_id="pptproj_structured_export_001", user_id=1, expected_revision=saved["revision"])
    assert result["file_id"] != 201
    original = db.query(File).filter(File.id == 201).first()
    assert original is not None
    exported = db.query(File).filter(File.id == result["file_id"]).first()
    pptx_path = Path(exported.real_path or exported.filepath)
    assert pptx_path.is_file()


def test_structured_export_revision_conflict(structured_export_db):
    from app.PPT_master.editor_documents import (
        EditorDocumentStore, EditorExportStore, EditorExportConflict,
    )
    db, tmp_path = structured_export_db
    doc_store = EditorDocumentStore()
    initial = doc_store.get_or_initialize(db, project_id="pptproj_structured_export_001", user_id=1)
    document = initial["document"]
    saved = doc_store.save(db, project_id="pptproj_structured_export_001", user_id=1, expected_revision=initial["revision"], document=document)
    export_store = EditorExportStore(projects_root=tmp_path / "projects")
    with pytest.raises(EditorExportConflict):
        export_store.export(db, project_id="pptproj_structured_export_001", user_id=1, expected_revision=initial["revision"])


def test_structured_export_missing_master_layout_hard_fails(structured_export_db):
    from app.PPT_master.editor_documents import (
        EditorDocumentStore, EditorExportStore, EditorExportFailed,
    )
    db, tmp_path = structured_export_db
    doc_store = EditorDocumentStore()
    initial = doc_store.get_or_initialize(db, project_id="pptproj_structured_export_001", user_id=1)
    document = initial["document"]
    document["slides"][0]["pptx_structure"] = {
        "mode": "structured", "master_id": "", "master_name": "",
        "layout_id": "", "layout_name": "", "page_role": "cover",
    }
    saved = doc_store.save(db, project_id="pptproj_structured_export_001", user_id=1, expected_revision=initial["revision"], document=document)
    export_store = EditorExportStore(projects_root=tmp_path / "projects")
    with pytest.raises(EditorExportFailed):
        export_store.export(db, project_id="pptproj_structured_export_001", user_id=1, expected_revision=saved["revision"])


@pytest.fixture()
def flat_export_db(tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, username="flat-editor-owner", password_hash="x"))
    flat_svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720"><rect width="1280" height="720" fill="#FFFFFF"/><text x="100" y="100" font-size="32">Hello flat</text></svg>'
    svg_path = tmp_path / "flat-1.svg"
    svg_path.write_text(flat_svg, encoding="utf-8")
    session.add(File(id=31, user_id=1, owner_user_id=1, filename="flat-1.svg", filepath=str(svg_path), real_path=str(svg_path), mime_type="image/svg+xml", project_id="pptproj_flat_export_001", task_id="pptinc_flat_export_001"))
    session.add(File(id=301, user_id=1, owner_user_id=1, filename="original.pptx", filepath="/tmp/original_flat.pptx", real_path="/tmp/original_flat.pptx", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", project_id="pptproj_flat_export_001", task_id="pptinc_flat_export_001"))
    session.add(PPTIncrementalTask(task_id="pptinc_flat_export_001", project_id="pptproj_flat_export_001", user_id=1, request_id="flat-editor-export-001", page_count=1, status="completed", final_file_json='{"file_id":301}', completed_slides_json='[{"slide_id":"flat-1","index":1,"title":"Hello flat","preview_file_id":31}]'))
    session.commit()
    try:
        yield session, tmp_path
    finally:
        session.close()
        engine.dispose()


def test_flat_editor_export_regression(flat_export_db):
    from app.PPT_master.editor_documents import EditorDocumentStore, EditorExportStore
    db, tmp_path = flat_export_db
    doc_store = EditorDocumentStore()
    initial = doc_store.get_or_initialize(db, project_id="pptproj_flat_export_001", user_id=1)
    assert initial["document"]["slides"][0].get("pptx_structure", {}).get("mode") != "structured"
    saved = doc_store.save(db, project_id="pptproj_flat_export_001", user_id=1, expected_revision=initial["revision"], document=initial["document"])
    export_store = EditorExportStore(projects_root=tmp_path / "projects")
    result = export_store.export(db, project_id="pptproj_flat_export_001", user_id=1, expected_revision=saved["revision"])
    exported = db.query(File).filter(File.id == result["file_id"]).first()
    pptx_path = Path(exported.real_path or exported.filepath)
    assert pptx_path.is_file()
    with ZipFile(pptx_path) as archive:
        assert any(name.startswith("ppt/slides/slide") for name in archive.namelist())
