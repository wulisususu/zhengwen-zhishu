"""P4 Animation unit tests — schema, service, validation, revision, isolation.

Fixed version: pydantic ValidationError and schema-level validation alignment.
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace
from pydantic import ValidationError as PydanticValidationError
from app.PPT_master.animation_schemas import (
    AnimationCategory,
    AnimationEffect,
    AnimationManifest,
    AnimationObject,
    AnimationTrigger,
    SlideAnimations,
    CATEGORY_EFFECTS,
)
from app.PPT_master.animation_service import (
    AnimationService,
)
from fastapi import HTTPException
from app.PPT_master.animation_router import _parse_animation_request
from app.PPT_master.animation_schemas import AnimationSaveRequest, AnimationValidateRequest


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def service():
    return AnimationService()


@pytest.fixture
def valid_animation():
    return AnimationObject(
        animation_id="anim_001",
        element_id="el_001",
        category=AnimationCategory.entrance,
        effect=AnimationEffect.fade,
        order=1,
        duration_ms=500,
        delay_ms=0,
        trigger=AnimationTrigger.on_click,
        direction=None,
        repeat=1,
        enabled=True,
    )


@pytest.fixture
def valid_manifest():
    return AnimationManifest(
        version=1,
        project_id="test_project",
        animation_revision=1,
        slides=[
            SlideAnimations(
                slide_id="slide_001",
                animations=[
                    AnimationObject(
                        animation_id="anim_001",
                        element_id="el_001",
                        category=AnimationCategory.entrance,
                        effect=AnimationEffect.fade,
                        order=1,
                        duration_ms=500,
                        delay_ms=0,
                        trigger=AnimationTrigger.on_click,
                        repeat=1,
                        enabled=True,
                    )
                ],
            )
        ],
    )


# ── Schema Tests ──────────────────────────────────────────────────

class TestAnimationSchema:
    def test_valid_animation(self, valid_animation):
        assert valid_animation.animation_id == "anim_001"
        assert valid_animation.category == AnimationCategory.entrance
        assert valid_animation.effect == AnimationEffect.fade

    def test_category_effect_mapping(self):
        assert CATEGORY_EFFECTS == {
            AnimationCategory.entrance: set(AnimationEffect),
            AnimationCategory.emphasis: set(),
            AnimationCategory.exit: set(),
        }

    def test_invalid_effect_for_category_detected_by_service(self):
        """Service validation catches category/effect mismatch even if schema doesn't."""
        anim = AnimationObject.model_construct(
            animation_id="a1", element_id="e1",
            category=AnimationCategory.exit,
            effect=AnimationEffect.fade,
            order=1, duration_ms=500, delay_ms=0,
            trigger=AnimationTrigger.on_click, repeat=1,
        )
        svc = AnimationService()
        errors = svc.validate_animation(anim, {"s1"}, {"e1"})
        assert len(errors) > 0
        assert any("not valid for category" in e for e in errors)

    def test_duration_ms_bounds(self):
        a1 = AnimationObject(animation_id="a1", element_id="e1",
                        category=AnimationCategory.entrance, effect=AnimationEffect.fade,
                        order=1, duration_ms=100, delay_ms=0,
                        trigger=AnimationTrigger.on_click, repeat=1)
        assert a1.duration_ms == 100

        a2 = AnimationObject(animation_id="a2", element_id="e2",
                        category=AnimationCategory.entrance, effect=AnimationEffect.fade,
                        order=2, duration_ms=10000, delay_ms=0,
                        trigger=AnimationTrigger.on_click, repeat=1)
        assert a2.duration_ms == 10000

    def test_delay_ms_bounds(self):
        a1 = AnimationObject(animation_id="a1", element_id="e1",
                        category=AnimationCategory.entrance, effect=AnimationEffect.fade,
                        order=1, duration_ms=500, delay_ms=0,
                        trigger=AnimationTrigger.on_click, repeat=1)
        assert a1.delay_ms == 0

        a2 = AnimationObject(animation_id="a2", element_id="e2",
                        category=AnimationCategory.entrance, effect=AnimationEffect.fade,
                        order=2, duration_ms=500, delay_ms=60000,
                        trigger=AnimationTrigger.on_click, repeat=1)
        assert a2.delay_ms == 60000

    def test_repeat_bounds(self):
        a1 = AnimationObject(animation_id="a1", element_id="e1",
                        category=AnimationCategory.entrance, effect=AnimationEffect.fade,
                        order=1, duration_ms=500, delay_ms=0,
                        trigger=AnimationTrigger.on_click, repeat=1)
        assert a1.repeat == 1

        with pytest.raises(PydanticValidationError):
            AnimationObject(animation_id="a2", element_id="e2",
                            category=AnimationCategory.entrance, effect=AnimationEffect.fade,
                            order=2, duration_ms=500, delay_ms=0,
                            trigger=AnimationTrigger.on_click, repeat=10)

    def test_manifest_unique_animation_ids_rejected(self):
        """Schema model_validator rejects duplicate animation_ids."""
        with pytest.raises(PydanticValidationError, match="Duplicate animation_id"):
            AnimationManifest(
                version=1, project_id="test", animation_revision=1,
                slides=[
                    SlideAnimations(slide_id="s1", animations=[
                        AnimationObject(animation_id="dup", element_id="e1",
                                        category=AnimationCategory.entrance, effect=AnimationEffect.fade,
                                        order=1, duration_ms=500, delay_ms=0,
                                        trigger=AnimationTrigger.on_click, repeat=1),
                        AnimationObject(animation_id="dup", element_id="e2",
                                        category=AnimationCategory.entrance, effect=AnimationEffect.fade,
                                        order=2, duration_ms=500, delay_ms=0,
                                        trigger=AnimationTrigger.on_click, repeat=1),
                    ])
                ],
            )

    def test_manifest_duplicate_order_rejected(self):
        """Schema model_validator rejects duplicate orders per slide."""
        with pytest.raises(PydanticValidationError, match="Duplicate order"):
            AnimationManifest(
                version=1, project_id="test", animation_revision=1,
                slides=[
                    SlideAnimations(slide_id="s1", animations=[
                        AnimationObject(animation_id="a1", element_id="e1",
                                        category=AnimationCategory.entrance, effect=AnimationEffect.fade,
                                        order=1, duration_ms=500, delay_ms=0,
                                        trigger=AnimationTrigger.on_click, repeat=1),
                        AnimationObject(animation_id="a2", element_id="e2",
                                        category=AnimationCategory.entrance, effect=AnimationEffect.fade,
                                        order=1, duration_ms=500, delay_ms=0,
                                        trigger=AnimationTrigger.on_click, repeat=1),
                    ])
                ],
            )

    def test_disabled_animation(self, valid_animation):
        anim = valid_animation.model_copy(update={"enabled": False})
        assert anim.enabled is False


