"""Tests for guided_generation_adapter projection + chain invocation."""
import asyncio
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from PPT_master import guided_generation_adapter as ga  # noqa: E402


async def _fake_chain(*, task_id, project_id, guided_project_id, user_id, user_input,
                      page_count, page_format, pptx_structure_mode, structured_workspace_id,
                      source_context, sink=None):
    _fake_chain.last = dict(
        task_id=task_id, project_id=project_id, guided_project_id=guided_project_id,
        user_id=user_id, user_input=user_input, page_count=page_count,
        page_format=page_format, pptx_structure_mode=pptx_structure_mode,
        structured_workspace_id=structured_workspace_id, source_context=source_context,
    )
    return task_id


def _structured_result():
    return {
        "audience": "企业高管",
        "communication_intent": "说服",
        "core_message": "降本30%",
        "visual_style": "modern_editorial",
        "presentation_mode": "sectional",
        "reading_mode": "scan",
        "palette": {"background": "#FFF8F0", "foreground": "#3A2E25", "accent": "#E07A3F"},
        "title_family": {"cjk": "Source Han Serif SC", "latin": "Georgia"},
        "body_family": {"cjk": "Source Han Sans SC", "latin": "Calibri"},
        "typography_sizes": {"title": 44, "body": 17, "heading": 30},
        "icon_strategy": "duotone_icons",
        "image_strategy": "controlled_slots: P1-A image_slots only; no_network_fetch; no_ai_generation",
        "chart_strategy": "native_ooxml_chart",
        "table_strategy": "native_ooxml_table",
        "page_rhythm": "accent_beat",
        "pptx_structure_mode": "structured",
        "page_count": 6,
        "image_sources": "controlled",
        "native_chart_policy": "native_ooxml_chart",
        "native_table_policy": "native_ooxml_table",
        "formula_policy": "none",
        "structured_workspace_id": "ws_test_abc",
        "structured_workspace_revision": 3,
        "animation_policy": "none",
        "page_layout": "standard",
    }


def _flat_result():
    r = _structured_result()
    r = dict(r)
    r["pptx_structure_mode"] = "flat"
    r["page_count"] = 4
    r.pop("structured_workspace_id", None)
    r.pop("structured_workspace_revision", None)
    return r


def _fake_guid(result, gp_id="gp-1", revision=2):
    return {
        "result_json": result,
        "confirmed_values_json": {},
        "stage1_json": {},
        "stage2_json": {},
        "stage3_json": {},
        "guided_project_id": gp_id,
        "revision": revision,
    }


def test_structured_projection_maps_correctly(monkeypatch):
    monkeypatch.setattr(ga, "_invoke_chain", _fake_chain)
    tmp = tempfile.mkdtemp()
    task_id = asyncio.run(
        ga.run_guided_generation(_fake_guid(_structured_result()), "proj-1", project_dir=tmp)
    )
    assert task_id.startswith("pptguided_")

    spec = ga._read_spec_kv(os.path.join(tmp, "spec_lock.md"))
    ds = ga._read_spec_kv(os.path.join(tmp, "design_spec.md"))

    # exact page_count
    assert spec["page_count"] == "6"
    # palette
    assert spec["palette.background"] == "#FFF8F0"
    assert spec["palette.foreground"] == "#3A2E25"
    assert spec["palette.accent"] == "#E07A3F"
    # chosen fonts (cjk + latin)
    assert spec["font.title.cjk"] == "Source Han Serif SC"
    assert spec["font.title.latin"] == "Georgia"
    assert spec["font.body.cjk"] == "Source Han Sans SC"
    assert spec["font.body.latin"] == "Calibri"
    # structured mode + workspace id + revision
    assert spec["pptx_structure.mode"] == "structured"
    assert spec["structured_workspace_id"] == "ws_test_abc"
    assert spec["structured_workspace_revision"] == "3"
    # image sources + animation policy
    assert spec["image_sources"] == "controlled"
    assert spec["animation_policy"] == "none"
    # design_spec carries visual style too
    assert ds["visual_style"] == "modern_editorial"
    assert ds["pptx_structure_mode"] == "structured"


def test_flat_mode_has_no_structured_workspace(monkeypatch):
    monkeypatch.setattr(ga, "_invoke_chain", _fake_chain)
    tmp = tempfile.mkdtemp()
    task_id = asyncio.run(
        ga.run_guided_generation(_fake_guid(_flat_result()), "proj-2", project_dir=tmp)
    )
    assert task_id.startswith("pptguided_")

    spec = ga._read_spec_kv(os.path.join(tmp, "spec_lock.md"))
    ds = ga._read_spec_kv(os.path.join(tmp, "design_spec.md"))

    assert spec["page_count"] == "4"
    assert spec["pptx_structure.mode"] == "flat"
    # No structured workspace referenced anywhere
    assert "structured_workspace_id" not in spec
    assert "structured_workspace_revision" not in spec
    assert "structured_workspace_id" not in ds


def test_chain_call_is_the_existing_one(monkeypatch):
    monkeypatch.setattr(ga, "_invoke_chain", _fake_chain)
    tmp = tempfile.mkdtemp()
    tid = asyncio.run(
        ga.run_guided_generation(
            _fake_guid(_structured_result(), gp_id="gp-77"), "proj-9", project_dir=tmp
        )
    )
    assert tid.startswith("pptguided_")
    assert _fake_chain.last["project_id"] == "proj-9"
    assert _fake_chain.last["guided_project_id"] == "gp-77"
    # the real chain entrypoint receives the guided structure parameters
    assert _fake_chain.last["pptx_structure_mode"] == "structured"
    assert _fake_chain.last["structured_workspace_id"] == "ws_test_abc"
    assert "core_message" in _fake_chain.last["source_context"]
