"""Test incremental generation with structured mode."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import User, Base
from app.database import get_db
from app.deps import get_current_user
from app.PPT_master.workspace_service import WorkspaceService


@pytest.fixture
def structured_api_setup():
    """Set up API with workspace data."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    
    # Create workspace table
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS ppt_structured_workspaces (
                workspace_id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'builtin',
                source_template_id TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                version INTEGER NOT NULL DEFAULT 1,
                canvas TEXT NOT NULL DEFAULT 'ppt169',
                theme_json TEXT NOT NULL DEFAULT '{}',
                master_manifest_json TEXT NOT NULL DEFAULT '[]',
                layout_manifest_json TEXT NOT NULL DEFAULT '[]',
                placeholder_manifest_json TEXT NOT NULL DEFAULT '[]',
                asset_manifest_json TEXT NOT NULL DEFAULT '[]',
                validation_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_user_id) REFERENCES users (id)
            )
        """)
    
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    user = User(id=1, username="123", password_hash="hash")
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Create builtin workspace
    service = WorkspaceService()
    workspace_id = service.create_builtin_workspace(db, user.id, "ppt169")
    db.commit()
    
    from app.PPT_master.router import router as ppt_router
    app = FastAPI()
    app.include_router(ppt_router, prefix="/api/v1")
    
    def override_db():
        try:
            yield db
        finally:
            pass
    
    def override_user():
        return user
    
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    
    yield app, db, user, workspace_id
    
    db.close()
    engine.dispose()


@pytest.fixture
def structured_client(structured_api_setup):
    app, db, user, workspace_id = structured_api_setup
    return TestClient(app), workspace_id


def test_incremental_request_defaults_to_flat(structured_client):
    """Incremental request without pptx_structure_mode defaults to flat."""
    client, workspace_id = structured_client
    
    response = client.post(
        "/api/v1/ppt-master/generate-incremental",
        json={
            "user_input": "Test presentation",
            "page_count": 4,
            "page_format": "ppt169",
            "sources": [],
            "request_id": "test_flat_default"
        }
    )
    # Should accept (generation will be mocked/async)
    assert response.status_code in (200, 202)


def test_incremental_structured_requires_workspace_id(structured_client):
    """Structured mode requires workspace_id."""
    client, workspace_id = structured_client
    
    response = client.post(
        "/api/v1/ppt-master/generate-incremental",
        json={
            "user_input": "Test structured",
            "page_count": 4,
            "page_format": "ppt169",
            "sources": [],
            "request_id": "test_structured_no_ws",
            "pptx_structure_mode": "structured"
        }
    )
    assert response.status_code == 422  # Pydantic validation error
    detail = response.json().get("detail", [])
    # Check validation error mentions workspace_id
    error_str = str(detail).lower()
    assert "workspace" in error_str


def test_incremental_structured_with_valid_workspace(structured_client):
    """Structured mode with valid workspace_id succeeds."""
    client, workspace_id = structured_client
    
    response = client.post(
        "/api/v1/ppt-master/generate-incremental",
        json={
            "user_input": "Test structured valid",
            "page_count": 4,
            "page_format": "ppt169",
            "sources": [],
            "request_id": "test_structured_valid",
            "pptx_structure_mode": "structured",
            "structured_workspace_id": workspace_id
        }
    )
    assert response.status_code in (200, 202)


def test_incremental_structured_rejects_invalid_workspace(structured_client):
    """Structured mode rejects nonexistent workspace_id."""
    client, workspace_id = structured_client
    
    response = client.post(
        "/api/v1/ppt-master/generate-incremental",
        json={
            "user_input": "Test invalid ws",
            "page_count": 4,
            "page_format": "ppt169",
            "sources": [],
            "request_id": "test_invalid_ws",
            "pptx_structure_mode": "structured",
            "structured_workspace_id": "ws_nonexistent_123"
        }
    )
    assert response.status_code == 400  # Endpoint validation error
    detail = response.json().get("detail", {})
    assert detail.get("code") == "invalid_workspace"