# ── Service Validation Tests ──────────────────────────────────────

class TestAnimationValidation:
    def test_valid_animation_passes(self, service, valid_animation):
        errors = service.validate_animation(valid_animation, {"slide_001"}, {"el_001"})
        assert len(errors) == 0

    def test_effect_category_mismatch(self, service):
        anim = AnimationObject.model_construct(
            animation_id="a1", element_id="e1",
            category=AnimationCategory.emphasis,
            effect=AnimationEffect.fade,  # entrance, not emphasis
            order=1, duration_ms=500, delay_ms=0,
            trigger=AnimationTrigger.on_click, repeat=1,
        )
        errors = service.validate_animation(anim, {"s1"}, {"e1"})
        assert len(errors) > 0
        assert any("not valid for category" in e for e in errors)

    def test_element_not_found(self, service, valid_animation):
        errors = service.validate_animation(valid_animation, {"slide_001"}, {"different_element"})
        assert len(errors) > 0
        assert any("not found in document" in e for e in errors)

    def test_duration_out_of_range(self, service):
        """Service catches duration violations (schema has Field constraints)."""
        # Test via model_construct to bypass pydantic validation
        anim = AnimationObject.model_construct(
            animation_id="a1", element_id="e1",
            category=AnimationCategory.entrance, effect=AnimationEffect.fade,
            order=1, duration_ms=50, delay_ms=0,
            trigger=AnimationTrigger.on_click, repeat=1,
        )
        errors = service.validate_animation(anim, {"s1"}, {"e1"})
        assert any("duration_ms" in e for e in errors)

        anim2 = AnimationObject.model_construct(
            animation_id="a2", element_id="e2",
            category=AnimationCategory.entrance, effect=AnimationEffect.fade,
            order=2, duration_ms=20000, delay_ms=0,
            trigger=AnimationTrigger.on_click, repeat=1,
        )
        errors2 = service.validate_animation(anim2, {"s1"}, {"e2"})
        assert any("duration_ms" in e for e in errors2)

    def test_delay_out_of_range(self, service):
        anim = AnimationObject.model_construct(
            animation_id="a1", element_id="e1",
            category=AnimationCategory.entrance, effect=AnimationEffect.fade,
            order=1, duration_ms=500, delay_ms=120000,
            trigger=AnimationTrigger.on_click, repeat=1,
        )
        errors = service.validate_animation(anim, {"s1"}, {"e1"})
        assert any("delay_ms" in e for e in errors)

    def test_repeat_out_of_range(self, service):
        anim = AnimationObject.model_construct(
            animation_id="a1", element_id="e1",
            category=AnimationCategory.entrance, effect=AnimationEffect.fade,
            order=1, duration_ms=500, delay_ms=0,
            trigger=AnimationTrigger.on_click, repeat=0,
        )
        errors = service.validate_animation(anim, {"s1"}, {"e1"})
        assert any("repeat" in e for e in errors)

    def test_direction_is_rejected_at_schema_boundary(self, service):
        with pytest.raises(PydanticValidationError):
            AnimationObject(animation_id="a1", element_id="e1",
                            category=AnimationCategory.entrance, effect=AnimationEffect.wipe,
                            order=1, duration_ms=500, delay_ms=0,
                            trigger=AnimationTrigger.on_click, direction="left", repeat=1)

    def test_constructed_non_default_direction_is_rejected_by_service(self, service):
        anim = AnimationObject.model_construct(
            animation_id="a1", element_id="e1", category=AnimationCategory.entrance,
            effect=AnimationEffect.fade, order=1, duration_ms=500, delay_ms=0,
            trigger=AnimationTrigger.on_click, direction="left", repeat=1,
        )
        assert "unsupported_animation_direction" in service.validate_animation(anim, {"s1"}, {"e1"})


