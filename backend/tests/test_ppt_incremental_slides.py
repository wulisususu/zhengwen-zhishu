from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


VALID_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1280 720'>"
    "<rect width='1280' height='720' fill='#ffffff'/>"
    "<text x='80' y='120'>Safe slide</text></svg>"
)


async def QUALITY_OK(_project: Path, _svg_path: Path) -> list[str]:
    return []


@pytest.mark.parametrize(
    "raw",
    [
        VALID_SVG,
        f"```svg\n{VALID_SVG}\n```",
        f"Here is the slide:\n```svg\n{VALID_SVG}\n```\nUse it directly.",
        json.dumps({"page": 1, "title": "Safe", "svg": VALID_SVG}),
        json.dumps([{"page": 1, "svg": VALID_SVG}]),
    ],
)
def test_extract_single_svg_accepts_supported_model_forms(raw: str):
    from app.PPT_master.incremental_slides import extract_single_svg

    assert extract_single_svg(raw).startswith("<svg")
    assert extract_single_svg(raw).endswith("</svg>")


def test_extract_single_svg_rejects_non_svg_output():
    from app.PPT_master.incremental_slides import SlideOutputError, extract_single_svg

    with pytest.raises(SlideOutputError):
        extract_single_svg("not an svg")


@pytest.mark.parametrize(
    ("checker_output", "expected"),
    [
        (
            "[ERROR] <text> uses unsupported text property 'dominant-baseline'",
            ["svg_unsupported_text_property:dominant-baseline"],
        ),
        (
            "[ERROR] <rect> uses unsupported inline style property 'box-shadow'",
            ["svg_unsupported_style_property:box-shadow"],
        ),
        (
            "[ERROR] Unsupported visual SVG element(s) for native PPTX export: image",
            ["svg_unsupported_visual_element"],
        ),
    ],
)
def test_quality_checker_output_is_reduced_to_safe_repair_codes(checker_output, expected):
    from app.PPT_master.incremental_slides import _quality_error_codes

    assert _quality_error_codes(checker_output) == expected


def test_outline_extraction_returns_exact_ordered_page_count():
    from app.PPT_master.incremental_slides import extract_outline

    design = """
### Page 1 — Opening
Layout notes
### Page 2: Current State
Layout notes
### Page 3 - Actions
Layout notes
"""
    outline = extract_outline(design, page_count=4, user_input="AI security")
    assert [item["index"] for item in outline] == [1, 2, 3, 4]
    assert [item["title"] for item in outline[:3]] == ["Opening", "Current State", "Actions"]
    assert len({item["title"] for item in outline}) == 4
    assert all(item["content_brief"] for item in outline)


def test_design_summary_redacts_paths_and_external_urls():
    from app.PPT_master.incremental_slides import summarize_design

    summary = summarize_design("Theme from /home/private/config and https://example.com/a.css")
    serialized = str(summary)
    assert "/home/" not in serialized
    assert "https://" not in serialized
    assert "[redacted]" in serialized


def test_invalid_xml_is_retried_and_counted(tmp_path: Path):
    from app.PPT_master.incremental_slides import generate_slide

    outputs = iter(["<svg><text>", VALID_SVG])
    prompts: list[str] = []

    async def model_call(_system: str, prompt: str) -> str:
        prompts.append(prompt)
        return next(outputs)

    result = asyncio.run(
        generate_slide(
            project_dir=tmp_path,
            task_id="pptinc-slide-1",
            index=1,
            title="Opening",
            page_count=2,
            page_format="ppt169",
            design_spec="Safe design",
            user_input="Safe topic",
            model_call=model_call,
            quality_check=QUALITY_OK,
        )
    )

    assert result.errors == []
    assert result.svg_path == tmp_path / "svg_output" / "page_01.svg"
    assert result.svg_path.read_text(encoding="utf-8") == VALID_SVG
    assert result.metrics == {
        "model_output_count": 2,
        "svg_xml_invalid_count": 1,
        "svg_sanitize_success_count": 0,
        "svg_validation_blocked_count": 1,
        "model_repair_retry_count": 1,
    }
    assert "svg_xml_invalid" in prompts[1]


def test_unescaped_ampersand_is_safely_sanitized_without_retry(tmp_path: Path):
    from app.PPT_master.incremental_slides import generate_slide

    amp_svg = VALID_SVG.replace("Safe slide", "AI & ML")
    prompts: list[str] = []

    async def model_call(_system: str, prompt: str) -> str:
        prompts.append(prompt)
        return f"```svg\n{amp_svg}\n```"

    result = asyncio.run(
        generate_slide(
            project_dir=tmp_path,
            task_id="pptinc-slide-amp",
            index=1,
            title="Opening",
            page_count=1,
            page_format="ppt169",
            design_spec="Safe design",
            user_input="Safe topic",
            model_call=model_call,
            quality_check=QUALITY_OK,
        )
    )

    assert result.errors == []
    assert result.metrics == {
        "model_output_count": 1,
        "svg_xml_invalid_count": 0,
        "svg_sanitize_success_count": 1,
        "svg_validation_blocked_count": 0,
        "model_repair_retry_count": 0,
    }
    assert len(prompts) == 1
    assert "&amp;" in result.svg_path.read_text(encoding="utf-8")


