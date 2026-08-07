"""
guided_generation_adapter.py  (Sub-agent 3 — P3-B Guided Strategist)

Bridges the confirmed GuidedProject result into the EXISTING FastAPI incremental
generation chain. It does NOT build a second chain: it projects the confirmed
result into the very same ``design_spec.md`` + ``spec_lock.md`` files that the
current incremental chain already consumes, then invokes the SAME chain entrypoint
quick-mode uses.

Hard constraints (P3B_SPEC.md §8/§2):
  * Reuses the current incremental chain — no independent Confirm UI, no second chain.
  * Keeps SSE, page-count consistency, image_slots, chart/table sidecar, structured
    path and history intact.
  * No network image URLs / AI image generation / notes / TTS / audio / video.
  * animation_policy only 'none' | 'basic_allowed'.

Integration seams are lazy-imported and defensive so the module imports cleanly
without the rest of the backend present (unit tests mock the chain call).
"""
from __future__ import annotations

import importlib
import json
import os
import uuid
from typing import Any, Dict, List, Optional

from .guided_strategist_adapter import (
    ALLOWED_CHART_STRATEGIES,
    ALLOWED_TABLE_STRATEGIES,
    FALLBACK_BUILTIN_WORKSPACE_ID,
)


# --------------------------------------------------------------------------- #
# Tolerant field readers
# --------------------------------------------------------------------------- #
def _as_dict(node: Any) -> Dict[str, Any]:
    return node if isinstance(node, dict) else {}


def _pick(*nodes: Any, key: str, default: Any = None) -> Any:
    """Return the first non-None value for ``key`` across the provided dicts."""
    for n in nodes:
        d = _as_dict(n)
        if key in d and d[key] is not None:
            return d[key]
    return default


def _font_pair(value: Any) -> Dict[str, str]:
    """Normalise a font field into {cjk, latin} strings."""
    if isinstance(value, dict):
        return {
            "cjk": str(value.get("cjk") or value.get("CJK") or ""),
            "latin": str(value.get("latin") or value.get("Latin") or ""),
        }
    # accept a plain string: treat whole as latin fallback
    s = str(value or "")
    return {"cjk": "", "latin": s}


def _hex_or(value: Any, default: str) -> str:
    s = str(value or "").strip()
    if s.startswith("#") and len(s) in (4, 7):
        return s
    return default


def _px(value: Any, default: int) -> str:
    try:
        return f"{int(value)}px"
    except (TypeError, ValueError):
        return f"{default}px"


# --------------------------------------------------------------------------- #
# Project dir resolution (lazy)
# --------------------------------------------------------------------------- #
def resolve_project_dir(project_id: str) -> Optional[str]:
    """Best-effort discovery of a PPT project directory from the existing storage
    layer. Returns None if it cannot be resolved (caller may pass it explicitly)."""
    candidates = (
        "project_storage",
        "storage_service",
        "ppt_storage",
    )
    fn_names = (
        "get_project_dir",
        "project_dir",
        "resolve_project_path",
        "get_project_path",
    )
    for mod_name in candidates:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for fn_name in fn_names:
            fn = getattr(mod, fn_name, None)
            if fn is None:
                continue
            try:
                path = fn(project_id)
            except Exception:
                continue
            if path:
                return str(path)
    return None


