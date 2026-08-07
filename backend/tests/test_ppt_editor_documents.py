from __future__ import annotations

import pytest
from zipfile import ZipFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import File, PPTIncrementalTask, User


def editable_text(document):
    return next(item for item in document["slides"][0]["elements"] if item["type"] == "text")


@pytest.fixture()
def db_session(tmp_path):
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
        '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
        '<rect x="10" y="20" width="120" height="80" fill="#ffffff" stroke="#112233"/>'
        '<text x="80" y="160" font-size="32" font-weight="700" fill="#334455">编辑标题</text>'
        '<path d="M 0 0 L 20 20" fill="#000"/>'
        '</svg>',
        encoding="utf-8",
    )
    session.add(File(id=11, user_id=1, owner_user_id=1, filename="slide-1.svg", filepath=str(svg_path), real_path=str(svg_path), mime_type="image/svg+xml", project_id="pptproj_editor_001", task_id="pptinc_editor_001"))
    session.add(File(id=101, user_id=1, owner_user_id=1, filename="original.pptx", filepath="/tmp/original.pptx", real_path="/tmp/original.pptx", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", project_id="pptproj_editor_001", task_id="pptinc_editor_001"))
    session.add(PPTIncrementalTask(
        task_id="pptinc_editor_001",
        project_id="pptproj_editor_001",
        user_id=1,
        request_id="editor-document-001",
        page_count=1,
        status="completed",
        final_file_json='{"file_id": 101}',
        completed_slides_json='[{"slide_id":"slide-1","index":1,"title":"原始标题","preview_file_id":11}]',
    ))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_initialization_creates_one_mutable_draft_without_changing_original_file(db_session):
    from app.PPT_master.editor_documents import EditorDocumentStore

    store = EditorDocumentStore()
    first = store.get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)
    second = store.get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)

    assert first["original_file_id"] == 101
    assert first["revision"] == 1
    assert editable_text(first["document"])["content"]["text"] == "编辑标题"
    assert second["document_id"] == first["document_id"]
    assert db_session.query(PPTIncrementalTask).one().final_file_json == '{"file_id": 101}'


def test_initialization_builds_stable_normalized_svg_elements_and_preserves_locked_vector(db_session):
    from app.PPT_master.editor_documents import EditorDocumentStore

    store = EditorDocumentStore()
    first = store.get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)
    second = store.get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)
    elements = first["document"]["slides"][0]["elements"]

    assert [item["type"] for item in elements] == ["rect", "text", "lockedVector"]
    assert elements[0]["style"] == {"fill": "#ffffff", "stroke": "#112233", "opacity": 1}
    assert elements[1]["content"]["text"] == "编辑标题"
    assert elements[1]["style"]["font_size"] == 32
    assert elements[2]["locked"] is True
    assert "path" in elements[2]["content"]["svg"]
    assert [item["id"] for item in second["document"]["slides"][0]["elements"]] == [item["id"] for item in elements]


def test_save_rejects_stale_revision_and_keeps_latest_document(db_session):
    from app.PPT_master.editor_documents import EditorDocumentConflict, EditorDocumentStore

    store = EditorDocumentStore()
    draft = store.get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)
    updated_document = draft["document"]
    editable_text(updated_document)["content"]["text"] = "已编辑标题"

    saved = store.save(
        db_session,
        project_id="pptproj_editor_001",
        user_id=1,
        expected_revision=1,
        document=updated_document,
    )

    assert saved["revision"] == 2
    with pytest.raises(EditorDocumentConflict):
        store.save(
            db_session,
            project_id="pptproj_editor_001",
            user_id=1,
            expected_revision=1,
            document=draft["document"],
        )
    assert editable_text(store.get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)["document"])["content"]["text"] == "已编辑标题"


