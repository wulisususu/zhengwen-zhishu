"""Pydantic schemas for the Guided Strategist (P3-B) API.

These are the boundary/validation models used by ``guided_router.py``.
All error responses across the guided API use :class:`ErrorResponse`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Error contract
# --------------------------------------------------------------------------- #
class ErrorResponse(BaseModel):
    """Structured error body returned for every non-2xx guided response."""

    error_code: str = Field(..., description="Stable machine code, e.g. revision_conflict")
    message: str = Field(..., description="Human-readable summary")
    detail: Optional[Any] = Field(None, description="Optional structured context")


# --------------------------------------------------------------------------- #
# Create / list
# --------------------------------------------------------------------------- #
class GuidedProjectCreate(BaseModel):
    title: Optional[str] = Field(None, description="Optional display title")
    prompt: Optional[str] = Field(None, description="Free-text user prompt for stage 1 seed")
    source_refs: Optional[Any] = Field(None, description="Optional source references payload")


class GuidedProjectListItem(BaseModel):
    guided_project_id: str
    title: Optional[str] = None
    current_stage: str
    status: str
    revision: int
    updated_at: Optional[datetime] = None


class GuidedProjectListOut(BaseModel):
    items: List[GuidedProjectListItem]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- #
# Full restorable state (GET /{id})
# --------------------------------------------------------------------------- #
class GuidedProjectOut(BaseModel):
    guided_project_id: str
    owner_user_id: int
    project_id: Optional[str] = None
    title: Optional[str] = None
    mode: str
    current_stage: str
    status: str
    revision: int
    # stage payloads (full restorable state)
    stage1_json: Optional[Dict[str, Any]] = None
    stage2_json: Optional[Dict[str, Any]] = None
    stage3_json: Optional[Dict[str, Any]] = None
    recommendations_json: Optional[Dict[str, Any]] = None
    result_json: Optional[Dict[str, Any]] = None
    confirmed_values_json: Optional[Dict[str, Any]] = None
    source_refs_json: Optional[Any] = None
    generation_task_id: Optional[str] = None
    error_json: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# --------------------------------------------------------------------------- #
# Stage read (GET /{id}/stage)
# --------------------------------------------------------------------------- #
class StageOut(BaseModel):
    guided_project_id: str
    current_stage: str
    status: str
    revision: int
    stage_data: Optional[Dict[str, Any]] = None
    allowed_next_actions: List[str] = Field(default_factory=list)
    chosen_direction: Optional[Dict[str, Any]] = None


# --------------------------------------------------------------------------- #
# Mutations
# --------------------------------------------------------------------------- #
class StagePatch(BaseModel):
    expected_revision: int = Field(..., description="Optimistic-lock revision")
    stage_data: Dict[str, Any] = Field(..., description="Full stage JSON for the current draft stage")


class ConfirmRequest(BaseModel):
    expected_revision: int = Field(..., description="Optimistic-lock revision")
    stage: Optional[Any] = Field(
        None,
        description=(
            "Confirmed stage values. May be the full stage data DICT (server contract), "
            "a stage-name MARKER STRING when the data was PATCHed separately, or omitted. "
            "The service keeps already-stored data when only a marker is supplied."
        ),
    )
    action: Optional[str] = Field(
        None, description="Optional transition action, e.g. revise_stage1 / revise_stage2"
    )
    direction_id: Optional[str] = Field(
        None,
        description="Chosen direction id for stage2 (top-level field; mirrors a stage dict's direction_id)",
    )


class GenerateRequest(BaseModel):
    expected_revision: Optional[int] = Field(
        None, description="Optional optimistic-lock revision (ignored when already generating/completed)"
    )


class RetryRequest(BaseModel):
    """Empty body for retry; retained for explicit contract parity."""


# --------------------------------------------------------------------------- #
# Simple success / mutation echoes
# --------------------------------------------------------------------------- #
class MutationOut(BaseModel):
    guided_project_id: str
    current_stage: str
    status: str
    revision: int


class GenerateOut(BaseModel):
    guided_project_id: str
    status: str
    generation_task_id: str