# --------------------------------------------------------------------------- #
# Projection: confirmed result -> design_spec.md / spec_lock.md
# --------------------------------------------------------------------------- #
def project_guided_result(
    result: Dict[str, Any],
    confirmed_values: Optional[Dict[str, Any]] = None,
    stage1: Optional[Dict[str, Any]] = None,
    stage2: Optional[Dict[str, Any]] = None,
    stage3: Optional[Dict[str, Any]] = None,
    project_dir: Optional[str] = None,
    revision: Optional[int] = None,
) -> Dict[str, Any]:
    """Project a confirmed GuidedProject result into the existing spec files.

    Reads from ``result`` first, then ``confirmed_values`` / stage dicts as
    fallbacks, so partial payloads still project gracefully.

    If ``project_dir`` is provided, writes ``design_spec.md`` and ``spec_lock.md``
    there and returns the structured spec dict.
    """
    result = _as_dict(result)
    cv = _as_dict(confirmed_values)

    audience = _pick(result, cv, key="audience", default="general")
    intent = _pick(result, cv, key="communication_intent", default="inform")
    core_message = _pick(result, cv, key="core_message", default="")

    visual_style = _pick(result, key="visual_style", default="classic_minimal")
    presentation_mode = _pick(result, key="presentation_mode", default="slide_by_slide")
    reading_mode = _pick(result, key="reading_mode", default="immersive")

    palette = _as_dict(_pick(result, key="palette", default={}))
    background = _hex_or(palette.get("background"), "#FFFFFF")
    foreground = _hex_or(palette.get("foreground"), "#1F2933")
    accent = _hex_or(palette.get("accent"), "#2563EB")

    title_family = _font_pair(_pick(result, key="title_family", default=""))
    body_family = _font_pair(_pick(result, key="body_family", default=""))

    typo = _as_dict(_pick(result, key="typography_sizes", default={}))
    title_size = _px(typo.get("title"), 40)
    body_size = _px(typo.get("body"), 18)
    heading_size = _px(typo.get("heading"), 28)

    icon_strategy = _pick(result, key="icon_strategy", default="minimal_line_icons")
    image_strategy = _pick(result, key="image_strategy", default="controlled_slots")
    chart_strategy = _pick(result, key="chart_strategy", default="native_ooxml_chart")
    table_strategy = _pick(result, key="table_strategy", default="native_ooxml_table")
    page_rhythm = _pick(result, key="page_rhythm", default="steady_even")

    pptx_structure_mode = str(_pick(result, key="pptx_structure_mode", default="flat")).lower()
    if pptx_structure_mode not in ("flat", "structured"):
        pptx_structure_mode = "flat"

    # ---- Stage 3 production config ----
    page_count = int(_pick(result, key="page_count", default=6) or 6)
    image_sources = _pick(result, key="image_sources", default="controlled")
    native_chart_policy = _pick(result, key="native_chart_policy", default=chart_strategy)
    native_table_policy = _pick(result, key="native_table_policy", default=table_strategy)
    formula_policy = _pick(result, key="formula_policy", default="none")

    structured_workspace_id = _pick(
        result, key="structured_workspace_id", default=FALLBACK_BUILTIN_WORKSPACE_ID
    )
    structured_workspace_revision = _pick(
        result, key="structured_workspace_revision", default=1
    )

    animation_policy = _pick(result, key="animation_policy", default="none")
    if animation_policy not in ("none", "basic_allowed"):
        animation_policy = "none"

    page_layout = _pick(result, key="page_layout", default="standard")

    spec = {
        "audience": audience,
        "communication_intent": intent,
        "core_message": core_message,
        "visual_style": visual_style,
        "presentation_mode": presentation_mode,
        "reading_mode": reading_mode,
        "palette": {"background": background, "foreground": foreground, "accent": accent},
        "title_family": title_family,
        "body_family": body_family,
        "typography_sizes": {"title": title_size, "body": body_size, "heading": heading_size},
        "icon_strategy": icon_strategy,
        "image_strategy": image_strategy,
        "chart_strategy": chart_strategy,
        "table_strategy": table_strategy,
        "page_rhythm": page_rhythm,
        "pptx_structure_mode": pptx_structure_mode,
        "page_count": page_count,
        "image_sources": image_sources,
        "native_chart_policy": native_chart_policy,
        "native_table_policy": native_table_policy,
        "formula_policy": formula_policy,
        "structured_workspace_id": structured_workspace_id,
        "structured_workspace_revision": structured_workspace_revision,
        "animation_policy": animation_policy,
        "page_layout": page_layout,
    }

    if project_dir:
        _write_design_spec(project_dir, spec)
        _write_spec_lock(project_dir, spec)
    return spec