def test_editor_api_is_owner_scoped_and_rejects_stale_save(db_session, monkeypatch):
    monkeypatch.setenv("PPT_P0_ALLOWED_USERS", "editor-owner")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.PPT_master.editor_router import router
    from app.database import get_db
    from app.deps import get_current_user

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    owner = db_session.query(User).filter(User.id == 1).one()
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: owner

    with TestClient(app) as client:
        initial = client.get("/api/v1/ppt-master/projects/pptproj_editor_001/editor")
        assert initial.status_code == 200
        draft = initial.json()["data"]
        editable_text(draft["document"])["content"]["text"] = "接口保存标题"
        saved = client.patch(
            "/api/v1/ppt-master/projects/pptproj_editor_001/editor",
            json={"expected_revision": draft["revision"], "document": draft["document"]},
        )
        assert saved.status_code == 200
        assert saved.json()["data"]["revision"] == 2
        stale = client.patch(
            "/api/v1/ppt-master/projects/pptproj_editor_001/editor",
            json={"expected_revision": 1, "document": draft["document"]},
        )
    assert stale.status_code == 409
    assert stale.json()["detail"]["revision"] == 2


def test_save_rejects_dangerous_locked_vector_and_keeps_revision(db_session):
    from app.PPT_master.editor_documents import EditorDocumentStore

    store = EditorDocumentStore()
    draft = store.get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)
    draft["document"]["slides"][0]["elements"][-1]["content"]["svg"] = "<script>alert(1)</script>"

    with pytest.raises(ValueError, match="editor_document_invalid"):
        store.save(db_session, project_id="pptproj_editor_001", user_id=1, expected_revision=1, document=draft["document"])
    assert store.get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)["revision"] == 1


def test_recent_projects_are_owner_scoped_and_expose_editor_metadata(db_session):
    from app.PPT_master.editor_documents import EditorProjectStore

    db_session.add(User(id=2, username="another-owner", password_hash="x"))
    db_session.add(PPTIncrementalTask(
        task_id="pptinc_editor_002",
        project_id="pptproj_editor_002",
        user_id=2,
        request_id="editor-document-002",
        page_count=2,
        status="completed",
        final_file_json='{"file_id": 999}',
        completed_slides_json='[]',
    ))
    db_session.commit()

    projects = EditorProjectStore().recent(db_session, user_id=1)

    assert [item["project_id"] for item in projects] == ["pptproj_editor_001"]
    assert projects[0]["task_id"] == "pptinc_editor_001"
    assert projects[0]["original_file_id"] == 101
    assert projects[0]["preview_file_id"] == 11
    assert projects[0]["editor_supported"] is True
    assert projects[0]["editor_revision"] == 1


def test_recent_projects_api_uses_authenticated_owner(db_session, monkeypatch):
    monkeypatch.setenv("PPT_P0_ALLOWED_USERS", "editor-owner")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.PPT_master.editor_router import router
    from app.database import get_db
    from app.deps import get_current_user

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    owner = db_session.query(User).filter(User.id == 1).one()

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: owner
    with TestClient(app) as client:
        response = client.get("/api/v1/ppt-master/projects/recent")

    assert response.status_code == 200
    assert response.json()["data"][0]["project_id"] == "pptproj_editor_001"


def test_editor_export_is_append_only_and_locks_the_requested_revision(db_session, tmp_path, monkeypatch):
    import app.PPT_master.editor_documents as editor_documents
    from app.PPT_master.editor_documents import EditorDocumentStore, EditorExportStore, EditorProjectStore
    from app.models import PPTEditorExport
    from app.services.artifact_service import ArtifactService

    draft = EditorDocumentStore().get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)
    editable_text(draft["document"])["content"]["text"] = "导出后的标题"
    saved = EditorDocumentStore().save(db_session, project_id="pptproj_editor_001", user_id=1, expected_revision=1, document=draft["document"])
    projects_root = tmp_path / "projects"

    def fake_converter(workspace, page_count):
        assert page_count == 1
        assert "导出后的标题" in (workspace / "svg_output" / "page_01.svg").read_text(encoding="utf-8")
        output = workspace / "exports" / "edited.pptx"
        output.parent.mkdir()
        output.write_bytes(b"not-the-original-pptx")
        return output

    monkeypatch.setattr(editor_documents, "validate_pptx", lambda _path, expected_pages: {"passed": True, "blocking_errors": [], "errors": []})
    result = EditorExportStore(
        projects_root=projects_root,
        artifact_service=ArtifactService(projects_root=projects_root, legacy_roots=[]),
        command_runner=fake_converter,
    ).export(db_session, project_id="pptproj_editor_001", user_id=1, expected_revision=saved["revision"])

    assert result["revision"] == 2
    assert result["file_id"] != 101
    assert db_session.query(PPTEditorExport).one().file_id == result["file_id"]
    assert db_session.query(PPTIncrementalTask).one().final_file_json == '{"file_id": 101}'
    assert EditorProjectStore().recent(db_session, user_id=1)[0]["last_export_file_id"] == result["file_id"]


