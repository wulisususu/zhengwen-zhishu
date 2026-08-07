"""Test workspace service."""
import pytest
from app.PPT_master.workspace_service import WorkspaceService, WorkspaceNotFoundError
from app.models import User, Base
from app.database import SessionLocal, engine, _run_startup_migrations


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    _run_startup_migrations()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def test_user(db_session):
    user = db_session.query(User).filter_by(username="ws_test_user").first()
    if not user:
        user = User(username="ws_test_user", password_hash="hash123")
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    return user


def test_get_nonexistent_workspace_returns_none(db_session):
    """get_workspace returns None for nonexistent ID."""
    service = WorkspaceService()
    result = service.get_workspace(db_session, "ws_nonexistent")
    assert result is None


def test_create_builtin_workspace_ppt169(db_session, test_user):
    """create_builtin_workspace returns workspace_id."""
    service = WorkspaceService()
    workspace_id = service.create_builtin_workspace(db_session, test_user.id, "ppt169")
    
    assert workspace_id is not None
    assert workspace_id.startswith("ws_builtin_ppt169")
    
    # Verify created
    workspace = service.get_workspace(db_session, workspace_id)
    assert workspace is not None
    assert workspace["source_type"] == "builtin"
    assert workspace["canvas"] == "ppt169"
    assert workspace["status"] == "active"
    assert len(workspace["master_manifest"]) > 0
    assert len(workspace["layout_manifest"]) >= 5  # title, title_content, section, two_column, blank


def test_builtin_workspace_has_required_layouts(db_session, test_user):
    """Builtin workspace must have all 7 required layout kinds."""
    service = WorkspaceService()
    workspace_id = service.create_builtin_workspace(db_session, test_user.id, "ppt169")
    workspace = service.get_workspace(db_session, workspace_id)

    layout_kinds = {layout["kind"] for layout in workspace["layout_manifest"]}
    required_kinds = {"title", "title_content", "section", "two_column", "image_text", "data", "blank"}

    assert layout_kinds == required_kinds, f"Missing layouts: {required_kinds - layout_kinds}"


def test_builtin_workspace_image_text_layout(db_session, test_user):
    """image_text layout must exist with proper placeholders."""
    service = WorkspaceService()
    workspace_id = service.create_builtin_workspace(db_session, test_user.id, "ppt169")
    workspace = service.get_workspace(db_session, workspace_id)

    image_text_layout = next((l for l in workspace["layout_manifest"] if l["kind"] == "image_text"), None)
    assert image_text_layout is not None, "image_text layout not found"
    assert image_text_layout["layout_id"] == "layout_image_text"
    assert image_text_layout["master_id"] == "master_default"


def test_builtin_workspace_data_layout(db_session, test_user):
    """data layout must exist with proper placeholders."""
    service = WorkspaceService()
    workspace_id = service.create_builtin_workspace(db_session, test_user.id, "ppt169")
    workspace = service.get_workspace(db_session, workspace_id)

    data_layout = next((l for l in workspace["layout_manifest"] if l["kind"] == "data"), None)
    assert data_layout is not None, "data layout not found"
    assert data_layout["layout_id"] == "layout_data"
    assert data_layout["master_id"] == "master_default"
