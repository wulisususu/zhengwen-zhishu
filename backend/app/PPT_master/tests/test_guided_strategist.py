"""Tests for guided_strategist_adapter (Stage-2 recommendations)."""
import os
import sys

# Make the PPT_master package importable without the full backend installed.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from PPT_master.guided_strategist_adapter import (  # noqa: E402
    ALLOWED_CHART_STRATEGIES,
    ALLOWED_TABLE_STRATEGIES,
    generate_stage2_recommendations,
    known_workspace_ids,
)


def _stage1():
    return {
        "audience": {"value": "企业高管", "suggested_value": "企业高管"},
        "communication_intent": {"value": "说服", "suggested_value": "说服"},
        "core_message": {"value": "我们的方案能降本30%", "suggested_value": "我们的方案能降本30%"},
        "requested_page_count": {"value": 6, "suggested_value": 6},
        "language": {"value": "zh-CN"},
    }


def test_three_directions_present():
    rec = generate_stage2_recommendations(_stage1())
    directions = rec["directions"]
    assert set(directions.keys()) >= {"safe", "shifted", "bold"}
    assert len(directions) == 3


def test_directions_coherent_and_differentiated():
    rec = generate_stage2_recommendations(_stage1())
    d = rec["directions"]
    palettes = [tuple(d[k]["palette"].values()) for k in ("safe", "shifted", "bold")]
    visual_styles = [d[k]["visual_style"] for k in ("safe", "shifted", "bold")]
    rhythms = [d[k]["page_rhythm"] for k in ("safe", "shifted", "bold")]
    # All three must differ in palette and visual_style
    assert len(set(palettes)) == 3, "palettes must differ across directions"
    assert len(set(visual_styles)) == 3, "visual_style must differ"
    assert len(set(rhythms)) == 3, "page_rhythm must differ"
    # Each direction must be internally coherent: structure is complete
    for key, direction in d.items():
        for field in (
            "direction_id", "name", "summary", "rationale", "visual_style",
            "presentation_mode", "reading_mode", "palette", "title_family",
            "body_family", "typography_sizes", "icon_strategy", "image_strategy",
            "chart_strategy", "table_strategy", "page_rhythm",
            "pptx_structure_mode", "structured_workspace_id",
            "structured_workspace_revision", "sample_page_roles",
        ):
            assert field in direction, f"{key} missing field {field}"
        assert len(direction["sample_page_roles"]) == 6
        assert direction["pptx_structure_mode"] in ("flat", "structured")


def test_cjk_and_latin_font_families_nonempty():
    rec = generate_stage2_recommendations(_stage1())
    for key, direction in rec["directions"].items():
        assert direction["title_family"]["cjk"], f"{key} title cjk empty"
        assert direction["title_family"]["latin"], f"{key} title latin empty"
        assert direction["body_family"]["cjk"], f"{key} body cjk empty"
        assert direction["body_family"]["latin"], f"{key} body latin empty"


def test_structured_workspace_id_is_valid_known():
    known = known_workspace_ids()
    rec = generate_stage2_recommendations(_stage1())
    for key, direction in rec["directions"].items():
        wsid = direction["structured_workspace_id"]
        assert wsid and isinstance(wsid, str), f"{key} workspace id empty"
        assert wsid in known, f"{key} workspace id {wsid!r} not in known set {known}"
        assert "invalid" not in wsid.lower()
        assert "fabricated" not in wsid.lower()


def test_no_http_in_image_strategy():
    rec = generate_stage2_recommendations(_stage1())
    for key, direction in rec["directions"].items():
        assert "http" not in direction["image_strategy"].lower(), (
            f"{key} image_strategy must not contain a network URL"
        )


def test_chart_table_strategy_from_allowed_set():
    rec = generate_stage2_recommendations(_stage1())
    for key, direction in rec["directions"].items():
        assert direction["chart_strategy"] in ALLOWED_CHART_STRATEGIES, (
            f"{key} chart_strategy not allowed"
        )
        assert direction["table_strategy"] in ALLOWED_TABLE_STRATEGIES, (
            f"{key} table_strategy not allowed"
        )
