"""Background producer for durable per-slide PPT milestone events."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import or_

from app.database import SessionLocal
from app.PPT_master.admission import enforce_directory_quota
from app.PPT_master.incremental_slides import (
    SlideGenerationResult,
    extract_outline,
    generate_slide,
    summarize_design,
)
from app.PPT_master.incremental_store import IncrementalTaskStore
from app.PPT_master.planning_media import build_image_slots, inject_slot_image
from app.models import File
from app.PPT_master.nodes import export_node, parse_node, source_md_node, spec_node, validate_node
from app.PPT_master.state import initial_state
from app.PPT_master.validation import build_validation_result, count_pptx_slides
from app.services.artifact_service import ArtifactError, ArtifactService, SVG_MIME_TYPE


logger = logging.getLogger(__name__)
_PROJECT_MAX_BYTES = 200 * 1024 * 1024


def page_count_mismatch_result(requested: int, outline: int, completed: int, exported: int) -> dict:
    message = (
        f"page_count_mismatch: requested={requested}, outline={outline}, "
        f"completed={completed}, exported={exported}"
    )
    return build_validation_result(errors=[message], blocking_errors=["page_count_mismatch"])


@dataclass(frozen=True)
class PlanningResult:
    project_dir: Path
    design_spec: str
    outline: list[dict]
    design_summary: dict


async def _default_planner(
    *,
    task_id: str,
    user_id: int,
    user_input: str,
    page_count: int,
    page_format: str,
    source_context: str = "",
    source_manifest: list[dict] | None = None,
    pptx_structure_mode: str = "flat",
    structured_workspace_id: str | None = None,
) -> PlanningResult:
    state = initial_state(
        user_input,
        page_count,
        page_format,
        [],
        task_id,
        user_id,
        source_context,
        source_manifest,
        pptx_structure_mode,
        structured_workspace_id,
    )
    state = await parse_node(state)
    if state.get("status") == "graceful_fallback":
        raise RuntimeError("planning_project_init_failed")
    state = await source_md_node(state)
    state = await spec_node(state)
    if state.get("status") != "spec_done" or not state.get("project_dir"):
        raise RuntimeError("planning_spec_failed")
    design_spec = state.get("design_spec") or ""
    return PlanningResult(
        project_dir=Path(state["project_dir"]),
        design_spec=design_spec,
        outline=extract_outline(design_spec, page_count, user_input),
        design_summary=summarize_design(design_spec),
    )


async def _default_validator(*, planning: PlanningResult, page_count: int) -> dict:
    state = {
        "project_dir": str(planning.project_dir),
        "page_count": page_count,
        "validation_result": None,
    }
    result = await validate_node(state)
    return result.get("validation_result") or build_validation_result(
        blocking_errors=["validation_result_missing"]
    )


async def _default_exporter(
    *,
    planning: PlanningResult,
    page_count: int,
    validation_result: dict,
) -> dict:
    state = {
        "project_dir": str(planning.project_dir),
        "page_count": page_count,
        "validation_result": validation_result,
    }
    return await export_node(state)


async def run_incremental_workflow(
    *,
    task_id: str,
    project_id: str,
    user_id: int,
    user_input: str,
    page_count: int,
    page_format: str,
    event_sink: Callable[[dict], Awaitable[None]],
    source_context: str = "",
    source_manifest: list[dict] | None = None,
    pptx_structure_mode: str = "flat",
    structured_workspace_id: str | None = None,
    session_factory=SessionLocal,
    artifact_service: ArtifactService | None = None,
    planner: Callable[..., Awaitable[PlanningResult]] | None = None,
    slide_generator: Callable[..., Awaitable[SlideGenerationResult]] | None = None,
    validator: Callable[..., Awaitable[dict]] | None = None,
    exporter: Callable[..., Awaitable[dict]] | None = None,
) -> None:
    """Produce the complete incremental workflow; every event is stored before delivery."""

    store = IncrementalTaskStore()
    artifacts = artifact_service or ArtifactService()
    plan = planner or _default_planner
    make_slide = slide_generator or generate_slide
    validate = validator or _default_validator
    export = exporter or _default_exporter
    completed_count = 0

    async def emit(event_type: str, data: dict) -> dict:
        db = session_factory()
        try:
            envelope = store.append_event(db, task_id, event_type, data)
        finally:
            db.close()
        await event_sink(envelope)
        return envelope

    try:
        await emit("planning.started", {"status": "planning"})
        planning = await plan(
            task_id=task_id,
            user_id=user_id,
            user_input=user_input,
            page_count=page_count,
            page_format=page_format,
            source_context=source_context,
            source_manifest=source_manifest or [],
            pptx_structure_mode=pptx_structure_mode,
            structured_workspace_id=structured_workspace_id,
        )
        # Load workspace layouts for structured mode
        workspace_layouts = None
        if pptx_structure_mode == "structured" and structured_workspace_id:
            from app.PPT_master.workspace_service import WorkspaceService
            from app.PPT_master.structured_spec_lock import install_structured_templates
            db_ws = session_factory()
            try:
                ws = WorkspaceService().get_workspace(db_ws, structured_workspace_id)
                if ws:
                    workspace_layouts = ws.get("layout_manifest", [])
                    # Install layout template SVGs to project templates/ directory
                    install_structured_templates(planning.project_dir)
            finally:
                db_ws.close()

        # Collect layout assignments per page for spec_lock generation
        layout_assignments: list[str] = []

        outline = planning.outline[:page_count]
        if len(outline) < page_count:
            outline = extract_outline(planning.design_spec, page_count, user_input)
        planning = PlanningResult(planning.project_dir, planning.design_spec, outline, planning.design_summary)
        media_assets = [item for item in (source_manifest or []) if isinstance(item, dict) and item.get("kind") == "media_asset"]
        prepared_assets: list[dict] = []
        if media_assets:
            images_dir = planning.project_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            db = session_factory()
            try:
                for asset in media_assets:
                    record = db.query(File).filter(File.id == asset.get("file_id"), or_(File.owner_user_id == user_id, File.user_id == user_id)).first()
                    source = Path(record.real_path or record.filepath) if record else None
                    if source is None or not source.is_file():
                        continue
                    suffix = source.suffix.lower() if source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else ".png"
                    resource = f"{asset.get('asset_id')}{suffix}"
                    shutil.copyfile(source, images_dir / resource)
                    prepared_assets.append({**asset, "resource": resource})
            finally:
                db.close()
        registered_media_resources = {
            (planning.project_dir / "images" / str(asset["resource"])).resolve()
            for asset in prepared_assets
            if isinstance(asset.get("resource"), str)
        }
        image_slots = build_image_slots(prepared_assets, page_count=page_count)
        if image_slots:
            (planning.project_dir / "image_slots.json").write_text(json.dumps({"slots": image_slots}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        slots_by_index = {int(slot["slide_index"]): slot for slot in image_slots}
        await emit(
            "planning.completed",
            {
                "page_count": page_count,
                "outline": outline,
                "design_summary": planning.design_summary,
            },
        )
        if len(outline) != page_count:
            mismatch = page_count_mismatch_result(page_count, len(outline), 0, 0)
            await emit("validation.completed", mismatch)
            await emit("task.failed", {"code": "page_count_mismatch", "counts": mismatch["errors"]})
            return

        totals = {
            "model_output_count": 0,
            "svg_xml_invalid_count": 0,
            "svg_sanitize_success_count": 0,
            "svg_validation_blocked_count": 0,
            "model_repair_retry_count": 0,
        }
        failed_indices: list[int] = []

        for item in planning.outline:
            index = int(item["index"])
            title = str(item["title"])
            slide_id = f"{task_id}:slide:{index}"
            await emit(
                "slide.started",
                {"slide_id": slide_id, "index": index, "title": title, "status": "started"},
            )
            result = await make_slide(
                project_dir=planning.project_dir,
                task_id=task_id,
                index=index,
                title=title,
                content_brief=str(item.get("content_brief") or title),
                page_count=page_count,
                page_format=page_format,
                design_spec=planning.design_spec,
                user_input=user_input,
                workspace_layouts=workspace_layouts,
                source_context=source_context + (f"\n\nAuthorized image slot (local-only): {json.dumps(slots_by_index[index], ensure_ascii=False)}" if index in slots_by_index else ""),
            )
            if result.svg_path is not None and index in slots_by_index:
                inject_slot_image(result.svg_path, slots_by_index[index])
            for key in totals:
                totals[key] += int(result.metrics.get(key, 0))

            if result.errors or result.svg_path is None:
                failed_indices.append(index)
                failure_payload = {
                    "slide_id": slide_id,
                    "index": index,
                    "title": title,
                    "status": "failed",
                    "errors": result.errors or ["slide_generation_failed"],
                }
                if result.diagnostics:
                    failure_payload["diagnostics"] = result.diagnostics
                await emit(
                    "slide.failed",
                    failure_payload,
                )
                continue

            try:
                db = session_factory()
                try:
                    record = artifacts.register_project_asset(
                        db,
                        owner_user_id=user_id,
                        project_id=project_id,
                        task_id=task_id,
                        real_path=result.svg_path,
                        mime_type=SVG_MIME_TYPE,
                        registered_resources=registered_media_resources,
                    )
                finally:
                    db.close()
            except ArtifactError:
                failed_indices.append(index)
                await emit(
                    "slide.failed",
                    {
                        "slide_id": slide_id,
                        "index": index,
                        "title": title,
                        "status": "failed",
                        "errors": ["preview_registration_failed"],
                    },
                )
                continue

            completed_count += 1
            enforce_directory_quota(planning.project_dir, _PROJECT_MAX_BYTES)
            url = f"/api/v1/files/{record.id}/download"
            await emit(
                "slide.completed",
                {
                    "slide_id": slide_id,
                    "index": index,
                    "title": title,
                    "status": "completed",
                    "preview_file_id": record.id,
                    "preview_url": url,
                    "thumbnail_file_id": record.id,
                    "thumbnail_url": url,
                },
            )

        output_count = totals["model_output_count"]
        totals["svg_validation_block_rate"] = (
            totals["svg_validation_blocked_count"] / output_count if output_count else 0
        )

        if failed_indices or completed_count != page_count:
            validation_result = build_validation_result(
                blocking_errors=["slide_generation_failed"] if failed_indices else ["page_count_mismatch"]
            )
        else:
            validation_result = await validate(planning=planning, page_count=page_count)
        validation_payload = {**validation_result, "metrics": totals}
        await emit("validation.completed", validation_payload)

        if not validation_result.get("passed") or validation_result.get("blocking_errors"):
            await emit(
                "task.failed",
                {
                    "code": "slide_generation_failed" if failed_indices else "page_count_mismatch",
                    "failed_indices": failed_indices,
                    "completed_slide_count": completed_count,
                },
            )
            return

        # Regenerate spec_lock.md with structured sections before export
        if workspace_layouts and layout_assignments:
            from app.PPT_master.structured_spec_lock import build_structured_spec_lock_sections
            from app.PPT_master.planning_layout import to_converter_layout_key
            from pathlib import Path as _P
            converter_keys = [to_converter_layout_key(k) for k in layout_assignments]
            sections = build_structured_spec_lock_sections(layout_assignments=converter_keys)
            spec_lock_path = planning.project_dir / "spec_lock.md"
            if spec_lock_path.exists():
                existing = spec_lock_path.read_text(encoding="utf-8")
                # Append structured sections if not already present
                if "## pptx_masters" not in existing:
                    spec_lock_path.write_text(existing + chr(10) + sections, encoding="utf-8")

        export_state = await export(
            planning=planning,
            page_count=page_count,
            validation_result=validation_result,
        )
        export_slide_count = int(export_state.get("slide_count") or count_pptx_slides(export_state.get("pptx_path", "")))
        if export_slide_count != page_count:
            mismatch = page_count_mismatch_result(page_count, len(planning.outline), completed_count, export_slide_count)
            await emit("validation.completed", {**mismatch, "metrics": totals})
            await emit("task.failed", {"code": "page_count_mismatch", "completed_slide_count": completed_count})
            return
        if not export_state.get("pptx_valid") or not export_state.get("pptx_path"):
            await emit(
                "task.failed",
                {"code": "export_failed", "completed_slide_count": completed_count},
            )
            return

        db = session_factory()
        try:
            pptx_record = artifacts.register_pptx(
                db,
                owner_user_id=user_id,
                project_id=project_id,
                task_id=task_id,
                real_path=export_state["pptx_path"],
            )
            final_file = artifacts.download_payload(
                pptx_record,
                validation_result,
                slide_count=export_slide_count,
            )
        finally:
            db.close()
        await emit("export.ready", {"final_file": final_file})
        await emit("task.completed", {"final_file": final_file})
    except Exception:
        logger.exception("Incremental PPT workflow failed for task %s", task_id)
        try:
            await emit(
                "task.failed",
                {"code": "workflow_failed", "completed_slide_count": completed_count},
            )
        except Exception:
            logger.exception("Could not persist incremental task failure for task %s", task_id)
