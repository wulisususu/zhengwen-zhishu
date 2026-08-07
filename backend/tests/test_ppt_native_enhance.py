from __future__ import annotations

import hashlib

import pytest
from zipfile import ZipFile
from xml.etree import ElementTree as ET


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_pptx(path):
    presentation = """<p:presentation xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><p:sldIdLst><p:sldId id=\"256\" r:id=\"rId1\"/></p:sldIdLst></p:presentation>"""
    slide = """<p:sld xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\" xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\"><p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id=\"2\" name=\"Title\"/></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Title</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld><p:transition spd=\"slow\" advTm=\"5000\"><p:fade/></p:transition><p:timing><p:tnLst/></p:timing></p:sld>"""
    rels = """<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide\" Target=\"slides/slide1.xml\"/></Relationships>"""
    slide_rels = """<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rIdExt\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink\" Target=\"https://example.test\" TargetMode=\"External\"/></Relationships>"""
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>")
        archive.writestr("ppt/presentation.xml", presentation)
        archive.writestr("ppt/_rels/presentation.xml.rels", rels)
        archive.writestr("ppt/slides/slide1.xml", slide)
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", slide_rels)
        archive.writestr("ppt/notesSlides/notesSlide1.xml", "<p:notes xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\"/>")


def test_native_enhance_analysis_and_none_transition_preserves_timing(tmp_path):
    from app.PPT_master.native_enhance import analyze_native_pptx, apply_native_enhancement

    source = tmp_path / "source.pptx"
    output = tmp_path / "output.pptx"
    _fixture_pptx(source)
    source_sha = _sha256(source)

    analysis = analyze_native_pptx(source)

    assert analysis["slide_count"] == 1
    assert analysis["slides"][0]["transition"]["type"] == "fade"
    assert analysis["slides"][0]["has_timing"] is True
    assert analysis["slides"][0]["has_notes_slide"] is True
    assert analysis["external_relationships"][0]["target"] == "https://example.test"

    report = apply_native_enhancement(source, output, {"transition_type": "none", "application_scope": "all"})

    assert _sha256(source) == source_sha
    assert report["changed_slide_count"] == 1
    with ZipFile(output) as archive:
        xml = archive.read("ppt/slides/slide1.xml")
        assert b"<p:transition" not in xml
        assert b"<p:timing" in xml
        assert "ppt/notesSlides/notesSlide1.xml" in archive.namelist()


def test_native_enhance_fade_keeps_existing_timing(tmp_path):
    from app.PPT_master.native_enhance import apply_native_enhancement

    source = tmp_path / "source.pptx"
    output = tmp_path / "output.pptx"
    _fixture_pptx(source)

    report = apply_native_enhancement(source, output, {"transition_type": "fade", "application_scope": "all", "duration_ms": 500, "advance_on_click": False, "auto_advance_ms": 1200})

    assert report["changed_slide_count"] == 1
    with ZipFile(output) as archive:
        xml = archive.read("ppt/slides/slide1.xml")
        assert b"<p:fade" in xml
        assert b"advTm=\"1200\"" in xml
        assert b"advClick=\"0\"" in xml
        assert b"<p:timing" in xml


