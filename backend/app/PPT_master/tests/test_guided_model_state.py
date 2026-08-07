"""P3-B Guided Strategist — unit tests for model + state machine + migration.

OWNER: Sub1.

Runs WITHOUT the server: model/migration tests use an in-memory SQLite
database (sqlalchemy StaticPool) via tempfile-free ``:memory:``; the
state-machine tests need no database at all. ``GuidedProject`` falls back to a
local ``declarative_base`` when ``app.database`` is unavailable, so metadata
stays consistent within the test process.

Run:  python -m pytest app/PPT_master/tests/test_guided_model_state.py
"""
from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Make the backend package root importable (backend/ -> "app").
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from app.PPT_master.guided_state_machine import (  # noqa: E402
    ALLOWED_TRANSITIONS,
    RevisionConflict,
    apply_confirm,
    can_patch_stage,
    check_revision,
    is_terminal,
    revise_invalidates_downstream,
    validate_transition,
)
from app.PPT_master.guided_models import GuidedProject  # noqa: E402
from app.PPT_master.guided_migration import ensure_guided_tables  # noqa: E402


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def make_engine():
    """In-memory SQLite engine with a single shared connection (StaticPool)
    so the schema survives across Sessions and `ensure_guided_tables` twice."""
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


# --------------------------------------------------------------------------
# State-machine: transitions (valid + rejected)
# --------------------------------------------------------------------------
def test_validate_transition_valid():
    assert validate_transition("stage1_draft", "stage1_confirmed") is True
    assert validate_transition("stage1_confirmed", "stage2_draft") is True
    assert validate_transition("stage2_draft", "stage2_confirmed") is True
    assert validate_transition("stage2_confirmed", "stage3_draft") is True
    assert validate_transition("stage3_draft", "confirmed") is True
    assert validate_transition("confirmed", "generating") is True
    assert validate_transition("generating", "completed") is True
    assert validate_transition("generating", "failed") is True
    assert validate_transition("failed", "generating") is True


def test_validate_transition_rejected():
    # cannot skip ahead
    assert validate_transition("stage1_draft", "stage2_draft") is False
    assert validate_transition("stage1_confirmed", "stage3_draft") is False
    # terminal has no outgoing transition
    assert validate_transition("completed", "generating") is False
    # unknown stage
    assert validate_transition("nonsense", "stage1_draft") is False


def test_apply_confirm_linear():
    assert apply_confirm("stage1_draft") == "stage1_confirmed"
    assert apply_confirm("stage1_confirmed") == "stage2_draft"
    assert apply_confirm("stage2_draft") == "stage2_confirmed"
    assert apply_confirm("stage2_confirmed") == "stage3_draft"
    assert apply_confirm("stage3_draft") == "confirmed"
    assert apply_confirm("confirmed") == "generating"
    assert apply_confirm("generating") == "completed"
    assert apply_confirm("failed") == "generating"


def test_apply_confirm_terminal_raises():
    with pytest.raises(ValueError):
        apply_confirm("completed")


# --------------------------------------------------------------------------
# Optimistic lock: revision 409 logic
# --------------------------------------------------------------------------
def test_check_revision_match_no_raise():
    check_revision(3, 3)  # no exception


def test_check_revision_mismatch_raises_conflict():
    with pytest.raises(RevisionConflict) as exc:
        check_revision(2, 3)
    assert exc.value.status_code == 409
    assert exc.value.error_code == "revision_conflict"
    assert exc.value.expected == 2
    assert exc.value.actual == 3


# --------------------------------------------------------------------------
# Confirmed immutability rule
# --------------------------------------------------------------------------
def test_can_patch_stage_rules():
    # current draft stage is patchable
    assert can_patch_stage("stage1_draft", "stage1") is True
    assert can_patch_stage("stage2_draft", "stage2") is True
    # confirmed stage is immutable (cannot patch the same stage name)
    assert can_patch_stage("stage1_confirmed", "stage1") is False
    # not the current draft stage
    assert can_patch_stage("stage1_draft", "stage2") is False
    assert can_patch_stage("stage2_confirmed", "stage2") is False


# --------------------------------------------------------------------------
# Revise invalidation clears downstream
# --------------------------------------------------------------------------
def test_revise_invalidates_downstream():
    # revising the earliest stage wipes everything downstream
    assert revise_invalidates_downstream("stage1") == [
        "stage2_json",
        "stage3_json",
        "recommendations_json",
        "result_json",
        "confirmed_values_json",
    ]
    # revising stage2 wipes stage3 + result + confirmed_values
    assert revise_invalidates_downstream("stage2") == [
        "stage3_json",
        "result_json",
        "confirmed_values_json",
    ]
    # revising stage3 wipes result + confirmed_values
    assert revise_invalidates_downstream("stage3") == [
        "result_json",
        "confirmed_values_json",
    ]
    # suffix variants normalise
    assert revise_invalidates_downstream("stage1_confirmed") == revise_invalidates_downstream("stage1")


