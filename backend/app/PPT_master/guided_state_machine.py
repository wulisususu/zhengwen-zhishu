"""P3-B Guided Strategist — pure state-machine logic (NO DB / HTTP imports).

OWNER: Sub1.

Every function here takes and returns plain Python values so it is fully
unit-testable without a database or web framework. The router/service layers
import these helpers; they never import back into those layers.

Stage flow (see P3B_SPEC §3)
----------------------------
stage1_draft -> stage1_confirmed -> stage2_draft -> stage2_confirmed ->
stage3_draft -> confirmed -> generating -> completed
plus failure state: any generation error moves `generating` -> `failed`,
and `failed` -> `generating` via retry.

Optimistic locking
------------------
Every mutating request carries ``expected_revision``. ``check_revision`` raises
``RevisionConflict`` (HTTP 409, error_code="revision_conflict") on mismatch.
``revision`` increments by 1 on every successful mutation.

Immutability / revise
---------------------
After a stage is confirmed its draft is immutable. Editing an earlier stage
requires an explicit "revise" action that invalidates all downstream
confirmations (downstream stages reset to draft; downstream JSON cleared).
``revise_invalidates_downstream`` reports which JSON fields to clear.
"""
from __future__ import annotations


# --- Stages (linear flow) ------------------------------------------------
STAGES = (
    "stage1_draft",
    "stage1_confirmed",
    "stage2_draft",
    "stage2_confirmed",
    "stage3_draft",
    "confirmed",
    "generating",
    "completed",
)

# --- Status values -------------------------------------------------------
STATUS_DRAFT = "draft"
STATUS_CONFIRMED = "confirmed"
STATUS_GENERATING = "generating"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

ALL_STATUSES = (
    STATUS_DRAFT,
    STATUS_CONFIRMED,
    STATUS_GENERATING,
    STATUS_COMPLETED,
    STATUS_FAILED,
)

# A terminal status admits no further mutation transitions.
TERMINAL_STATUSES = (STATUS_COMPLETED,)

# --- Allowed transitions -------------------------------------------------
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "stage1_draft": ("stage1_confirmed",),
    "stage1_confirmed": ("stage2_draft",),
    "stage2_draft": ("stage2_confirmed",),
    "stage2_confirmed": ("stage3_draft",),
    "stage3_draft": ("confirmed",),
    "confirmed": ("generating",),
    "generating": ("completed", "failed"),
    "failed": ("generating",),
    "completed": (),  # terminal
}

# Linear "confirm/advance" progression used by apply_confirm.
_NEXT_STAGE = {
    "stage1_draft": "stage1_confirmed",
    "stage1_confirmed": "stage2_draft",
    "stage2_draft": "stage2_confirmed",
    "stage2_confirmed": "stage3_draft",
    "stage3_draft": "confirmed",
    "confirmed": "generating",
    "generating": "completed",
    "failed": "generating",
}


class RevisionConflict(Exception):
    """Raised when expected_revision != actual_revision. Maps to HTTP 409."""

    error_code = "revision_conflict"
    status_code = 409

    def __init__(self, expected: int, actual: int):
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Revision conflict: expected {expected}, but current revision is "
            f"{actual}. Reload the latest state and re-apply your change."
        )


def validate_transition(current_stage: str, target: str) -> bool:
    """Return True iff ``target`` is an allowed transition from ``current_stage``."""
    return target in ALLOWED_TRANSITIONS.get(current_stage, ())


def check_revision(expected: int, actual: int) -> None:
    """Raise ``RevisionConflict`` (HTTP 409) when the optimistic-lock revision
    does not match. No-op when they are equal."""
    if expected != actual:
        raise RevisionConflict(expected, actual)


def can_patch_stage(current_stage: str, stage_name: str) -> bool:
    """A stage draft is patchable only when it is the *current* draft stage.

    Once a stage is confirmed it is immutable; editing it requires an explicit
    revise action (see ``revise_invalidates_downstream``).
    """
    return current_stage == f"{stage_name}_draft"


def apply_confirm(current_stage: str) -> str:
    """Return the next stage after a successful confirm/advance action.

    Raises ``ValueError`` for terminal or unknown stages.
    """
    if current_stage not in _NEXT_STAGE:
        raise ValueError(f"Cannot advance from terminal/unknown stage: {current_stage}")
    return _NEXT_STAGE[current_stage]


def revise_invalidates_downstream(stage: str) -> list[str]:
    """Given a stage being revised, return the JSON field names that must be
    cleared because they are downstream of (and invalidated by) the revision.

    ``stage`` may be passed as ``stage1`` / ``stage1_draft`` / ``stage1_confirmed``
    etc. — the suffix is normalised. Revising an earlier stage resets all
    downstream stages to draft and clears their confirmed JSON.
    """
    normalised = stage.replace("_confirmed", "").replace("_draft", "")
    if normalised == "stage1":
        return [
            "stage2_json",
            "stage3_json",
            "recommendations_json",
            "result_json",
            "confirmed_values_json",
        ]
    if normalised == "stage2":
        return ["stage3_json", "result_json", "confirmed_values_json"]
    if normalised == "stage3":
        return ["result_json", "confirmed_values_json"]
    raise ValueError(f"Unknown stage for revise: {stage}")


def is_terminal(status: str) -> bool:
    """Return True if a project in ``status`` can no longer be mutated."""
    return status in TERMINAL_STATUSES
