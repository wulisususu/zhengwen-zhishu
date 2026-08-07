"""P4 Object Animation Pydantic schemas — request/response contracts.

Animation Manifest structure:
{
    "version": 1,
    "project_id": "pptproj_xxx",
    "animation_revision": 5,
    "slides": [{
        "slide_id": "slide_001",
        "animations": [{animation_obj}, ...]
    }]
}
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── Enums ──────────────────────────────────────────────────────────

class AnimationCategory(str, Enum):
    entrance = "entrance"
    emphasis = "emphasis"
    exit = "exit"


class AnimationEffect(str, Enum):
    """Engine-supported entrance effects (appear/fade/wipe/fly/zoom)."""
    appear = "appear"
    fade = "fade"
    wipe = "wipe"
    fly_in = "fly_in"
    zoom = "zoom"


class AnimationTrigger(str, Enum):
    on_click = "on_click"
    with_previous = "with_previous"
    after_previous = "after_previous"


# ── Effect <-> Category mapping ─────────────────────────────────────

CATEGORY_EFFECTS: dict[AnimationCategory, set[AnimationEffect]] = {
    AnimationCategory.entrance: {
        AnimationEffect.appear, AnimationEffect.fade, AnimationEffect.wipe,
        AnimationEffect.fly_in, AnimationEffect.zoom,
    },
    AnimationCategory.emphasis: set(),
    AnimationCategory.exit: set(),
}

# Direction enums per effect
EFFECT_DIRECTIONS: dict[AnimationEffect, set[str]] = {
    AnimationEffect.wipe: {"left", "right", "up", "down"},
    AnimationEffect.fly_in: {"left", "right", "top", "bottom", "top_left", "top_right", "bottom_left", "bottom_right"},
}


# ── Request schemas ─────────────────────────────────────────────────

class AnimationObject(BaseModel):
    """Single animation entry on an element."""
    model_config = ConfigDict(extra="forbid")

    animation_id: str = Field(min_length=1, max_length=128)
    element_id: str = Field(min_length=1, max_length=256)
    category: AnimationCategory
    effect: AnimationEffect
    order: int = Field(ge=0, le=99)
    duration_ms: int = Field(ge=100, le=10000, default=500)
    delay_ms: int = Field(ge=0, le=60000, default=0)
    trigger: AnimationTrigger = AnimationTrigger.on_click
    direction: Optional[Literal[None]] = None
    repeat: Literal[1] = 1
    enabled: bool = True

    @model_validator(mode="after")
    def validate_p4_entrance_only(self):
        if self.category is not AnimationCategory.entrance:
            raise ValueError("unsupported_animation_effect")
        return self


class SlideAnimations(BaseModel):
    """Animations for a single slide."""
    slide_id: str = Field(min_length=1, max_length=128)
    animations: list[AnimationObject] = Field(default_factory=list)


class AnimationManifest(BaseModel):
    """Full animation manifest for a project."""
    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1, le=1)
    project_id: str = Field(min_length=1, max_length=128)
    animation_revision: int = Field(ge=1)
    slides: list[SlideAnimations] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_animation_ids(self):
        seen = set()
        for slide in self.slides:
            for anim in slide.animations:
                if anim.animation_id in seen:
                    raise ValueError(f"Duplicate animation_id: {anim.animation_id}")
                seen.add(anim.animation_id)
        return self

    @model_validator(mode="after")
    def validate_orders_per_slide(self):
        for slide in self.slides:
            orders = [a.order for a in slide.animations]
            if len(orders) != len(set(orders)):
                raise ValueError(f"Duplicate order in slide {slide.slide_id}")
        return self


class AnimationSaveRequest(BaseModel):
    """Request body for saving animation manifest."""
    model_config = ConfigDict(extra="forbid")

    expected_document_revision: int = Field(ge=1)
    expected_animation_revision: int = Field(ge=1)
    manifest: AnimationManifest


class AnimationSaveResponse(BaseModel):
    """Response after saving animation manifest."""
    model_config = ConfigDict(extra="forbid")

    project_id: str
    document_revision: int
    animation_revision: int
    animation_count: int
    sha256: str


class AnimationGetResponse(BaseModel):
    """Response when reading animation manifest."""
    model_config = ConfigDict(extra="forbid")

    project_id: str
    document_revision: int
    animation_revision: int
    manifest: AnimationManifest


class AnimationValidateRequest(BaseModel):
    """Request to validate an animation manifest without saving."""
    model_config = ConfigDict(extra="forbid")

    manifest: AnimationManifest
    document: Optional[dict[str, Any]] = Field(default=None)  # optional editor doc for element validation


class AnimationValidateResponse(BaseModel):
    """Validation result."""
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnimationExportPreviewRequest(BaseModel):
    """Request to preview export animations — checks mapping validity."""
    model_config = ConfigDict(extra="forbid")

    expected_document_revision: int = Field(ge=1)
    expected_animation_revision: int = Field(ge=1)


class AnimationTargetManifestEntry(BaseModel):
    """Entry in animation target manifest — element_id → shape_id mapping."""
    slide_id: str
    element_id: str
    shape_id: Optional[int] = None
    shape_name: str = ""
    supported: bool = False
    reason: str = ""


class AnimationExportPreviewResponse(BaseModel):
    """Preview result showing what animations will produce in OOXML."""
    model_config = ConfigDict(extra="forbid")

    project_id: str
    document_revision: int
    animation_revision: int
    targets: list[AnimationTargetManifestEntry] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# ── Constants ───────────────────────────────────────────────────────

ANIMATION_LIMITS = {
    "duration_ms_min": 100,
    "duration_ms_max": 10000,
    "delay_ms_min": 0,
    "delay_ms_max": 60000,
    "repeat_min": 1,
    "repeat_max": 10,
    "per_slide_max": 100,
    "total_max": 1000,
}