def test_revise_invalidates_downstream_unknown_raises():
    with pytest.raises(ValueError):
        revise_invalidates_downstream("stage9")


def test_is_terminal():
    assert is_terminal("completed") is True
    assert is_terminal("failed") is False
    assert is_terminal("generating") is False
    assert is_terminal("draft") is False


# --------------------------------------------------------------------------
# Model construction
# --------------------------------------------------------------------------
def test_model_construction_all_fields():
    proj = GuidedProject(
        owner_user_id=123,
        title="Quarterly Strategy",
        mode="guided",
        current_stage="stage1_draft",
        status="draft",
        revision=1,
        stage1_json={"audience": "exec"},
        stage2_json=None,
        recommendations_json=[{"direction_id": "safe"}],
        source_refs_json=[{"type": "doc"}],
        generation_task_id=None,
    )
    # construction-time attributes (uuid/server_default are applied on flush)
    assert proj.guided_project_id is None
    assert proj.created_at is None
    assert proj.owner_user_id == 123
    assert proj.title == "Quarterly Strategy"
    assert proj.mode == "guided"
    assert proj.revision == 1
    assert proj.stage1_json == {"audience": "exec"}
    assert proj.recommendations_json == [{"direction_id": "safe"}]
    assert proj.source_refs_json == [{"type": "doc"}]
    assert proj.generation_task_id is None

    # round-trip: auto uuid + all JSON fields persist and reload correctly
    engine = make_engine()
    ensure_guided_tables(engine)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as s:
        s.add(proj)
        s.flush()
        assert proj.guided_project_id
        assert len(proj.guided_project_id) == 36
        s.commit()
        pid = proj.guided_project_id

    with SessionLocal() as s:
        got = s.get(GuidedProject, pid)
        assert got.owner_user_id == 123
        assert got.title == "Quarterly Strategy"
        assert got.stage1_json == {"audience": "exec"}
        assert got.recommendations_json == [{"direction_id": "safe"}]
        assert got.source_refs_json == [{"type": "doc"}]
        assert got.generation_task_id is None
        assert got.created_at is not None  # server_default now() applied


def test_model_persist_and_query():
    engine = make_engine()
    ensure_guided_tables(engine)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as s:
        p = GuidedProject(
            owner_user_id=1,
            title="t",
            current_stage="stage1_draft",
            status="draft",
        )
        s.add(p)
        s.commit()
        pid = p.guided_project_id
        assert pid

        got = s.get(GuidedProject, pid)
        assert got.owner_user_id == 1
        assert got.created_at is not None  # server_default now() applied

        # indexed ownership query works
        rows = (
            s.execute(select(GuidedProject).where(GuidedProject.owner_user_id == 1))
            .scalars()
            .all()
        )
        assert len(rows) == 1


# --------------------------------------------------------------------------
# Migration idempotency + non-interference
# --------------------------------------------------------------------------
def test_migration_idempotent_in_memory():
    engine = make_engine()
    ensure_guided_tables(engine)
    # second call must be a no-op (idempotent) and raise nothing
    ensure_guided_tables(engine)

    cols = [c["name"] for c in inspect(engine).get_columns("guided_projects")]
    expected_cols = [
        "guided_project_id",
        "owner_user_id",
        "project_id",
        "title",
        "mode",
        "current_stage",
        "status",
        "revision",
        "stage1_json",
        "stage2_json",
        "stage3_json",
        "recommendations_json",
        "result_json",
        "confirmed_values_json",
        "source_refs_json",
        "generation_task_id",
        "error_json",
        "created_at",
        "updated_at",
        "confirmed_at",
        "completed_at",
    ]
    for col in expected_cols:
        assert col in cols, f"missing column {col}"


def test_migration_does_not_alter_existing_tables():
    engine = make_engine()
    # an existing unrelated PPT table
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS ppt_projects (id INTEGER PRIMARY KEY, name TEXT)")
        )

    ensure_guided_tables(engine)

    tables = inspect(engine).get_table_names()
    assert "ppt_projects" in tables
    assert "guided_projects" in tables

    # existing table must be untouched (columns unchanged)
    ppt_cols = [c["name"] for c in inspect(engine).get_columns("ppt_projects")]
    assert ppt_cols == ["id", "name"]


def test_migration_column_add_guard():
    """If an older guided_projects table is missing some columns, the guard
    adds them without dropping the table or touching rows."""
    engine = make_engine()
    with engine.begin() as conn:
        # simulate an older partial schema (missing stage3_json etc.)
        conn.execute(
            text(
                "CREATE TABLE guided_projects ("
                "guided_project_id VARCHAR(36) PRIMARY KEY, "
                "owner_user_id INTEGER NOT NULL, "
                "current_stage VARCHAR(32) NOT NULL)"
            )
        )
    ensure_guided_tables(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("guided_projects")}
    assert "stage3_json" in cols
    assert "result_json" in cols
    assert "confirmed_values_json" in cols