def test_editor_export_runs_real_quality_finalize_and_pptx_converter(db_session, tmp_path):
    from app.PPT_master.editor_documents import EditorDocumentStore, EditorExportStore, _write_editor_workspace
    from app.PPT_master.validation import validate_pptx

    draft = EditorDocumentStore().get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)
    editable_text(draft["document"])["content"]["text"] = "Real converted title"
    workspace = tmp_path / "real-editor-export"
    pages = _write_editor_workspace(workspace, draft["document"])
    pptx_path = EditorExportStore(projects_root=tmp_path)._run_converter(workspace, pages)

    assert validate_pptx(str(pptx_path), expected_pages=1)["passed"] is True
    with ZipFile(pptx_path) as archive:
        names = set(archive.namelist())
        slide_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")
    assert "ppt/slides/slide1.xml" in names
    assert "<p:sp" in slide_xml and "Real converted title" in slide_xml


def test_editor_export_api_returns_a_new_downloadable_file(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("PPT_P0_ALLOWED_USERS", "editor-owner")
    import app.PPT_master.editor_documents as editor_documents
    import app.PPT_master.editor_router as editor_router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.PPT_master.editor_documents import EditorExportStore
    from app.database import get_db
    from app.deps import get_current_user
    from app.services.artifact_service import ArtifactService

    projects_root = tmp_path / "projects"

    def fake_converter(workspace, _page_count):
        output = workspace / "exports" / "edited.pptx"
        output.parent.mkdir()
        output.write_bytes(b"edited-pptx")
        return output

    monkeypatch.setattr(editor_documents, "validate_pptx", lambda _path, expected_pages: {"passed": True, "blocking_errors": [], "errors": []})
    monkeypatch.setattr(editor_router, "_exports", EditorExportStore(
        projects_root=projects_root, artifact_service=ArtifactService(projects_root=projects_root, legacy_roots=[]), command_runner=fake_converter,
    ))
    app = FastAPI()
    app.include_router(editor_router.router, prefix="/api/v1")
    owner = db_session.query(User).filter(User.id == 1).one()

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: owner
    with TestClient(app) as client:
        response = client.post("/api/v1/ppt-master/projects/pptproj_editor_001/editor/export", json={"expected_revision": 1})

    assert response.status_code == 200
    assert response.json()["data"]["file_id"] != 101
    assert db_session.query(PPTIncrementalTask).one().final_file_json == '{"file_id": 101}'


def test_save_rejects_any_locked_vector_mutation(db_session):
    from app.PPT_master.editor_documents import EditorDocumentStore

    store = EditorDocumentStore()
    draft = store.get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)
    locked = next(item for item in draft["document"]["slides"][0]["elements"] if item["type"] == "lockedVector")
    locked["x"] = 240

    with pytest.raises(ValueError, match="editor_document_invalid"):
        store.save(db_session, project_id="pptproj_editor_001", user_id=1, expected_revision=1, document=draft["document"])
    assert store.get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)["revision"] == 1


