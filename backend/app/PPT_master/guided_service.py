"""Guided Strategist (P3-B) business logic.

Service layer — never imports HTTP request/response types (see fullstack-dev
skill: services stay framework-agnostic). All orchestration, ownership,
revision-lock, feature-flag and stage-gate rules live here.

Dependencies on sibling sub-agents:
  * Sub1 owns ``guided_models.GuidedProject`` and ``guided_state_machine``
    helpers. We import them eagerly; if they are absent (e.g. isolated test
    run before the worktree is merged) we fall back to a minimal, contract-
    faithful implementation so the module stays importable and testable.
  * Sub3 owns ``guided_strategist_adapter`` and ``guided_generation_adapter``.
    Those are imported *lazily* inside the call sites so tests can monkeypatch
    ``_lazy_generate_stage2_recommendations`` / ``_lazy_run_guided_generation``
    without the real chain present.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Session

# --------------------------------------------------------------------------- #
# Sub1 integration (model + state machine) with offline fallback
# --------------------------------------------------------------------------- #
# We import Sub1's real modules eagerly. If they are absent (isolated test run
# before the worktree is merged), we fall back to contract-faithful local
# definitions that mirror Sub1's public signatures EXACTLY so the module stays
# importable and behaves identically.
try:  # pragma: no cover - exercised when sub1 modules are present
    from .guided_models import GuidedProject  # type: ignore
    from .guided_state_machine import (  # type: ignore
        RevisionConflict,
        can_patch_stage,
        check_revision,
        revise_invalidates_downstream,
    )
    _HAVE_SUB1 = True
except Exception:  # pragma: no cover - offline fallback only
    _HAVE_SUB1 = False

    class _Base(DeclarativeBase):
        pass

    class GuidedProject(_Base):  # type: ignore
        """Fallback GuidedProject model mirroring Sub1's guided_models.py."""

        __tablename__ = "guided_projects"

        guided_project_id = __import__("sqlalchemy").Column(
            String(36), primary_key=True, default=lambda: str(uuid.uuid4())
        )
        owner_user_id = __import__("sqlalchemy").Column(Integer, index=True)
        project_id = __import__("sqlalchemy").Column(String(36), nullable=True)
        title = __import__("sqlalchemy").Column(String(512), nullable=True)
        mode = __import__("sqlalchemy").Column(String(32), nullable=False, default="guided")
        current_stage = __import__("sqlalchemy").Column(String(48), nullable=False)
        status = __import__("sqlalchemy").Column(String(32), nullable=False, default="draft")
        revision = __import__("sqlalchemy").Column(
            Integer, nullable=False, default=1
        )
        stage1_json = __import__("sqlalchemy").Column(JSON, nullable=True)
        stage2_json = __import__("sqlalchemy").Column(JSON, nullable=True)
        stage3_json = __import__("sqlalchemy").Column(JSON, nullable=True)
        recommendations_json = __import__("sqlalchemy").Column(JSON, nullable=True)
        result_json = __import__("sqlalchemy").Column(JSON, nullable=True)
        confirmed_values_json = __import__("sqlalchemy").Column(JSON, nullable=True)
        source_refs_json = __import__("sqlalchemy").Column(JSON, nullable=True)
        generation_task_id = __import__("sqlalchemy").Column(String(255), nullable=True)
        error_json = __import__("sqlalchemy").Column(JSON, nullable=True)
        created_at = __import__("sqlalchemy").Column(
            DateTime, default=lambda: datetime.now(timezone.utc)
        )
        updated_at = __import__("sqlalchemy").Column(
            DateTime,
            default=lambda: datetime.now(timezone.utc),
            onupdate=lambda: datetime.now(timezone.utc),
        )
        confirmed_at = __import__("sqlalchemy").Column(DateTime, nullable=True)
        completed_at = __import__("sqlalchemy").Column(DateTime, nullable=True)

    class RevisionConflict(Exception):  # type: ignore
        error_code = "revision_conflict"

        def __init__(self, expected: Any, actual: Any):
            self.expected = expected
            self.actual = actual
            super().__init__(f"Revision conflict: expected {expected}, actual {actual}")

    def check_revision(expected: int, actual: int) -> None:  # type: ignore
        if int(expected) != int(actual):
            raise RevisionConflict(expected, actual)

    def can_patch_stage(current_stage: str, stage_name: str) -> bool:  # type: ignore
        return current_stage == f"{stage_name}_draft"

    def revise_invalidates_downstream(stage: str):  # type: ignore
        normalised = stage.replace("_confirmed", "").replace("_draft", "")
        if normalised == "stage1":
            return ["stage2_json", "stage3_json", "recommendations_json",
                    "result_json", "confirmed_values_json"]
        if normalised == "stage2":
            return ["stage3_json", "result_json", "confirmed_values_json"]
        if normalised == "stage3":
            return ["result_json", "confirmed_values_json"]
        raise ValueError(f"Unknown stage for revise: {stage}")


