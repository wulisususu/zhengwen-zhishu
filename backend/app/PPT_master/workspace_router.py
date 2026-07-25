"""Authenticated endpoints for structured workspace management."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.PPT_master.workspace_service import WorkspaceNotFoundError
from app.deps import get_current_user
from app.errors import ok
from app.PPT_master.workspace_service import WorkspaceService

router = APIRouter(tags=["ppt-master-workspaces"])
_service = WorkspaceService()


def _require_feature(current_user) -> None:
    """Check if user has access to structured generation."""
    allowed = {item.strip() for item in os.environ.get("PPT_STRUCTURED_ALLOWED_USERS", "123").split(",") if item.strip()}
    if str(getattr(current_user, "username", "")) not in allowed:
        raise HTTPException(status_code=404, detail={"code": "ppt_feature_unavailable"})


@router.get("/workspaces")
def list_workspaces(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List available structured workspaces for current user.
    
    Returns both user-owned workspaces and builtin workspaces.
    """
    _require_feature(current_user)
    
    workspaces = _service.list_user_workspaces(db, current_user.id)
    return ok(workspaces)


@router.get("/workspaces/{workspace_id}")
def get_workspace(
    workspace_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get workspace details including master/layout/placeholder manifests."""
    _require_feature(current_user)
    
    workspace = _service.get_workspace(db, workspace_id)
    if not workspace:
        raise HTTPException(404, detail={"code": "workspace_not_found"})
    
    # Check ownership (builtin or owned by user)
    if workspace["source_type"] != "builtin" and workspace["owner_user_id"] != current_user.id:
        raise HTTPException(403, detail={"code": "access_denied"})
    
    return ok(workspace)


@router.post("/workspaces")
def create_workspace(
    payload: dict,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new user workspace."""
    _require_feature(current_user)
    
    workspace_id = _service.create_user_workspace(
        db,
        current_user.id,
        payload["name"],
        payload["canvas"],
        payload["master_manifest"],
        payload["layout_manifest"],
        payload.get("placeholder_manifest")
    )
    
    workspace = _service.get_workspace(db, workspace_id)
    return ok(workspace)


@router.patch("/workspaces/{workspace_id}")
def update_workspace(
    workspace_id: str,
    payload: dict,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing workspace."""
    _require_feature(current_user)
    
    try:
        workspace = _service.update_workspace(
            db,
            workspace_id,
            current_user.id,
            payload.get("expected_revision"),
            payload
        )
        return ok(workspace)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail={"code": "workspace_not_found"})
    except PermissionError as e:
        raise HTTPException(403, detail={"code": "permission_denied", "message": str(e)})
    except ValueError as e:
        raise HTTPException(409, detail={"code": "revision_conflict", "message": str(e)})


@router.post("/workspaces/{workspace_id}/validate")
def validate_workspace(
    workspace_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Validate workspace manifest consistency."""
    _require_feature(current_user)
    
    try:
        result = _service.validate_workspace(db, workspace_id)
        return ok(result)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail={"code": "workspace_not_found"})
