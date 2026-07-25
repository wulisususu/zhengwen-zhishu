"""Workspace service for structured PPT generation."""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import PPTStructuredWorkspace


class WorkspaceNotFoundError(LookupError):
    """Workspace not found."""
    pass


class WorkspaceService:
    """Service for managing structured workspaces."""
    
    def get_workspace(self, db: Session, workspace_id: str) -> dict[str, Any] | None:
        """Get workspace by ID.
        
        Returns None if not found, otherwise dict with:
        - workspace_id, owner_user_id, name, source_type, status, version, canvas
        - master_manifest, layout_manifest, placeholder_manifest (parsed JSON)
        """
        workspace = db.query(PPTStructuredWorkspace).filter_by(workspace_id=workspace_id).first()
        if not workspace:
            return None
        
        return {
            "workspace_id": workspace.workspace_id,
            "owner_user_id": workspace.owner_user_id,
            "name": workspace.name,
            "source_type": workspace.source_type,
            "status": workspace.status,
            "version": workspace.version,
            "canvas": workspace.canvas,
            "master_manifest": json.loads(workspace.master_manifest_json),
            "layout_manifest": json.loads(workspace.layout_manifest_json),
            "placeholder_manifest": json.loads(workspace.placeholder_manifest_json),
        }
    
    def create_builtin_workspace(self, db: Session, owner_user_id: int, canvas: str) -> str:
        """Create a builtin workspace for given canvas.
        
        Returns workspace_id of created workspace.
        """
        from app.PPT_master.workspace_fixtures import get_builtin_workspace_definition
        
        definition = get_builtin_workspace_definition(canvas)
        workspace_id = f"ws_builtin_{canvas}_{uuid.uuid4().hex[:8]}"
        
        workspace = PPTStructuredWorkspace(
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            name=definition["name"],
            source_type="builtin",
            status="active",
            canvas=canvas,
            theme_json=json.dumps(definition.get("theme", {})),
            master_manifest_json=json.dumps(definition["masters"]),
            layout_manifest_json=json.dumps(definition["layouts"]),
            placeholder_manifest_json=json.dumps(definition["placeholders"]),
        )
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
        return workspace_id
    
    def list_user_workspaces(self, db: Session, user_id: int) -> list[dict[str, Any]]:
        """List workspaces available to user (owned + builtin)."""
        workspaces = db.query(PPTStructuredWorkspace).filter(
            (PPTStructuredWorkspace.owner_user_id == user_id) |
            (PPTStructuredWorkspace.source_type == "builtin")
        ).all()
        
        return [{
            "workspace_id": w.workspace_id,
            "name": w.name,
            "source_type": w.source_type,
            "status": w.status,
            "canvas": w.canvas
        } for w in workspaces]
    
    def create_user_workspace(
        self,
        db: Session,
        owner_user_id: int,
        name: str,
        canvas: str,
        master_manifest: list[dict],
        layout_manifest: list[dict],
        placeholder_manifest: list[dict] | None = None
    ) -> str:
        """Create a user-owned workspace.
        
        Returns workspace_id of created workspace.
        """
        workspace_id = f"ws_user_{uuid.uuid4().hex}"
        
        workspace = PPTStructuredWorkspace(
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            name=name,
            source_type="user_created",
            status="draft",
            canvas=canvas,
            theme_json=json.dumps({}),
            master_manifest_json=json.dumps(master_manifest),
            layout_manifest_json=json.dumps(layout_manifest),
            placeholder_manifest_json=json.dumps(placeholder_manifest or []),
        )
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
        return workspace_id
    
    def update_workspace(
        self,
        db: Session,
        workspace_id: str,
        owner_user_id: int,
        expected_revision: int | None,
        updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Update a user workspace.
        
        Raises:
        - WorkspaceNotFoundError if not found
        - PermissionError if not owned by user
        - ValueError if revision mismatch or trying to update builtin
        """
        workspace = db.query(PPTStructuredWorkspace).filter_by(workspace_id=workspace_id).first()
        if not workspace:
            raise WorkspaceNotFoundError(workspace_id)
        
        if workspace.source_type == "builtin":
            raise PermissionError("Cannot modify builtin workspaces")
        
        if workspace.owner_user_id != owner_user_id:
            raise PermissionError("Workspace not owned by user")
        
        if expected_revision is not None and workspace.version != expected_revision:
            raise ValueError(f"Revision mismatch: expected {expected_revision}, got {workspace.version}")
        
        # Apply updates
        if "name" in updates:
            workspace.name = updates["name"]
        if "master_manifest" in updates:
            workspace.master_manifest_json = json.dumps(updates["master_manifest"])
        if "layout_manifest" in updates:
            workspace.layout_manifest_json = json.dumps(updates["layout_manifest"])
        if "placeholder_manifest" in updates:
            workspace.placeholder_manifest_json = json.dumps(updates["placeholder_manifest"])
        
        workspace.version += 1
        db.commit()
        db.refresh(workspace)
        
        return self.get_workspace(db, workspace_id)
    
    def validate_workspace(self, db: Session, workspace_id: str) -> dict[str, Any]:
        """Validate workspace manifest consistency.
        
        Returns validation result with:
        - valid: bool
        - errors: list[str]
        - warnings: list[str]
        """
        workspace = db.query(PPTStructuredWorkspace).filter_by(workspace_id=workspace_id).first()
        if not workspace:
            raise WorkspaceNotFoundError(workspace_id)
        
        errors = []
        warnings = []
        
        masters = json.loads(workspace.master_manifest_json)
        layouts = json.loads(workspace.layout_manifest_json)
        placeholders = json.loads(workspace.placeholder_manifest_json)
        
        # Check masters exist
        if not masters:
            errors.append("No masters defined")
        
        master_ids = {m.get("master_id") for m in masters}
        
        # Check layouts reference valid masters
        for layout in layouts:
            master_id = layout.get("master_id")
            if master_id not in master_ids:
                errors.append(f"Layout {layout.get('layout_id')} references unknown master {master_id}")
        
        layout_ids = {l.get("layout_id") for l in layouts}
        
        # Check placeholders reference valid layouts
        for ph in placeholders:
            layout_id = ph.get("layout_id")
            if layout_id not in layout_ids:
                errors.append(f"Placeholder {ph.get('ph_id')} references unknown layout {layout_id}")
        
        # Check required layout kinds present
        layout_kinds = {l.get("kind") for l in layouts}
        required = {"title", "title_content", "blank"}
        missing = required - layout_kinds
        if missing:
            warnings.append(f"Missing recommended layouts: {missing}")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