try:  # pragma: no cover - sub1 migration module present in merged worktree
    from .guided_migration import ensure_guided_tables  # type: ignore
except Exception:  # pragma: no cover - offline fallback
    def ensure_guided_tables(engine: Any) -> None:  # type: ignore
        GuidedProject.__table__.create(engine, checkfirst=True)


# --------------------------------------------------------------------------- #
# Domain errors (no HTTP types — translated by the router)
# --------------------------------------------------------------------------- #
class FeatureDenied(Exception):
    error_code = "feature_denied"
    status_code = 403

    def __init__(self, message: str = "Guided Strategist is not enabled for this account"):
        self.message = message
        super().__init__(message)


class NotFound(Exception):
    error_code = "not_found"
    status_code = 404

    def __init__(self, message: str = "Guided project not found"):
        self.message = message
        super().__init__(message)


class StageGateInvalid(Exception):
    error_code = "stage_gate_invalid"
    status_code = 400

    def __init__(self, message: str = "Stage transition not allowed"):
        self.message = message
        super().__init__(message)


class GenerationFailed(Exception):
    error_code = "generation_failed"
    status_code = 500

    def __init__(self, message: str = "Generation failed"):
        self.message = message
        super().__init__(message)


# --------------------------------------------------------------------------- #
# Feature flag
# --------------------------------------------------------------------------- #
def _allowed_user_ids() -> List[str]:
    raw = os.environ.get("PPT_GUIDED_STRATEGIST_ALLOWED_USERS", "123")
    return [u.strip() for u in raw.split(",") if u.strip()]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_owned(db: Session, user: Any, project_id: str) -> GuidedProject:
    gp = (
        db.query(GuidedProject)
        .filter(
            GuidedProject.guided_project_id == str(project_id),
            GuidedProject.owner_user_id == int(user.id),
        )
        .first()
    )
    if gp is None:
        # Do not leak existence to other users -> 404 (per spec §6)
        raise NotFound()
    return gp


def _stage_json_field(current_stage: str) -> Optional[str]:
    if current_stage == "stage1_draft":
        return "stage1_json"
    if current_stage == "stage2_draft":
        return "stage2_json"
    if current_stage == "stage3_draft":
        return "stage3_json"
    return None


def _val(payload: Optional[Dict[str, Any]], key: str, default: Any = None) -> Any:
    """Extract a value from a stage payload that may use {value, ...} wrappers."""
    if not payload:
        return default
    node = payload.get(key)
    if isinstance(node, dict) and "value" in node:
        return node.get("value", default)
    return node if node is not None else default


def _auto_create_project_id(gp: GuidedProject) -> str:
    """Bind an (auto-created) PPT project id. Real project creation is Sub3's job;
    we persist a stable UUID placeholder the generation chain can resolve."""
    if gp.project_id:
        return str(gp.project_id)
    gp.project_id = str(uuid.uuid4())
    return gp.project_id


def _extract_directions(payload: Any) -> List[Dict[str, Any]]:
    """Normalise Sub3's recommendations into a list of direction dicts.

    Sub3 returns ``{"directions": {safe: {...}, shifted: {...}, bold: {...}}, ...}``
    (dict keyed by direction id) but tests/older shapes may use a plain list.
    """
    if not isinstance(payload, dict):
        return list(payload) if isinstance(payload, (list, tuple)) else []
    d = payload.get("directions")
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return list(d.values())
    # payload itself may already be the directions map
    if set(payload.keys()) & {"safe", "shifted", "bold"}:
        return list(payload.values())
    return []


