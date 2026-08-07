"""P4 Object Animation ORM models — animation manifest persistence.

Design: Animation config stored in ppt_editor_documents via animation_config
column (JSON text), plus a dedicated ppt_animation_manifests table as
audit artifact (write-through from editor saves for OOXML traceability).

Tables:
- ppt_animation_manifests: project-level animation manifest snapshot
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from app.database import Base


class PPTAnimationManifest(Base):
    """Per-project animation manifest — atomic audit artifact.

    Written on every editor save that includes animation changes.
    animation_revision increments independently from document revision.
    """

    __tablename__ = "ppt_animation_manifests"
    __table_args__ = (
        UniqueConstraint("project_id", "animation_revision", name="uq_ppt_anim_manifest_rev"),
    )

    manifest_id = Column(String(64), primary_key=True)
    project_id = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    document_revision = Column(Integer, nullable=False)  # editor document revision at write time
    animation_revision = Column(Integer, nullable=False, default=1)
    animations_json = Column(Text, nullable=False, default="{}")  # the full animations.json
    sha256 = Column(String(64), nullable=True)  # hash of animations_json for integrity
    created_at = Column(DateTime, default=datetime.utcnow)
