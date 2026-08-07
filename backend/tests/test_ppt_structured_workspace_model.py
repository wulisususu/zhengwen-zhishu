"""Test PPTStructuredWorkspace model and migration."""
import pytest
from app.models import PPTStructuredWorkspace, User, Base
from app.database import SessionLocal, engine, _run_startup_migrations
from sqlalchemy import inspect


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """Initialize database with migrations."""
    # IMPORTANT: create_all BEFORE _run_startup_migrations
    Base.metadata.create_all(bind=engine)
    _run_startup_migrations()
    yield
    # Cleanup
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    """Provide a clean database session for each test."""
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


def test_ppt_structured_workspace_table_exists():
    """Verify ppt_structured_workspaces table exists."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "ppt_structured_workspaces" in tables


def test_create_builtin_workspace(db_session):
    """Test creating a builtin workspace."""
    user = User(username="test_ws_user", password_hash="hash123")
    db_session.add(user)
    db_session.commit()
    
    workspace = PPTStructuredWorkspace(
        workspace_id="ws_test_builtin",
        owner_user_id=user.id,
        name="Test Built-in Workspace",
        source_type="builtin",
        status="active",
        canvas="ppt169",
        master_manifest_json='[{"master_id":"m1","name":"Master 1"}]',
        layout_manifest_json='[{"layout_id":"l1","kind":"title"}]',
        placeholder_manifest_json="[]",
        asset_manifest_json="[]"
    )
    db_session.add(workspace)
    db_session.commit()
    
    retrieved = db_session.query(PPTStructuredWorkspace).filter_by(workspace_id="ws_test_builtin").first()
    assert retrieved is not None
    assert retrieved.name == "Test Built-in Workspace"
    assert retrieved.source_type == "builtin"
    assert retrieved.status == "active"
    assert retrieved.canvas == "ppt169"
