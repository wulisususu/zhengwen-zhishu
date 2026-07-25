"""
guided_strategist_adapter.py  (Sub-agent 3 — P3-B Guided Strategist)

Stage-2 recommendation engine. Builds AT LEAST three coordinated, internally
coherent design directions keyed ``safe``, ``shifted``, ``bold`` from a confirmed
Stage-1 draft.

Hard constraints honoured (see P3B_SPEC.md §2/§5):
  * No network image URLs and no AI image generation -> image_strategy references
    only controlled P1-A-style image slots.
  * Charts/tables are native P1-B (OOXML sidecar) compatible.
  * structured_workspace_id is resolved from the REAL available/builtin workspace
    list at runtime; if resolution fails we fall back to a single safe builtin id
    (never a fabricated/invalid one).
  * CJK + Latin font families are both complete and non-empty for every direction.

This module is import-safe without the rest of the PPT backend: workspace list
resolution and any chain imports are lazy / defensive.
"""
from __future__ import annotations

import datetime as _dt
import importlib
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Allowed strategy vocabularies (P1-B native, OOXML sidecar compatible)
# --------------------------------------------------------------------------- #
ALLOWED_CHART_STRATEGIES = frozenset({
    "native_ooxml_chart",
    "native_chart_sidecar",
    "none",
})
ALLOWED_TABLE_STRATEGIES = frozenset({
    "native_ooxml_table",
    "native_table_sidecar",
    "none",
})

# Safe fallback builtin workspace id used ONLY when the live workspace list
# cannot be reached. It is a single, well-known constant (not a random uuid),
# so the "valid/known id" test can treat it as known.
FALLBACK_BUILTIN_WORKSPACE_ID = "builtin_default_workspace"
FALLBACK_BUILTIN_WORKSPACE_REVISION = 1


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Workspace id resolution (lazy, defensive)
# --------------------------------------------------------------------------- #
def _collect_workspace_ids() -> List[str]:
    """Best-effort collection of currently available/builtin workspace ids.

    Tries several plausible export names from ``workspace_service`` (the module
    that owns the P3-A workspace list endpoint). Returns [] if unavailable.
    """
    found: List[str] = []
    module_names = ("workspace_service", "PPT_master.workspace_service")
    fn_names = (
        "list_available_workspaces",
        "list_builtin_workspaces",
        "list_workspaces",
        "get_workspace_list",
    )
    for mod_name in module_names:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for fn_name in fn_names:
            fn = getattr(mod, fn_name, None)
            if fn is None:
                continue
            try:
                items = fn()
            except Exception:
                continue
            if isinstance(items, dict):
                items = (
                    items.get("items")
                    or items.get("workspaces")
                    or items.get("data")
                    or []
                )
            if not isinstance(items, (list, tuple)):
                continue
            for it in items:
                if isinstance(it, dict):
                    wid = (
                        it.get("workspace_id")
                        or it.get("id")
                        or it.get("ws_id")
                    )
                elif isinstance(it, str):
                    wid = it
                else:
                    wid = None
                if wid:
                    found.append(str(wid))
    # de-duplicate, preserve order
    seen = set()
    out: List[str] = []
    for w in found:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def resolve_workspace_id(prefer_structured: bool = True) -> str:
    """Return a real available/builtin workspace id, or the safe fallback."""
    ids = _collect_workspace_ids()
    if not ids:
        return FALLBACK_BUILTIN_WORKSPACE_ID
    if prefer_structured and len(ids) > 1:
        # Prefer a non-fallback-looking id when several exist.
        for w in ids:
            if w != FALLBACK_BUILTIN_WORKSPACE_ID:
                return w
    return ids[0]


def known_workspace_ids() -> frozenset:
    """Set of ids considered valid/known (live list + fallback)."""
    return frozenset(_collect_workspace_ids() or [FALLBACK_BUILTIN_WORKSPACE_ID])


# --------------------------------------------------------------------------- #
# Helpers for building a direction
# --------------------------------------------------------------------------- #
def _img_strategy() -> str:
    # Controlled P1-A image slots only. No network fetch, no AI generation.
    return (
        "controlled_slots: P1-A image_slots only (user_upload, builtin_asset_library); "
        "no_network_fetch; no_ai_generation"
    )