class TestManifestValidation:
    def test_valid_manifest_passes(self, service, valid_manifest):
        errors = service.validate_manifest(valid_manifest, {"slide_001"}, {"el_001"})
        assert len(errors) == 0

    def test_total_limit(self, service):
        slides = []
        for i in range(11):
            animations = []
            for j in range(100):
                animations.append(AnimationObject(
                    animation_id=f"anim_{i}_{j}", element_id=f"el_{i}_{j}",
                    category=AnimationCategory.entrance, effect=AnimationEffect.fade,
                    order=j, duration_ms=500, delay_ms=0,
                    trigger=AnimationTrigger.on_click, repeat=1,
                ))
            slides.append(SlideAnimations(slide_id=f"s{i}", animations=animations))
        manifest = AnimationManifest(version=1, project_id="test", animation_revision=1, slides=slides)
        errors = service.validate_manifest(manifest)
        assert any("Total animations" in e for e in errors)

    def test_missing_slide(self, service, valid_manifest):
        errors = service.validate_manifest(valid_manifest, {"different_slide"}, {"el_001"})
        assert any("not found in document" in e for e in errors)

    def test_cleanup_orphaned(self, service, valid_manifest):
        cleaned = service.cleanup_orphaned(valid_manifest, {"el_001"})
        total = sum(len(s.animations) for s in cleaned.slides)
        assert total == 0

    def test_cross_slide_target_is_rejected_when_ownership_is_known(self, service, valid_manifest):
        errors = service.validate_manifest(
            valid_manifest,
            {"slide_001", "slide_002"},
            {"el_001", "el_002"},
            {"slide_001": {"el_002"}, "slide_002": {"el_001"}},
        )
        assert any("not found on slide slide_001" in error for error in errors)


# ── Effect/Category Matrix Tests ──────────────────────────────────

class TestEffectMatrix:
    def test_entrance_effects(self):
        entrance = CATEGORY_EFFECTS[AnimationCategory.entrance]
        assert entrance == set(AnimationEffect)

    def test_emphasis_effects(self):
        emphasis = CATEGORY_EFFECTS[AnimationCategory.emphasis]
        assert emphasis == set()

    def test_exit_effects(self):
        exit_effects = CATEGORY_EFFECTS[AnimationCategory.exit]
        assert exit_effects == set()

    def test_trigger_values(self):
        triggers = [t.value for t in AnimationTrigger]
        assert "on_click" in triggers
        assert "with_previous" in triggers
        assert "after_previous" in triggers


# ── Import check ──────────────────────────────────────────────────

class TestPptxAnimationsImport:
    def test_animation_schemas_importable(self):
        """Core P4 schemas are importable."""
        from app.PPT_master.animation_schemas import AnimationObject, AnimationManifest
        assert AnimationObject is not None
        assert AnimationManifest is not None