def _build_result(gp: GuidedProject) -> Dict[str, Any]:
    s1 = gp.stage1_json or {}
    s2 = gp.stage2_json or {}
    s3 = gp.stage3_json or {}
    recs = s2.get("directions") or gp.recommendations_json or {}
    dir_list = _extract_directions(recs)
    chosen_id = s2.get("chosen_direction_id")
    chosen = next(
        (d for d in dir_list if isinstance(d, dict) and d.get("direction_id") == chosen_id),
        None,
    )
    return {
        "audience": _val(s1, "audience"),
        "communication_intent": _val(s1, "communication_intent"),
        "core_message": _val(s1, "core_message"),
        "delivery_context": _val(s1, "delivery_context"),
        "requested_page_count": _val(s1, "requested_page_count"),
        "chosen_direction_id": chosen_id,
        "visual_style": chosen.get("visual_style") if chosen else None,
        "presentation_mode": chosen.get("presentation_mode") if chosen else None,
        "reading_mode": chosen.get("reading_mode") if chosen else None,
        "palette": chosen.get("palette") if chosen else None,
        "typography": {
            "title_family": chosen.get("title_family") if chosen else None,
            "body_family": chosen.get("body_family") if chosen else None,
            "typography_sizes": chosen.get("typography_sizes") if chosen else None,
        },
        "image_strategy": chosen.get("image_strategy") if chosen else None,
        "chart_strategy": chosen.get("chart_strategy") if chosen else None,
        "table_strategy": chosen.get("table_strategy") if chosen else None,
        "page_rhythm": chosen.get("page_rhythm") if chosen else None,
        "pptx_structure_mode": _val(s3, "pptx_structure_mode", chosen.get("pptx_structure_mode") if chosen else None),
        "structured_workspace_id": _val(s3, "structured_workspace_id", chosen.get("structured_workspace_id") if chosen else None),
        "structured_workspace_revision": _val(s3, "structured_workspace_revision"),
        "page_count": _val(s3, "page_count", _val(s1, "requested_page_count")),
        "animation_policy": _val(s3, "animation_policy", "none"),
        "native_chart_policy": _val(s3, "native_chart_policy"),
        "native_table_policy": _val(s3, "native_table_policy"),
        "source_handling_summary": _val(s3, "source_handling_summary"),
    }


def _build_confirmed_values(gp: GuidedProject) -> Dict[str, Any]:
    return {
        "stage1": gp.stage1_json,
        "stage2_chosen": gp.stage2_json,
        "stage3": gp.stage3_json,
        "result": _build_result(gp),
    }


# --------------------------------------------------------------------------- #
# Lazy Sub3 adapters (monkeypatchable in tests)
# --------------------------------------------------------------------------- #
def _lazy_generate_stage2_recommendations(stage1: Dict[str, Any]) -> Dict[str, Any]:
    """Lazily import Sub3's strategist. Raises ImportError if Sub3 absent."""
    from .guided_strategist_adapter import generate_stage2_recommendations  # type: ignore

    return generate_stage2_recommendations(stage1)


def _lazy_run_guided_generation(gp: GuidedProject, project_id: str) -> str:
    """Lazily import Sub3's generation chain. Returns a task id (str)."""
    from .guided_generation_adapter import run_guided_generation  # type: ignore

    return run_guided_generation(gp, project_id)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def create_guided_project(
    db: Session,
    user: Any,
    title: Optional[str] = None,
    prompt: Optional[str] = None,
    source_refs: Any = None,
) -> GuidedProject:
    if str(user.id) not in _allowed_user_ids():
        raise FeatureDenied()

    seed_stage1 = None
    if prompt:
        seed_stage1 = {"core_message": {"value": prompt, "source": "user", "user_modified": True}}

    gp = GuidedProject(
        owner_user_id=int(user.id),
        mode="guided",
        current_stage="stage1_draft",
        status="draft",
        revision=1,
        title=title,
        source_refs_json=source_refs,
        stage1_json=seed_stage1,
    )
    db.add(gp)
    db.commit()
    db.refresh(gp)
    return gp