def test_editor_export_stages_authorized_image_as_native_picture(db_session, tmp_path):
    from PIL import Image
    from app.PPT_master.editor_documents import EditorDocumentStore, EditorExportStore
    from app.PPT_master.media_assets import PptMediaResolver

    image_path = tmp_path / "provided.png"
    Image.new("RGB", (32, 18), "#336699").save(image_path)
    db_session.add(File(id=302, user_id=1, owner_user_id=1, filename="provided.png", filepath=str(image_path), real_path=str(image_path), mime_type="image/png"))
    db_session.commit()
    asset = PptMediaResolver().register_file(db_session, file_id=302, owner_user_id=1, source_type="uploaded", project_id="pptproj_editor_001")
    draft = EditorDocumentStore().get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)
    draft["document"]["slides"][0]["elements"].append({
        "id": "image_302", "type": "image", "asset_id": asset["asset_id"],
        "x": 500, "y": 120, "width": 240, "height": 135, "fit": "cover",
        "crop": {"left": 0, "top": 0, "right": 0, "bottom": 0}, "rotation": 0,
        "z_index": 9, "content": {}, "style": {},
    })
    saved = EditorDocumentStore().save(db_session, project_id="pptproj_editor_001", user_id=1, expected_revision=draft["revision"], document=draft["document"])
    result = EditorExportStore(projects_root=tmp_path / "projects").export(db_session, project_id="pptproj_editor_001", user_id=1, expected_revision=saved["revision"])
    exported = db_session.query(File).filter(File.id == result["file_id"]).one()
    with ZipFile(exported.real_path) as archive:
        names = set(archive.namelist())
        slide_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")
    assert any(name.startswith("ppt/media/") for name in names)
    assert "<p:pic>" in slide_xml


def test_editor_save_rejects_image_asset_not_authorized_for_this_project(db_session):
    from app.PPT_master.editor_documents import EditorDocumentStore

    store = EditorDocumentStore()
    draft = store.get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)
    draft["document"]["slides"][0]["elements"].append({
        "id": "image_not_authorized", "type": "image", "asset_id": "pptimg_missing",
        "x": 1, "y": 1, "width": 100, "height": 80, "fit": "cover",
        "crop": {"left": 0, "top": 0, "right": 0, "bottom": 0}, "content": {}, "style": {}, "locked": False,
    })

    with pytest.raises(ValueError, match="editor_image_unauthorized"):
        store.save(db_session, project_id="pptproj_editor_001", user_id=1, expected_revision=1, document=draft["document"])


def test_editor_export_converts_native_chart_and_table_to_ooxml(db_session, tmp_path):
    from app.PPT_master.editor_documents import EditorDocumentStore, EditorExportStore, _write_editor_workspace

    draft = EditorDocumentStore().get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)
    draft["document"]["slides"][0]["elements"].extend([
        {"id": "chart-1", "type": "chart", "x": 80, "y": 260, "width": 420, "height": 260, "rotation": 0, "z_index": 5, "locked": False,
         "content": {"chart_type": "column", "title": "季度销售", "categories": ["Q1", "Q2"], "series": [{"name": "销售额", "values": [12, 24]}], "source_refs": [{"file_id": 101, "sheet": "数据", "range": "A1:B3"}]}},
        {"id": "table-1", "type": "table", "x": 520, "y": 260, "width": 480, "height": 180, "rotation": 0, "z_index": 6, "locked": False,
         "content": {"columns": ["项目", "数值"], "rows": [["收入", "24"], ["成本", "12"]], "source_refs": [{"file_id": 101, "page": "1"}]}}
    ])
    workspace = tmp_path / "native-editor-export"
    pages = _write_editor_workspace(workspace, draft["document"])
    assert '"chart-1"' in (workspace / "native_data.json").read_text(encoding="utf-8")
    pptx_path = EditorExportStore(projects_root=tmp_path)._run_converter(workspace, pages)
    with ZipFile(pptx_path) as archive:
        names = set(archive.namelist())
        slide_xml = archive.read("ppt/slides/slide1.xml")
    assert any(name.startswith("ppt/charts/chart") for name in names)
    assert any(name.startswith("ppt/embeddings/") for name in names)
    assert b"c:chart" in slide_xml
    assert b"a:tbl" in slide_xml