def test_native_enhance_analyze_api_is_owner_scoped(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.database import Base, get_db
    from app.deps import get_current_user
    from app.models import File, User
    from app.PPT_master.native_enhance_router import router

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    source = tmp_path / "owned.pptx"
    _fixture_pptx(source)
    owner = User(id=1, username="123", password_hash="x")
    db.add_all([owner, File(id=401, user_id=1, owner_user_id=1, filename="owned.pptx", filepath=str(source), real_path=str(source), filetype=".pptx", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")])
    db.commit()
    app = FastAPI(); app.include_router(router, prefix="/api/v1")
    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: owner
    monkeypatch.setenv("PPT_NATIVE_ENHANCE_ALLOWED_USERS", "123")

    with TestClient(app) as client:
        response = client.post("/api/v1/ppt-master/enhance/analyze", json={"source_file_id": 401})

    assert response.status_code == 200
    assert response.json()["data"]["source_sha256"] == _sha256(source)


def test_native_enhance_task_is_append_only_and_rejects_sha_drift(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.database import Base
    from app.models import File, User
    from app.PPT_master.native_enhance_store import NativeEnhanceError, NativeEnhanceStore

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    source = tmp_path / "source.pptx"
    _fixture_pptx(source)
    source_sha = _sha256(source)
    db.add_all([User(id=1, username="123", password_hash="x"), File(id=501, user_id=1, owner_user_id=1, filename="source.pptx", filepath=str(source), real_path=str(source), filetype=".pptx", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", sha256=source_sha)])
    db.commit()
    store = NativeEnhanceStore(projects_root=tmp_path / "artifacts")

    with pytest.raises(NativeEnhanceError, match="native_enhance_source_sha_changed"):
        store.create_task(db, user_id=1, source_file_id=501, expected_sha256="0" * 64, options={"transition_type": "none", "application_scope": "all"})

    task = store.create_task(db, user_id=1, source_file_id=501, expected_sha256=source_sha, options={"transition_type": "none", "application_scope": "all"})

    assert task["status"] == "completed"
    assert task["source_file_id"] == 501
    assert task["output_file_id"] != 501
    assert _sha256(source) == source_sha


def test_native_enhance_task_api_creates_and_reads_owned_output(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.database import Base, get_db
    from app.deps import get_current_user
    from app.models import File, User
    from app.PPT_master.native_enhance_router import router

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine); db = sessionmaker(bind=engine)()
    source = tmp_path / "api-source.pptx"; _fixture_pptx(source); source_sha = _sha256(source)
    owner = User(id=1, username="123", password_hash="x")
    db.add_all([owner, File(id=601, user_id=1, owner_user_id=1, filename="source.pptx", filepath=str(source), real_path=str(source), filetype=".pptx", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", sha256=source_sha)]); db.commit()
    app = FastAPI(); app.include_router(router, prefix="/api/v1")
    def override_db(): yield db
    app.dependency_overrides[get_db] = override_db; app.dependency_overrides[get_current_user] = lambda: owner
    monkeypatch.setenv("PPT_NATIVE_ENHANCE_ALLOWED_USERS", "123")
    monkeypatch.setattr("app.PPT_master.native_enhance_router.NativeEnhanceStore", lambda: __import__("app.PPT_master.native_enhance_store", fromlist=["NativeEnhanceStore"]).NativeEnhanceStore(projects_root=tmp_path / "artifacts"))
    with TestClient(app) as client:
        created = client.post("/api/v1/ppt-master/enhance/tasks", json={"source_file_id": 601, "expected_sha256": source_sha, "options": {"transition_type": "none", "application_scope": "all"}})
        task_id = created.json()["data"]["task_id"]
        fetched = client.get(f"/api/v1/ppt-master/enhance/tasks/{task_id}")
    assert created.status_code == 200
    assert fetched.status_code == 200
    assert fetched.json()["data"]["output_file_id"] != 601


def test_native_enhance_footer_fields_are_idempotent(tmp_path):
    from app.PPT_master.native_enhance import apply_native_enhancement

    source = tmp_path / "source.pptx"; first = tmp_path / "first.pptx"; second = tmp_path / "second.pptx"
    _fixture_pptx(source)
    options = {"transition_type": "keep", "page_number": {"enabled": True}, "footer": {"enabled": True, "text": "内部资料"}, "date": {"enabled": True, "text": "2026-07-23"}}

    apply_native_enhancement(source, first, options)
    apply_native_enhancement(first, second, options)

    with ZipFile(second) as archive:
        xml = archive.read("ppt/slides/slide1.xml")
        assert xml.count(b'AIBox_PageNumber') == 1
        assert xml.count(b'AIBox_Footer') == 1
        assert xml.count(b'AIBox_Date') == 1


def test_native_enhance_removes_only_external_relationships_when_requested(tmp_path):
    from app.PPT_master.native_enhance import apply_native_enhancement

    source = tmp_path / "source.pptx"; output = tmp_path / "output.pptx"; _fixture_pptx(source)
    apply_native_enhancement(source, output, {"transition_type": "keep", "remove_external_relationships": True})

    with ZipFile(output) as archive:
        rels = archive.read("ppt/slides/_rels/slide1.xml.rels")
        assert b"TargetMode=\"External\"" not in rels
        assert "ppt/notesSlides/notesSlide1.xml" in archive.namelist()


def test_native_enhance_writes_standard_document_properties(tmp_path):
    from app.PPT_master.native_enhance import apply_native_enhancement

    source = tmp_path / "source.pptx"; output = tmp_path / "output.pptx"; _fixture_pptx(source)
    apply_native_enhancement(source, output, {"transition_type": "keep", "document_properties": {"title": "季度复盘", "author": "AI Box", "keywords": "增长,复盘", "company": "中科信创"}})

    with ZipFile(output) as archive:
        core = archive.read("docProps/core.xml")
        app = archive.read("docProps/app.xml")
        assert "季度复盘" in core.decode("utf-8")
        assert "AI Box" in core.decode("utf-8")
        assert "中科信创" in app.decode("utf-8")


def test_task_request_validates_advanced_options():
    from pydantic import ValidationError
    from app.PPT_master.native_enhance_router import NativeEnhanceTaskRequest

    request = NativeEnhanceTaskRequest.model_validate({
        "source_file_id": 7,
        "expected_sha256": "a" * 64,
        "options": {
            "transition_type": "wipe",
            "duration_ms": 700,
            "advance_on_click": False,
            "auto_advance_ms": 4200,
            "page_number": {"enabled": True, "text": "第 {page} 页", "font_size_pt": 10, "color": "334155", "position": "bottom_right"},
        },
    })
    assert request.options.duration_ms == 700
    with pytest.raises(ValidationError):
        NativeEnhanceTaskRequest.model_validate({
            "source_file_id": 7, "expected_sha256": "a" * 64,
            "options": {"transition_type": "zoom", "duration_ms": -1},
        })
    with pytest.raises(ValidationError):
        NativeEnhanceTaskRequest.model_validate({
            "source_file_id": 7, "expected_sha256": "a" * 64,
            "options": {"page_number": {"enabled": True, "slide_ids": [-1]}},
        })


def test_footer_field_applies_native_style_and_its_own_slide_scope(tmp_path):
    from app.PPT_master.native_enhance import NS, apply_native_enhancement

    source = tmp_path / "source.pptx"
    _fixture_pptx(source)
    output = tmp_path / "enhanced.pptx"
    apply_native_enhancement(source, output, {
        "page_number": {
            "enabled": True, "text": "第 {page} 页", "font_size_pt": 11,
            "color": "EF4444", "position": "bottom_left",
            "application_scope": "selected", "slide_ids": [1],
        },
    })
    with ZipFile(output) as archive:
        root = ET.fromstring(archive.read("ppt/slides/slide1.xml"))
    field = next(node for node in root.findall(".//p:sp", NS) if node.find(".//p:cNvPr", NS).attrib.get("name") == "AIBox_PageNumber")
    assert field.find(".//a:t", NS).text == "第 1 页"
    assert field.find(".//a:rPr", NS).attrib["sz"] == "1100"
    assert field.find(".//a:srgbClr", NS).attrib["val"] == "EF4444"
    assert field.find(".//a:off", NS).attrib["x"] == "914400"
    assert field.find("p:spPr/a:prstGeom", NS).attrib["prst"] == "rect"


def test_native_enhance_output_validator_parses_every_xml_part(tmp_path):
    from app.PPT_master.native_enhance import apply_native_enhancement, validate_native_pptx

    source = tmp_path / "source.pptx"
    output = tmp_path / "output.pptx"
    _fixture_pptx(source)
    apply_native_enhancement(source, output, {"transition_type": "fade"})
    validation = validate_native_pptx(output)
    assert validation["zip_valid"] is True
    assert validation["xml_part_count"] >= 4
    assert validation["slide_count"] == 1
