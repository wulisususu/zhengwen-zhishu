"""P4 Animation Service — CRUD + validation + revision management.

Ownership: project scoped per user. Concurrent writes guarded by
animation_revision (independent from document_revision).

Export integration point: provides manifest to editor export pipeline.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.PPT_master.animation_models import PPTAnimationManifest
from app.PPT_master.animation_schemas import (
    ANIMATION_LIMITS,
    AnimationCategory,
    AnimationEffect,
    AnimationManifest,
    AnimationObject,
    CATEGORY_EFFECTS,
    EFFECT_DIRECTIONS,
)


class AnimationNotFound(LookupError):
    def __init__(self, project_id: str):
        super().__init__(f"No animation manifest for project {project_id}")


class AnimationRevisionConflict(RuntimeError):
    def __init__(self, project_id: str, expected: int, actual: int):
        super().__init__(f"Animation revision conflict for {project_id}")
        self.project_id = project_id
        self.expected = expected
        self.actual = actual


class AnimationValidationError(ValueError):
    """Raised when animation data fails validation."""
    pass


class AnimationService:
    """Stateless animation CRUD service.

    All methods accept `db: Session` as first positional arg following
    the project convention.
    """

    # ── Helpers ───────────────────────────────────────────────────

    def _manifest_to_dict(self, manifest: AnimationManifest) -> dict:
        return manifest.model_dump(mode="json")

    def _dict_to_manifest(self, data: dict) -> AnimationManifest:
        return AnimationManifest.model_validate(data)

    def _hash_manifest(self, manifest: AnimationManifest) -> str:
        """SHA-256 of canonical JSON."""
        raw = json.dumps(self._manifest_to_dict(manifest), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _latest(self, db: Session, project_id: str, user_id: int) -> Optional[PPTAnimationManifest]:
        return (
            db.query(PPTAnimationManifest)
            .filter(
                PPTAnimationManifest.project_id == project_id,
                PPTAnimationManifest.user_id == user_id,
            )
            .order_by(PPTAnimationManifest.animation_revision.desc())
            .first()
        )

    # ── Validation ────────────────────────────────────────────────

    def validate_animation(self, anim: AnimationObject, slide_ids: set[str],
                           element_ids: set[str]) -> list[str]:
        """Validate a single animation object. Returns list of error messages (empty = valid)."""
        errors: list[str] = []

        # Slide must exist
        for slide in []:  # slide_ids passed in, checked at manifest level
            pass

        # animation_id uniqueness (checked at manifest level)
        if not anim.animation_id or len(anim.animation_id) > 128:
            errors.append(f"Invalid animation_id: {anim.animation_id}")

        # element_id must be non-empty
        if not anim.element_id:
            errors.append("element_id is required")

        # element must exist in document (if element_ids provided)
        if element_ids and anim.element_id not in element_ids:
            errors.append(f"element_id not found in document: {anim.element_id}")

        # category/effect match
        valid_effects = CATEGORY_EFFECTS.get(anim.category, set())
        if anim.effect not in valid_effects:
            errors.append(
                f"Effect '{anim.effect.value}' not valid for category '{anim.category.value}'. "
                f"Valid: {[e.value for e in valid_effects]}"
            )

        # trigger
        if anim.trigger is None:
            errors.append("trigger is required")

        # duration
        if not (ANIMATION_LIMITS["duration_ms_min"] <= anim.duration_ms <= ANIMATION_LIMITS["duration_ms_max"]):
            errors.append(
                f"duration_ms must be {ANIMATION_LIMITS['duration_ms_min']}-{ANIMATION_LIMITS['duration_ms_max']}, "
                f"got {anim.duration_ms}"
            )

        # delay
        if not (ANIMATION_LIMITS["delay_ms_min"] <= anim.delay_ms <= ANIMATION_LIMITS["delay_ms_max"]):
            errors.append(
                f"delay_ms must be {ANIMATION_LIMITS['delay_ms_min']}-{ANIMATION_LIMITS['delay_ms_max']}, "
                f"got {anim.delay_ms}"
            )

        # P4 exporter supports the default single play only.
        if anim.repeat != 1:
            errors.append("unsupported_animation_repeat")

        # order
        if anim.order < 0 or anim.order > 99:
            errors.append(f"order must be 0-99, got {anim.order}")

        # P4 exporter does not preserve effect direction.
        if anim.direction is not None:
            errors.append("unsupported_animation_direction")

        return errors

    def validate_manifest(self, manifest: AnimationManifest,
                          slide_ids: Optional[set[str]] = None,
                          element_ids: Optional[set[str]] = None,
                          elements_by_slide: Optional[dict[str, set[str]]] = None) -> list[str]:
        """Validate entire manifest. Returns list of error messages."""
        errors: list[str] = []

        # Count limits
        total = sum(len(s.animations) for s in manifest.slides)
        if total > ANIMATION_LIMITS["total_max"]:
            errors.append(f"Total animations ({total}) exceeds limit ({ANIMATION_LIMITS['total_max']})")

        # Per slide checks
        anim_ids = set()
        for slide in manifest.slides:
            if slide_ids and slide.slide_id not in slide_ids:
                errors.append(f"slide_id not found in document: {slide.slide_id}")

            if len(slide.animations) > ANIMATION_LIMITS["per_slide_max"]:
                errors.append(
                    f"Slide {slide.slide_id} has {len(slide.animations)} animations, "
                    f"max {ANIMATION_LIMITS['per_slide_max']}"
                )

            orders = set()
            target_ids = set()
            triggers = set()
            for anim in slide.animations:
                if anim.element_id in target_ids:
                    errors.append(f"Duplicate animation target {anim.element_id} in slide {slide.slide_id}")
                target_ids.add(anim.element_id)
                if anim.animation_id in anim_ids:
                    errors.append(f"Duplicate animation_id: {anim.animation_id}")
                anim_ids.add(anim.animation_id)

                if anim.order in orders:
                    errors.append(f"Duplicate order {anim.order} in slide {slide.slide_id}")
                orders.add(anim.order)
                triggers.add(anim.trigger)

                # A target must belong to the manifest's slide, not merely exist
                # somewhere else in the document.
                if elements_by_slide is not None and anim.element_id not in elements_by_slide.get(slide.slide_id, set()):
                    errors.append(f"element_id not found on slide {slide.slide_id}: {anim.element_id}")

                # Validate individual animation
                anim_errors = self.validate_animation(anim, slide_ids or set(), element_ids or set())
                errors.extend(anim_errors)

            # The OOXML writer uses one main sequence for a slide. Reject a
            # mixed Start mode instead of exporting a misleading schedule.
            if len(triggers) > 1:
                errors.append(f"Mixed animation triggers are not supported in slide {slide.slide_id}")

        return errors

    # ── CRUD ──────────────────────────────────────────────────────

    def get(self, db: Session, project_id: str, user_id: int) -> dict:
        """Get current animation manifest for a project."""
        row = self._latest(db, project_id, user_id)
        if row is None:
            raise AnimationNotFound(project_id)

        manifest = self._dict_to_manifest(json.loads(row.animations_json))
        return {
            "project_id": project_id,
            "document_revision": row.document_revision,
            "animation_revision": row.animation_revision,
            "manifest": self._manifest_to_dict(manifest),
        }

    def get_or_initialize(self, db: Session, project_id: str, user_id: int) -> dict:
        """Get current or initialize empty manifest."""
        try:
            return self.get(db, project_id, user_id)
        except AnimationNotFound:
            manifest = AnimationManifest(
                version=1,
                project_id=project_id,
                animation_revision=1,
                slides=[],
            )
            return {
                "project_id": project_id,
                "document_revision": 0,
                "animation_revision": 1,
                "manifest": self._manifest_to_dict(manifest),
            }

    def save(self, db: Session, project_id: str, user_id: int,
             expected_document_revision: int, expected_animation_revision: int,
             manifest: AnimationManifest, slide_ids: set[str],
             element_ids: set[str], elements_by_slide: Optional[dict[str, set[str]]] = None) -> dict:
        """Save animation manifest with revision conflict detection.

        Raises:
            AnimationRevisionConflict: if expected_animation_revision != current
            AnimationValidationError: if manifest fails validation
        """

        # Validate
        errors = self.validate_manifest(manifest, slide_ids, element_ids, elements_by_slide)
        if errors:
            raise AnimationValidationError("; ".join(errors))

        # Check animation revision
        existing = self._latest(db, project_id, user_id)
        if existing and expected_animation_revision != existing.animation_revision:
            raise AnimationRevisionConflict(
                project_id, expected_animation_revision, existing.animation_revision
            )

        # Create new manifest row
        sha = self._hash_manifest(manifest)
        new_row = PPTAnimationManifest(
            manifest_id=str(uuid.uuid4()),
            project_id=project_id,
            user_id=user_id,
            document_revision=expected_document_revision,
            animation_revision=expected_animation_revision if not existing else existing.animation_revision + 1,
            animations_json=json.dumps(self._manifest_to_dict(manifest), ensure_ascii=False),
            sha256=sha,
        )
        db.add(new_row)
        db.commit()
        db.refresh(new_row)

        return {
            "project_id": project_id,
            "document_revision": new_row.document_revision,
            "animation_revision": new_row.animation_revision,
            "animation_count": sum(len(s.animations) for s in manifest.slides),
            "sha256": sha,
        }

    def validate_only(self, manifest: AnimationManifest,
                      slide_ids: Optional[set[str]] = None,
                      element_ids: Optional[set[str]] = None,
                      elements_by_slide: Optional[dict[str, set[str]]] = None) -> dict:
        """Validate manifest without saving."""
        errors = self.validate_manifest(manifest, slide_ids, element_ids, elements_by_slide)
        warnings: list[str] = []

        # Check for disabled animations (warning, not error)
        for slide in manifest.slides:
            for anim in slide.animations:
                if not anim.enabled:
                    warnings.append(
                        f"Animation {anim.animation_id} is disabled and will not be exported"
                    )

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    def delete_all(self, db: Session, project_id: str, user_id: int):
        """Delete all animation manifests for a project (used when deleting project)."""
        db.query(PPTAnimationManifest).filter(
            PPTAnimationManifest.project_id == project_id,
            PPTAnimationManifest.user_id == user_id,
        ).delete()
        db.commit()

    def cleanup_orphaned(self, manifest: AnimationManifest, deleted_element_ids: set[str]) -> AnimationManifest:
        """Remove animations referencing deleted elements. Returns cleaned manifest."""
        cleaned = AnimationManifest(
            version=manifest.version,
            project_id=manifest.project_id,
            animation_revision=manifest.animation_revision,
            slides=[],
        )
        for slide in manifest.slides:
            remaining = [a for a in slide.animations if a.element_id not in deleted_element_ids]
            if remaining:
                cleaned.slides.append(
                    type(slide)(slide_id=slide.slide_id, animations=remaining)
                )
        return cleaned
