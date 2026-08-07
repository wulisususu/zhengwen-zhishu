"""Test workspace API routes."""
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
def api_setup():
    """Set up test API with in-memory database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    
    # Manually create ppt_structured_workspaces table (skip full migrations)
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
    
    # Create test users
    user1 = User(id=1, username="123", password_hash="hash123")
    user2 = User(id=2, username="testuser2", password_hash="hash456")
    db.add_all([user1, user2])
    db.commit()
    db.refresh(user1)
    db.refresh(user2)
    
    # Create builtin workspace
    service = WorkspaceService()
    service.create_builtin_workspace(db, user1.id, "ppt169")
    db.commit()
    
    # Create FastAPI app
    from app.PPT_master.router import router as ppt_router
    app = FastAPI()
    app.include_router(ppt_router, prefix="/api/v1/ppt-master")
    
    def override_db():
        try:
            yield db
        finally:
            pass
    
    def override_user1():
        return user1
    
    def override_user2():
        return user2
    
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user1
    
    yield app, db, user1, user2
    
    db.close()
    engine.dispose()


@pytest.fixture
def client(api_setup):
    """Test client fixture."""
    app, db, user1, user2 = api_setup
    return TestClient(app)


@pytest.fixture
def auth_token():
    """Mock auth token for user 123."""
    return "mock_token_123"


def test_list_workspaces_requires_auth(client):
    """List workspaces requires authentication."""
    # Override to no user
    from app.deps import get_current_user
    from fastapi import HTTPException
    
    def no_user():
        raise HTTPException(401)
    
    client.app.dependency_overrides[get_current_user] = no_user
    response = client.get("/api/v1/ppt-master/workspaces")
    assert response.status_code == 401


def test_list_workspaces_returns_builtins(client, auth_token):
    """Authenticated user can list workspaces including builtins."""
    response = client.get(
        "/api/v1/ppt-master/workspaces",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
    workspaces = data["data"]
    assert isinstance(workspaces, list)
    assert len(workspaces) >= 1
    assert any(w["source_type"] == "builtin" for w in workspaces)


def test_get_workspace_detail(client, auth_token):
    """Get workspace detail by ID."""
    # First list to get an ID
    list_resp = client.get(
        "/api/v1/ppt-master/workspaces",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    workspaces = list_resp.json()["data"]
    workspace_id = workspaces[0]["workspace_id"]
    
    # Get detail
    response = client.get(
        f"/api/v1/ppt-master/workspaces/{workspace_id}",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["workspace_id"] == workspace_id
    assert "master_manifest" in data
    assert "layout_manifest" in data


def test_create_user_workspace(client, auth_token):
    """User can create their own workspace."""
    response = client.post(
        "/api/v1/ppt-master/workspaces",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={
            "name": "My Custom Workspace",
            "canvas": "ppt169",
            "master_manifest": [{"master_id": "m1", "name": "Master 1"}],
            "layout_manifest": [{"layout_id": "l1", "master_id": "m1", "kind": "title"}]
        }
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "My Custom Workspace"
    assert data["source_type"] == "user_created"
    assert "workspace_id" in data


def test_update_workspace_requires_ownership(client, auth_token):
    """User can only update their own workspaces."""
    list_resp = client.get("/api/v1/ppt-master/workspaces", headers={"Authorization": f"Bearer {auth_token}"})
    builtin_id = next(w["workspace_id"] for w in list_resp.json()["data"] if w["source_type"] == "builtin")
    
    response = client.patch(
        f"/api/v1/ppt-master/workspaces/{builtin_id}",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"name": "Hacked Builtin"}
    )
    assert response.status_code == 403


def test_update_workspace_with_revision_check(client, auth_token):
    """Workspace update requires matching revision."""
    create_resp = client.post(
        "/api/v1/ppt-master/workspaces",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={
            "name": "Test Workspace",
            "canvas": "ppt169",
            "master_manifest": [{"master_id": "m1"}],
            "layout_manifest": [{"layout_id": "l1", "master_id": "m1", "kind": "title"}]
        }
    )
    workspace_id = create_resp.json()["data"]["workspace_id"]
    
    response = client.patch(
        f"/api/v1/ppt-master/workspaces/{workspace_id}",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"name": "Updated", "expected_revision": 99}
    )
    assert response.status_code == 409


def test_validate_workspace_endpoint(client, auth_token):
    """Validate endpoint checks manifest consistency."""
    create_resp = client.post(
        "/api/v1/ppt-master/workspaces",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={
            "name": "Valid Workspace",
            "canvas": "ppt169",
            "master_manifest": [{"master_id": "m1", "name": "M1"}],
            "layout_manifest": [{"layout_id": "l1", "master_id": "m1", "kind": "title"}],
            "placeholder_manifest": [{"ph_id": "p1", "layout_id": "l1", "type": "title", "idx": 0}]
        }
    )
    workspace_id = create_resp.json()["data"]["workspace_id"]
    
    response = client.post(
        f"/api/v1/ppt-master/workspaces/{workspace_id}/validate",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["valid"] is True