def test_control_characters_are_removed_without_retry(tmp_path: Path):
    from app.PPT_master.incremental_slides import generate_slide

    noisy_svg = VALID_SVG.replace("Safe slide", "Safe\u0001slide")

    async def model_call(_system: str, _prompt: str) -> str:
        return noisy_svg

    result = asyncio.run(
        generate_slide(
            project_dir=tmp_path,
            task_id="pptinc-slide-ctrl",
            index=1,
            title="Opening",
            page_count=1,
            page_format="ppt169",
            design_spec="Safe design",
            user_input="Safe topic",
            model_call=model_call,
            quality_check=QUALITY_OK,
        )
    )

    assert result.errors == []
    assert result.metrics["svg_sanitize_success_count"] == 1
    assert "\u0001" not in result.svg_path.read_text(encoding="utf-8")


def test_external_resource_is_blocked_then_repaired(tmp_path: Path):
    from app.PPT_master.incremental_slides import generate_slide

    unsafe = "<svg xmlns='http://www.w3.org/2000/svg'><image href='file:///etc/passwd'/></svg>"
    outputs = iter([unsafe, VALID_SVG])

    async def model_call(_system: str, _prompt: str) -> str:
        return next(outputs)

    result = asyncio.run(
        generate_slide(
            project_dir=tmp_path,
            task_id="pptinc-slide-2",
            index=1,
            title="Opening",
            page_count=1,
            page_format="ppt169",
            design_spec="Safe design",
            user_input="Safe topic",
            model_call=model_call,
            quality_check=QUALITY_OK,
        )
    )
    assert result.errors == []
    assert result.metrics["svg_validation_blocked_count"] == 1
    assert result.metrics["model_repair_retry_count"] == 1
    assert "file://" not in result.svg_path.read_text(encoding="utf-8")


def test_export_incompatible_svg_is_quality_checked_then_repaired(tmp_path: Path):
    from app.PPT_master.incremental_slides import generate_slide

    incompatible = VALID_SVG.replace("<text ", "<text dominant-baseline='middle' ")
    outputs = iter([incompatible, VALID_SVG])
    prompts: list[str] = []

    async def model_call(_system: str, prompt: str) -> str:
        prompts.append(prompt)
        return next(outputs)

    async def quality_check(_project: Path, svg_path: Path) -> list[str]:
        text = svg_path.read_text(encoding="utf-8")
        if "dominant-baseline" in text:
            return ["svg_unsupported_text_property:dominant-baseline"]
        return []

    result = asyncio.run(
        generate_slide(
            project_dir=tmp_path,
            task_id="pptinc-slide-quality",
            index=1,
            title="Opening",
            page_count=1,
            page_format="ppt169",
            design_spec="Safe design",
            user_input="Safe topic",
            model_call=model_call,
            quality_check=quality_check,
        )
    )

    assert result.errors == []
    assert result.metrics["svg_validation_blocked_count"] == 1
    assert result.metrics["model_repair_retry_count"] == 1
    assert "svg_unsupported_text_property:dominant-baseline" in prompts[1]
    assert "dominant-baseline" not in result.svg_path.read_text(encoding="utf-8")


def test_exhausted_repairs_do_not_remove_previous_completed_slide(tmp_path: Path):
    from app.PPT_master.incremental_slides import generate_slide

    svg_dir = tmp_path / "svg_output"
    svg_dir.mkdir()
    first_slide = svg_dir / "page_01.svg"
    first_slide.write_text(VALID_SVG, encoding="utf-8")

    async def model_call(_system: str, _prompt: str) -> str:
        return "<svg><broken>"

    result = asyncio.run(
        generate_slide(
            project_dir=tmp_path,
            task_id="pptinc-slide-3",
            index=2,
            title="Second",
            page_count=2,
            page_format="ppt169",
            design_spec="Safe design",
            user_input="Safe topic",
            model_call=model_call,
            quality_check=QUALITY_OK,
            max_repair_retries=2,
        )
    )

    assert result.svg_path is None
    assert result.errors == ["svg_xml_invalid"]
    assert result.metrics["model_output_count"] == 3
    assert result.metrics["model_repair_retry_count"] == 2
    assert first_slide.read_text(encoding="utf-8") == VALID_SVG
    assert not (svg_dir / "page_02.svg").exists()