def test_native_data_rejects_nonfinite_values_and_formula_cells(db_session):
    from app.PPT_master.editor_documents import EditorDocumentStore

    draft = EditorDocumentStore().get_or_initialize(db_session, project_id="pptproj_editor_001", user_id=1)
    draft["document"]["slides"][0]["elements"].append({"id":"bad-chart", "type":"chart", "x":1,"y":1,"width":100,"height":100,"content":{"chart_type":"line","categories":["A"],"series":[{"name":"S","values":[float("nan")]}]}})
    with pytest.raises(ValueError, match="native_chart_values_invalid"):
        EditorDocumentStore().save(db_session, project_id="pptproj_editor_001", user_id=1, expected_revision=1, document=draft["document"])
    draft["document"]["slides"][0]["elements"].pop()
    draft["document"]["slides"][0]["elements"].append({"id":"bad-table", "type":"table", "x":1,"y":1,"width":100,"height":100,"content":{"columns":["A"],"rows":[["=unsafe"]]}})
    with pytest.raises(ValueError, match="native_table_formula_unsafe"):
        EditorDocumentStore().save(db_session, project_id="pptproj_editor_001", user_id=1, expected_revision=1, document=draft["document"])


def test_history_project_api_returns_durable_slides_and_export_for_owner(db_session, monkeypatch):
    monkeypatch.setenv("PPT_P0_ALLOWED_USERS", "editor-owner")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.PPT_master.editor_router import router
    from app.database import get_db
    from app.deps import get_current_user

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    owner = db_session.query(User).filter(User.id == 1).one()

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: owner
    with TestClient(app) as client:
        response = client.get("/api/v1/ppt-master/projects/pptproj_editor_001/history")

    assert response.status_code == 200
    project = response.json()["data"]["project"]
    assert project["id"] == "pptproj_editor_001"
    assert project["title"] == "原始标题"
    assert project["presentation"]["slides"] == [{
        "id": "slide-1", "index": 1, "title": "原始标题", "status": "ready",
        "elements": [], "previewArtifactId": 11, "thumbnailArtifactId": 11,
        "speakerNotes": "", "userModifiedFields": [], "revision": 1,
    }]
    assert project["exportArtifact"]["fileId"] == 101
    assert project["exportArtifact"]["downloadUrl"] == "/api/v1/files/101/download"


def test_history_project_api_rejects_another_users_project(db_session, monkeypatch):
    monkeypatch.setenv("PPT_P0_ALLOWED_USERS", "editor-owner")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.PPT_master.editor_router import router
    from app.database import get_db
    from app.deps import get_current_user

    db_session.add(User(id=2, username="other-owner", password_hash="x"))
    db_session.add(PPTIncrementalTask(
        task_id="pptinc_private_002", project_id="pptproj_private_002", user_id=2, request_id="private-002",
        page_count=1, status="completed", completed_slides_json="[]",
    ))
    db_session.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    owner = db_session.query(User).filter(User.id == 1).one()

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: owner
    with TestClient(app) as client:
        response = client.get("/api/v1/ppt-master/projects/pptproj_private_002/history")

    assert response.status_code == 404


def test_history_project_migrates_preview_asset_to_persistent_storage(db_session, tmp_path):
    from app.PPT_master.editor_documents import EditorProjectStore

    stable_root = tmp_path / "ppt-history-assets"
    history = EditorProjectStore(history_root=stable_root).history(
        db_session, project_id="pptproj_editor_001", user_id=1,
    )
    asset = db_session.query(File).filter(File.id == 11).one()

    assert history["project"]["presentation"]["slides"][0]["previewArtifactId"] == 11
    assert asset.real_path == str(stable_root / "pptproj_editor_001" / "11-slide-1.svg")
    assert (stable_root / "pptproj_editor_001" / "11-slide-1.svg").read_text(encoding="utf-8").startswith("<svg")
