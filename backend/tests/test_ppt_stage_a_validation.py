from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


def _write_pptx(
    path: Path,
    slide_count: int = 1,
    omit: set[str] | None = None,
    overrides: dict[str, str] | None = None,
) -> Path:
    omit = omit or set()
    members = {
        "[Content_Types].xml": "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>",
        "_rels/.rels": "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'/>",
        "ppt/presentation.xml": "<p:presentation xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'/>",
        "ppt/_rels/presentation.xml.rels": "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'/>",
    }
    for index in range(1, slide_count + 1):
        members[f"ppt/slides/slide{index}.xml"] = (
            "<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' "
            "xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'>"
            "<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>editable</a:t></a:r></a:p>"
            "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
        )
    members.update(overrides or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, text in members.items():
            if name not in omit:
                archive.writestr(name, text)
    return path


def test_validation_result_distinguishes_warning_error_and_blocking():
    from app.PPT_master.validation import build_validation_result

    warning_only = build_validation_result(warnings=["font_fallback"])
    assert warning_only == {
        "passed": True,
        "warnings": ["font_fallback"],
        "errors": [],
        "blocking_errors": [],
    }
    assert build_validation_result(errors=["content_error"])["passed"] is False
    assert build_validation_result(blocking_errors=["unsafe_svg"])["passed"] is False


def test_validate_pptx_accepts_complete_expected_page_count(tmp_path: Path):
    from app.PPT_master.validation import validate_pptx

    result = validate_pptx(_write_pptx(tmp_path / "valid.pptx", slide_count=2), expected_pages=2)
    assert result["passed"] is True
    assert result["errors"] == []
    assert result["blocking_errors"] == []


def test_validate_pptx_rejects_corrupt_zip(tmp_path: Path):
    from app.PPT_master.validation import validate_pptx

    path = tmp_path / "corrupt.pptx"
    path.write_bytes(b"not-a-zip")
    result = validate_pptx(path, expected_pages=1)
    assert result["passed"] is False
    assert "pptx_zip_invalid" in result["blocking_errors"]


@pytest.mark.parametrize(
    ("missing_member", "expected_code"),
    [
        ("[Content_Types].xml", "pptx_content_types_missing"),
        ("_rels/.rels", "pptx_package_relationships_missing"),
        ("ppt/presentation.xml", "pptx_presentation_missing"),
        ("ppt/_rels/presentation.xml.rels", "pptx_presentation_relationships_missing"),
        ("ppt/slides/slide1.xml", "pptx_slides_missing"),
    ],
)
def test_validate_pptx_rejects_missing_required_members(tmp_path: Path, missing_member: str, expected_code: str):
    from app.PPT_master.validation import validate_pptx

    path = _write_pptx(tmp_path / "missing.pptx", omit={missing_member})
    result = validate_pptx(path, expected_pages=1)
    assert result["passed"] is False
    assert expected_code in result["blocking_errors"]


def test_validate_pptx_rejects_page_count_mismatch(tmp_path: Path):
    from app.PPT_master.validation import validate_pptx

    result = validate_pptx(_write_pptx(tmp_path / "mismatch.pptx", slide_count=1), expected_pages=2)
    assert result["passed"] is False
    assert "pptx_page_count_mismatch" in result["blocking_errors"]


def test_validate_pptx_rejects_invalid_required_xml(tmp_path: Path):
    from app.PPT_master.validation import validate_pptx

    path = _write_pptx(
        tmp_path / "invalid-xml.pptx",
        overrides={"ppt/presentation.xml": "<broken"},
    )
    result = validate_pptx(path, expected_pages=1)
    assert result["passed"] is False
    assert "pptx_xml_invalid" in result["blocking_errors"]
