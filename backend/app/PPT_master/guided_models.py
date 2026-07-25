"""P3-B Guided Strategist — GuidedProject ORM model.

OWNER: Sub1 (do not edit from other sub-agents).

Design notes
------------
* Imports ONLY ``Base`` from ``app.database`` plus standard SQLAlchemy
  utilities. No business logic, no HTTP types, no engine import — this keeps
  the module importable from unit tests and from ``guided_migration`` without a
  circular import.
* ``Base`` is shared with the rest of the repo (the server's ``app.database``
  defines it). A fallback ``declarative_base()`` is used only when
  ``app.database`` is unavailable (standalone test execution), so the metadata
  stays consistent within a single process.
* All timestamps are UTC. ``server_default=func.now()`` covers DB-side writes;
  a Python-side ``_utcnow`` default covers in-process object creation before a
  flush.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, DateTime, JSON, func, Index

try:  # Server layout: shared Base lives in app.database.
    from app.database import Base
except Exception:  # pragma: no cover - fallback for isolated unit tests.
    from sqlalchemy.orm import declarative_base

    Base = declarative_base()


def _utcnow() -> datetime:
    """UTC-aware timestamp used for client-side column defaults."""
    return datetime.now(timezone.utc)


class GuidedProject(Base):
    """A single guided-strategist project belonging to one user."""

    __tablename__ = "guided_projects"

    # --- Identity / ownership ---
    guided_project_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id = Column(Integer, nullable=False, index=True)
    project_id = Column(String(36), nullable=True)  # bound PPT project after generation

    # --- Lifecycle ---
    title = Column(String(512), nullable=True)
    mode = Column(String(32), nullable=False, default="guided")
    current_stage = Column(String(32), nullable=False, default="stage1_draft")
    status = Column(String(32), nullable=False, default="draft")
    revision = Column(Integer, nullable=False, default=1)

    # --- Stage payloads (JSON) ---
    stage1_json = Column(JSON, nullable=True)
    stage2_json = Column(JSON, nullable=True)
    stage3_json = Column(JSON, nullable=True)
    recommendations_json = Column(JSON, nullable=True)
    result_json = Column(JSON, nullable=True)
    confirmed_values_json = Column(JSON, nullable=True)
    source_refs_json = Column(JSON, nullable=True)
    generation_task_id = Column(String(255), nullable=True)
    error_json = Column(JSON, nullable=True)

    # --- Timestamps (UTC) ---
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), default=_utcnow,
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), default=_utcnow, onupdate=_utcnow,
    )
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_guided_projects_owner_status", "owner_user_id", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<GuidedProject {self.guided_project_id} "
            f"owner={self.owner_user_id} stage={self.current_stage} "
            f"status={self.status} rev={self.revision}>"
        )