class TestExplicitTargetContract:
    def test_duplicate_target_in_one_slide_is_rejected(self, service):
        duplicate = AnimationManifest(
            version=1, project_id="p", animation_revision=1,
            slides=[SlideAnimations(slide_id="s1", animations=[
                AnimationObject(animation_id="a1", element_id="e1", category=AnimationCategory.entrance, effect=AnimationEffect.fade, order=1, duration_ms=500, delay_ms=0, trigger=AnimationTrigger.on_click),
                AnimationObject(animation_id="a2", element_id="e1", category=AnimationCategory.entrance, effect=AnimationEffect.wipe, order=2, duration_ms=500, delay_ms=0, trigger=AnimationTrigger.on_click),
            ])],
        )
        errors = service.validate_manifest(duplicate, {"s1"}, {"e1"})
        assert any("Duplicate animation target" in error for error in errors)


class TestUnsupportedAnimationContract:
    def test_exit_category_is_rejected_at_schema_boundary(self):
        with pytest.raises(PydanticValidationError):
            AnimationObject(
                animation_id="x", element_id="e", category="exit", effect="fade",
                order=1, duration_ms=500, delay_ms=0, trigger="on_click",
            )


class TestUnsupportedAnimationApiContract:
    @pytest.mark.parametrize("category,effect", [("exit", "fade"), ("entrance", "fade_out"), ("entrance", "pulse")])
    def test_unsupported_payload_is_normalized_to_422(self, category, effect):
        with pytest.raises(HTTPException) as raised:
            _parse_animation_request({
                "expected_document_revision": 1,
                "expected_animation_revision": 1,
                "manifest": {"version": 1, "project_id": "p", "animation_revision": 1, "slides": [{"slide_id": "s1", "animations": [{"animation_id": "a", "element_id": "e", "category": category, "effect": effect, "order": 1, "duration_ms": 500, "delay_ms": 0, "trigger": "on_click"}]}]},
            }, AnimationSaveRequest)
        assert raised.value.status_code == 422
        assert raised.value.detail == {"code": "unsupported_animation_effect"}


class TestCrossSlideApiContract:
    def test_validate_endpoint_rejects_target_owned_by_another_slide(self, valid_manifest):
        from app.PPT_master.animation_router import validate_animations
        result = validate_animations(
            "test_project",
            AnimationValidateRequest(
                manifest=valid_manifest,
                document={"slides": [
                    {"id": "slide_001", "elements": [{"id": "other"}]},
                    {"id": "slide_002", "elements": [{"id": "el_001"}]},
                ]},
            ),
            current_user=SimpleNamespace(username="123", id=1),
            db=None,
        )
        assert result["data"]["valid"] is False
        assert any("not found on slide slide_001" in error for error in result["data"]["errors"])

    def test_preview_marks_cross_slide_target_unsupported(self, monkeypatch, valid_manifest):
        from app.PPT_master import animation_router
        document = {"slides": [
            {"id": "slide_001", "elements": [{"id": "other"}]},
            {"id": "slide_002", "elements": [{"id": "el_001"}]},
        ]}
        monkeypatch.setattr(animation_router._service, "get", lambda *args, **kwargs: {
            "project_id": "test_project", "document_revision": 1, "animation_revision": 1,
            "manifest": valid_manifest.model_dump(mode="json"),
        })
        monkeypatch.setattr(animation_router._docs, "get_or_initialize", lambda *args, **kwargs: {"revision": 1, "document": document})
        result = animation_router.export_preview_animations_qp(
            "test_project", 1, 1, current_user=SimpleNamespace(username="123", id=1), db=None,
        )
        target = result["data"]["targets"][0]
        assert target["supported"] is False
        assert target["reason"] == "element not found on slide"


class TestUnsupportedAnimationParameterApiContract:
    @pytest.mark.parametrize(
        "field,value,code",
        [("direction", "left", "unsupported_animation_direction"), ("repeat", 2, "unsupported_animation_repeat")],
    )
    def test_non_default_animation_parameter_is_rejected_at_api_boundary(self, field, value, code):
        animation = {
            "animation_id": "a", "element_id": "e", "category": "entrance",
            "effect": "wipe", "order": 1, "duration_ms": 500,
            "delay_ms": 0, "trigger": "on_click",
        }
        animation[field] = value
        with pytest.raises(HTTPException) as raised:
            _parse_animation_request({
                "expected_document_revision": 1,
                "expected_animation_revision": 1,
                "manifest": {
                    "version": 1, "project_id": "p", "animation_revision": 1,
                    "slides": [{"slide_id": "s1", "animations": [animation]}],
                },
            }, AnimationSaveRequest)
        assert raised.value.status_code == 422
        assert raised.value.detail == {"code": code}