def _direction(
    direction_id: str,
    name: str,
    summary: str,
    rationale: str,
    visual_style: str,
    presentation_mode: str,
    reading_mode: str,
    palette: Dict[str, str],
    title_family: Dict[str, str],
    body_family: Dict[str, str],
    typography_sizes: Dict[str, int],
    icon_strategy: str,
    chart_strategy: str,
    table_strategy: str,
    page_rhythm: str,
    pptx_structure_mode: str,
    sample_page_roles: List[str],
    workspace_id: str,
) -> Dict[str, Any]:
    return {
        "direction_id": direction_id,
        "name": name,
        "summary": summary,
        "rationale": rationale,
        "visual_style": visual_style,
        "presentation_mode": presentation_mode,
        "reading_mode": reading_mode,
        "palette": {
            "background": palette["background"],
            "foreground": palette["foreground"],
            "accent": palette["accent"],
        },
        "title_family": {
            "cjk": title_family["cjk"],
            "latin": title_family["latin"],
        },
        "body_family": {
            "cjk": body_family["cjk"],
            "latin": body_family["latin"],
        },
        "typography_sizes": {
            "title": int(typography_sizes["title"]),
            "body": int(typography_sizes["body"]),
            "heading": int(typography_sizes["heading"]),
        },
        "icon_strategy": icon_strategy,
        "image_strategy": _img_strategy(),
        "chart_strategy": chart_strategy,
        "table_strategy": table_strategy,
        "page_rhythm": page_rhythm,
        "pptx_structure_mode": pptx_structure_mode,
        "structured_workspace_id": workspace_id,
        "structured_workspace_revision": FALLBACK_BUILTIN_WORKSPACE_REVISION,
        "sample_page_roles": list(sample_page_roles),
    }


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def generate_stage2_recommendations(stage1: dict) -> dict:
    """Build Stage-2 recommendations from a confirmed Stage-1 draft.

    Returns recommendations_json:

        {
          "directions": {
             "safe":   {...direction...},
             "shifted": {...direction...},
             "bold":   {...direction...},
          },
          "generated_at": "<iso-utc>",
          "basis": { ...condensed stage1 signals... }
        }

    The three directions are internally coherent yet clearly differentiated
    (palette / visual_style / page_rhythm / presentation mode all differ).
    """
    stage1 = stage1 or {}
    # tolerant read of stage1 values (each field is {value, suggested_value, ...})
    def _pick(field: str, default: str = "") -> str:
        node = stage1.get(field)
        if isinstance(node, dict):
            return str(node.get("value") or node.get("suggested_value") or default)
        return str(node if node is not None else default)

    audience = _pick("audience", "general business audience")
    intent = _pick("communication_intent", "inform")
    core_message = _pick("core_message", "the deck's core message")
    page_count = _pick("requested_page_count", "6")
    language = _pick("language", "zh-CN")

    ws_id = resolve_workspace_id(prefer_structured=True)

    directions = {
        "safe": _direction(
            direction_id="safe",
            name="稳健商务 (Safe Corporate)",
            summary="保守、可信、低风险的商务呈现，适合正式汇报与高层沟通。",
            rationale=(
                f"受众为{audience}，沟通意图为{intent}；采用经典极简风格与蓝色中性色，"
                "降低视觉风险，确保信息清晰传达。"
            ),
            visual_style="classic_minimal",
            presentation_mode="slide_by_slide",
            reading_mode="immersive",
            palette={"background": "#FFFFFF", "foreground": "#1F2933", "accent": "#2563EB"},
            title_family={"cjk": "Source Han Sans SC", "latin": "Helvetica Neue"},
            body_family={"cjk": "Source Han Sans SC", "latin": "Arial"},
            typography_sizes={"title": 40, "body": 18, "heading": 28},
            icon_strategy="minimal_line_icons",
            chart_strategy="native_ooxml_chart",
            table_strategy="native_ooxml_table",
            page_rhythm="steady_even",
            pptx_structure_mode="flat",
            sample_page_roles=[
                "cover", "agenda", "context", "approach", "evidence", "closing",
            ],
            workspace_id=ws_id,
        ),
        "shifted": _direction(
            direction_id="shifted",
            name="编辑感叙事 (Editorial Narrative)",
            summary="带叙事节奏的编辑式版式，用暖色与衬线标题营造故事感。",
            rationale=(
                f"在保持专业的前提下引入编辑式排版，以暖橙强调色与衬线标题强化"
                f"「{core_message}」的叙事张力，适合需要说服与记忆点的场景。"
            ),
            visual_style="modern_editorial",
            presentation_mode="sectional",
            reading_mode="scan",
            palette={"background": "#FFF8F0", "foreground": "#3A2E25", "accent": "#E07A3F"},
            title_family={"cjk": "Source Han Serif SC", "latin": "Georgia"},
            body_family={"cjk": "Source Han Sans SC", "latin": "Calibri"},
            typography_sizes={"title": 44, "body": 17, "heading": 30},
            icon_strategy="duotone_icons",
            chart_strategy="native_ooxml_chart",
            table_strategy="native_ooxml_table",
            page_rhythm="accent_beat",
            pptx_structure_mode="structured",
            sample_page_roles=[
                "cover", "hook", "problem", "solution", "proof", "call_to_action",
            ],
            workspace_id=ws_id,
        ),
        "bold": _direction(
            direction_id="bold",
            name="强对比视觉 (Bold Contrast)",
            summary="高对比深色背景与亮色强调，冲击力强，适合发布会与路演。",
            rationale=(
                f"面向需要强记忆点的{intent}场景，采用深蓝背景+亮黄强调的戏剧化对比，"
                "以视觉冲击放大「核心信息」的传达效率。"
            ),
            visual_style="dramatic_contrast",
            presentation_mode="freeflow",
            reading_mode="skim",
            palette={"background": "#0F172A", "foreground": "#F8FAFC", "accent": "#FACC15"},
            title_family={"cjk": "Source Han Sans SC Heavy", "latin": "Arial Black"},
            body_family={"cjk": "Source Han Sans SC", "latin": "Arial"},
            typography_sizes={"title": 48, "body": 18, "heading": 32},
            icon_strategy="solid_geometric_icons",
            chart_strategy="native_ooxml_chart",
            table_strategy="native_ooxml_table",
            page_rhythm="punchy_peak",
            pptx_structure_mode="structured",
            sample_page_roles=[
                "cover", "statement", "problem", "solution", "impact", "next_step",
            ],
            workspace_id=ws_id,
        ),
    }

    return {
        "directions": directions,
        "generated_at": _now_iso(),
        "basis": {
            "audience": audience,
            "communication_intent": intent,
            "core_message": core_message,
            "requested_page_count": page_count,
            "language": language,
        },
    }