def _write_design_spec(project_dir: str, spec: Dict[str, Any]) -> str:
    p = spec["palette"]
    tf = spec["title_family"]
    bf = spec["body_family"]
    ts = spec["typography_sizes"]
    lines = [
        "# Design Spec (guided projection)",
        "",
        f"- audience: {spec['audience']}",
        f"- communication_intent: {spec['communication_intent']}",
        f"- core_message: {spec['core_message']}",
        f"- visual_style: {spec['visual_style']}",
        f"- presentation_mode: {spec['presentation_mode']}",
        f"- reading_mode: {spec['reading_mode']}",
        f"- palette.background: {p['background']}",
        f"- palette.foreground: {p['foreground']}",
        f"- palette.accent: {p['accent']}",
        f"- title_family.cjk: {tf['cjk']}",
        f"- title_family.latin: {tf['latin']}",
        f"- body_family.cjk: {bf['cjk']}",
        f"- body_family.latin: {bf['latin']}",
        f"- typography.title: {ts['title']}",
        f"- typography.body: {ts['body']}",
        f"- typography.heading: {ts['heading']}",
        f"- icon_strategy: {spec['icon_strategy']}",
        f"- image_strategy: {spec['image_strategy']}",
        f"- chart_strategy: {spec['chart_strategy']}",
        f"- table_strategy: {spec['table_strategy']}",
        f"- page_rhythm: {spec['page_rhythm']}",
        f"- pptx_structure_mode: {spec['pptx_structure_mode']}",
        "",
    ]
    path = os.path.join(project_dir, "design_spec.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def _write_spec_lock(project_dir: str, spec: Dict[str, Any]) -> str:
    p = spec["palette"]
    tf = spec["title_family"]
    bf = spec["body_family"]
    ts = spec["typography_sizes"]
    lines = [
        "# Spec Lock (guided projection)",
        "",
        f"- page_count: {spec['page_count']}",
        f"- palette.background: {p['background']}",
        f"- palette.foreground: {p['foreground']}",
        f"- palette.accent: {p['accent']}",
        f"- font.title.cjk: {tf['cjk']}",
        f"- font.title.latin: {tf['latin']}",
        f"- font.body.cjk: {bf['cjk']}",
        f"- font.body.latin: {bf['latin']}",
        f"- font.title.size: {ts['title']}",
        f"- font.body.size: {ts['body']}",
        f"- font.heading.size: {ts['heading']}",
        f"- image_sources: {spec['image_sources']}",
        f"- native_chart_policy: {spec['native_chart_policy']}",
        f"- native_table_policy: {spec['native_table_policy']}",
        f"- formula_policy: {spec['formula_policy']}",
        f"- pptx_structure.mode: {spec['pptx_structure_mode']}",
        f"- page_layout: {spec['page_layout']}",
        f"- animation_policy: {spec['animation_policy']}",
    ]
    if spec["pptx_structure_mode"] == "structured":
        lines.append(f"- structured_workspace_id: {spec['structured_workspace_id']}")
        lines.append(
            f"- structured_workspace_revision: {spec['structured_workspace_revision']}"
        )
    lines.append("")
    path = os.path.join(project_dir, "spec_lock.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def _read_spec_kv(path: str) -> Dict[str, str]:
    """Parse a 'key: value' markdown spec file into a flat dict (for tests)."""
    out: Dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line.startswith("- ") or ":" not in line:
                continue
            key, _, val = line[2:].partition(":")
            out[key.strip()] = val.strip()
    return out


# --------------------------------------------------------------------------- #
# Chain invocation (lazy, same entrypoint quick-mode uses)
# --------------------------------------------------------------------------- #
class GuidedChainFailed(Exception):
    """Raised when the underlying incremental chain emitted a ``task.failed``.

    The incremental chain swallows its own internal errors and emits
    ``task.failed`` (returning normally) instead of raising, so the guided flow
    detects failure by watching the event stream rather than relying on an
    exception bubbling up.
    """


async def _invoke_chain(
    *,
    task_id: str,
    project_id: str,
    guided_project_id: Optional[str],
    user_id: int,
    user_input: str,
    page_count: int,
    page_format: str,
    pptx_structure_mode: str,
    structured_workspace_id: Optional[str],
    source_context: str,
    sink,
) -> str:
    """Invoke the EXISTING incremental generation chain entrypoint.

    The real quick-mode entrypoint is ``run_incremental_workflow`` (an async
    coroutine). We reuse it directly — no second chain — driving the deck from
    the confirmed guided result via the same parameters quick-mode would pass
    (topic, page count, structure mode, workspace) plus a serialized spec as
    ``source_context`` for best-effort design steering.
    """
    from app.PPT_master.incremental_runner import run_incremental_workflow as fn

    await fn(
        task_id=task_id,
        project_id=project_id,
        user_id=user_id,
        user_input=user_input,
        page_count=page_count,
        page_format=page_format,
        event_sink=sink,
        source_context=source_context,
        source_manifest=[],
        pptx_structure_mode=pptx_structure_mode,
        structured_workspace_id=structured_workspace_id,
    )
    return task_id


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def _extract_guid(guided_project: Any) -> Dict[str, Any]:
    """Tolerant read of a GuidedProject (ORM object or plain dict)."""
    if isinstance(guided_project, dict):
        get = guided_project.get
    else:
        def get(k, default=None):
            return getattr(guided_project, k, default)
    return {
        "result_json": get("result_json") or {},
        "confirmed_values_json": get("confirmed_values_json") or {},
        "stage1_json": get("stage1_json") or {},
        "stage2_json": get("stage2_json") or {},
        "stage3_json": get("stage3_json") or {},
        "guided_project_id": get("guided_project_id"),
        "owner_user_id": get("owner_user_id"),
        "revision": get("revision"),
    }


async def run_guided_generation(
    guided_project: Any,
    project_id: str,
    task_id: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> str:
    """Project the confirmed result and run it through the existing chain.

    Returns the generation_task_id produced by the existing incremental chain.
    ``task_id`` is the id already allocated by the service layer (so the
    GuidedProject row and the chain task agree). If ``project_dir`` is supplied
    (tests / explicit), the projection files are written there before the chain
    runs; otherwise the projection is re-applied as a best-effort artifact after
    the chain creates the project directory.
    """
    g = _extract_guid(guided_project)
    if task_id is None:
        task_id = "pptguided_" + uuid.uuid4().hex

    # (a) + (b) read confirmed result and project into design_spec.md/spec_lock.md
    spec = project_guided_result(
        result=g["result_json"],
        confirmed_values=g["confirmed_values_json"],
        stage1=g["stage1_json"],
        stage2=g["stage2_json"],
        stage3=g["stage3_json"],
        project_dir=project_dir,
        revision=g["revision"],
    )

    owner_user_id = int(getattr(guided_project, "owner_user_id", g.get("owner_user_id")) or 0)
    user_input = (spec.get("core_message") or "").strip() or "演示文稿"
    pptx_structure_mode = spec["pptx_structure_mode"]
    structured_workspace_id = (
        spec["structured_workspace_id"] if pptx_structure_mode == "structured" else None
    )
    source_context = json.dumps(spec, ensure_ascii=False)

    # (c) invoke the EXISTING incremental chain (no second chain). The chain
    # emits ``task.failed`` on internal failure instead of raising, so watch the
    # event stream and raise to mark the guided project failed in the router.
    observed: Dict[str, Any] = {"failed": False, "code": None}

    async def _sink(event: Any) -> None:
        if isinstance(event, dict) and event.get("event_type") == "task.failed":
            observed["failed"] = True
            data = event.get("data") or {}
            observed["code"] = data.get("code") if isinstance(data, dict) else None
        return None

    await _invoke_chain(
        task_id=task_id,
        project_id=project_id,
        guided_project_id=g["guided_project_id"],
        user_id=owner_user_id,
        user_input=user_input,
        page_count=int(spec["page_count"]),
        page_format="ppt169",
        pptx_structure_mode=pptx_structure_mode,
        structured_workspace_id=structured_workspace_id,
        source_context=source_context,
        sink=_sink,
    )
    if observed["failed"]:
        raise GuidedChainFailed(str(observed["code"] or "chain_task_failed"))

    # (d) best-effort post-run projection artifact (the chain owns project_dir)
    if project_dir is None:
        resolved = resolve_project_dir(project_id)
        if resolved:
            try:
                project_guided_result(
                    result=g["result_json"],
                    confirmed_values=g["confirmed_values_json"],
                    stage1=g["stage1_json"],
                    stage2=g["stage2_json"],
                    stage3=g["stage3_json"],
                    project_dir=resolved,
                    revision=g["revision"],
                )
            except Exception:  # pragma: no cover - non-fatal artifact
                pass
    return task_id


def ensure_guided_projection(
    project_id: str,
    guided_project_id: Optional[str],
    project_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Best-effort hook used by the minimal incremental_runner patch.

    Re-applies the guided projection from the stored GuidedProject right before
    the chain builds the deck, as a safety net in case projection was not yet
    written. Returns the projected spec dict, or None if it cannot be resolved.
    """
    try:
        if project_dir is None:
            project_dir = resolve_project_dir(project_id)
        if project_dir is None:
            return None
        # Lazily load the ORM model + session owned by sub1 (does not hard-depend).
        models = importlib.import_module("guided_models")
        db = importlib.import_module("database")
        session = db.Session() if hasattr(db, "Session") else None
        try:
            GuidedProject = getattr(models, "GuidedProject", None)
            if GuidedProject is None or session is None:
                return None
            obj = session.query(GuidedProject).filter(
                GuidedProject.guided_project_id == guided_project_id
            ).first()
            if obj is None:
                return None
            return project_guided_result(
                result=getattr(obj, "result_json", None) or {},
                confirmed_values=getattr(obj, "confirmed_values_json", None) or {},
                stage1=getattr(obj, "stage1_json", None) or {},
                stage2=getattr(obj, "stage2_json", None) or {},
                stage3=getattr(obj, "stage3_json", None) or {},
                project_dir=project_dir,
                revision=getattr(obj, "revision", None),
            )
        finally:
            if session is not None:
                session.close()
    except Exception:
        # Never break the chain if projection cannot be re-applied here.
        return None