def list_guided_projects(
    db: Session, user: Any, page: int = 1, page_size: int = 20
) -> Dict[str, Any]:
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    q = db.query(GuidedProject).filter(GuidedProject.owner_user_id == int(user.id))
    total = q.count()
    rows = (
        q.order_by(GuidedProject.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "guided_project_id": str(r.guided_project_id),
            "title": r.title,
            "current_stage": r.current_stage,
            "status": r.status,
            "revision": r.revision,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_guided_project(db: Session, user: Any, project_id: str) -> GuidedProject:
    return _get_owned(db, user, project_id)


def patch_stage(
    db: Session,
    user: Any,
    project_id: str,
    expected_revision: int,
    stage_data: Dict[str, Any],
) -> GuidedProject:
    gp = _get_owned(db, user, project_id)
    check_revision(expected_revision, gp.revision)

    stage_name = gp.current_stage[:-len("_draft")] if gp.current_stage.endswith("_draft") else None
    if not stage_name or not can_patch_stage(gp.current_stage, stage_name):
        raise StageGateInvalid(
            f"Stage '{gp.current_stage}' is not patchable; only the current draft stage can be edited"
        )

    field = _stage_json_field(gp.current_stage)
    setattr(gp, field, stage_data)
    gp.revision += 1
    gp.updated_at = _now()
    db.commit()
    db.refresh(gp)
    return gp


def _apply_revise(gp: GuidedProject, from_stage: int) -> None:
    for field in revise_invalidates_downstream(f"stage{from_stage}"):
        setattr(gp, field, None)
    gp.current_stage = "stage1_draft" if from_stage == 1 else "stage2_draft"
    gp.status = "draft"
    gp.revision += 1
    gp.updated_at = _now()


def confirm_stage(
    db: Session,
    user: Any,
    project_id: str,
    expected_revision: int,
    stage: Optional[Any] = None,
    action: Optional[str] = None,
    direction_id: Optional[str] = None,
) -> GuidedProject:
    gp = _get_owned(db, user, project_id)
    check_revision(expected_revision, gp.revision)

    # Explicit revise actions invalidate downstream confirmations.
    if action == "revise_stage1":
        _apply_revise(gp, 1)
        db.commit()
        db.refresh(gp)
        return gp
    if action == "revise_stage2":
        _apply_revise(gp, 2)
        db.commit()
        db.refresh(gp)
        return gp

    if gp.current_stage == "stage1_draft":
        # `stage` may be the full stage-1 data dict (server contract), a stage-name
        # marker string (client PATCHed the data separately via PATCH /stage), or
        # None. Only overwrite when a real dict is supplied; otherwise keep the
        # already-PATCHed value so confirm() never clobbers user edits.
        if isinstance(stage, dict):
            gp.stage1_json = stage
        recommendations = _lazy_generate_stage2_recommendations(gp.stage1_json or {})
        gp.recommendations_json = recommendations
        gp.stage2_json = recommendations
        gp.current_stage = "stage2_draft"

    elif gp.current_stage == "stage2_draft":
        # Chosen direction comes from the top-level direction_id field (what the
        # client actually sends) or, for backward compatibility, from a stage dict.
        # Never call .get() on a string marker — that crashed with AttributeError.
        chosen_id = direction_id
        if chosen_id is None and isinstance(stage, dict):
            chosen_id = stage.get("direction_id")
        gp.stage2_json = {
            "chosen_direction_id": chosen_id,
            "directions": gp.recommendations_json,
        }
        gp.current_stage = "stage3_draft"

    elif gp.current_stage == "stage3_draft":
        # Keep the edited stage-3 data only when a real dict is supplied.
        if isinstance(stage, dict):
            gp.stage3_json = stage
        gp.result_json = _build_result(gp)
        gp.confirmed_values_json = _build_confirmed_values(gp)
        gp.status = "confirmed"
        gp.current_stage = "confirmed"
        gp.confirmed_at = _now()

    else:
        raise StageGateInvalid(
            f"Cannot confirm from current stage '{gp.current_stage}'"
        )

    gp.revision += 1
    gp.updated_at = _now()
    db.commit()
    db.refresh(gp)
    return gp


def generate(
    db: Session,
    user: Any,
    project_id: str,
    expected_revision: Optional[int] = None,
) -> GuidedProject:
    gp = _get_owned(db, user, project_id)
    if expected_revision is not None:
        check_revision(expected_revision, gp.revision)

    # Idempotency: same revision already generating/completed -> existing task.
    if gp.status in ("generating", "completed") and gp.generation_task_id:
        return gp

    if gp.status != "confirmed":
        raise StageGateInvalid("Generation requires status 'confirmed'")

    # Lock the confirmed result + revision, bind/auto-create project id, and
    # allocate the generation task id. The actual chain execution is launched as
    # a background task by the router (see guided_router._run_guided_background),
    # so this call returns immediately with generation_task_id for polling.
    project_id_bound = _auto_create_project_id(gp)
    gp.generation_task_id = "pptguided_" + uuid.uuid4().hex
    gp.status = "generating"
    gp.revision += 1
    gp.updated_at = _now()
    db.commit()
    db.refresh(gp)
    return gp


def retry(db: Session, user: Any, project_id: str) -> GuidedProject:
    gp = _get_owned(db, user, project_id)
    if gp.status != "failed":
        raise StageGateInvalid("Retry requires status 'failed'")

    gp.error_json = None
    gp.generation_task_id = "pptguided_" + uuid.uuid4().hex
    gp.status = "generating"
    gp.revision += 1
    gp.updated_at = _now()
    db.commit()
    db.refresh(gp)
    return gp
