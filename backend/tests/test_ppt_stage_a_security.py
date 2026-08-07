from pathlib import Path

import pytest
from pydantic import ValidationError

from app.PPT_master.router import PPTGenRequest


def test_generate_request_accepts_only_empty_sources():
    request = PPTGenRequest(
        user_input="季度经营复盘",
        page_count=1,
        page_format="ppt169",
        sources=[],
        request_id="smoke-security-001",
    )
    assert request.sources == []

    for unsafe_source in ("/etc/passwd", "../../data/app.db", "file:///etc/passwd", "http://127.0.0.1/"):
        with pytest.raises(ValidationError) as exc_info:
            PPTGenRequest(
                user_input="季度经营复盘",
                page_count=1,
                page_format="ppt169",
                sources=[unsafe_source],
                request_id="smoke-security-002",
            )
        error = exc_info.value.errors()[0]
        assert error["loc"] == ("sources",)
        assert "disabled" in error["msg"].lower()


def test_generate_request_enforces_stage_a_limits():
    with pytest.raises(ValidationError):
        PPTGenRequest(user_input="x" * 20001, page_count=1, sources=[])
    with pytest.raises(ValidationError):
        PPTGenRequest(user_input="valid topic", page_count=13, sources=[])
    with pytest.raises(ValidationError):
        PPTGenRequest(user_input="valid topic", page_count=1, page_format="letter", sources=[])
    with pytest.raises(ValidationError):
        PPTGenRequest(user_input="valid topic", page_count=1, sources=[], request_id="../bad")


def test_config_loads_runtime_files_from_external_directory(tmp_path: Path, monkeypatch):
    import app.config as app_config

    (tmp_path / ".env").write_text("STAGE_A_TEST_ENV=loaded\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("server:\n  host: 127.0.0.1\n  port: 8000\n", encoding="utf-8")
    monkeypatch.setenv("AI_BOX_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("STAGE_A_TEST_ENV", raising=False)
    app_config._ENV_LOADED = False
    app_config._config = None

    app_config._load_dotenv_if_present()
    assert app_config.os.environ["STAGE_A_TEST_ENV"] == "loaded"
    assert app_config.get_config()["server"]["port"] == 8000


def test_entrypoint_does_not_log_runtime_config_path():
    import run

    source = Path(run.__file__).read_text(encoding="utf-8")
    assert "Loaded environment from {env_path}" not in source
    assert "Runtime environment loaded" in source


@pytest.mark.parametrize(
    ("svg", "expected_code"),
    [
        ("<!DOCTYPE svg><svg xmlns='http://www.w3.org/2000/svg'/>", "svg_dtd_forbidden"),
        ("<!ENTITY x SYSTEM 'file:///etc/passwd'><svg xmlns='http://www.w3.org/2000/svg'/>", "svg_entity_forbidden"),
        ("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "svg_script_forbidden"),
        ("<svg xmlns='http://www.w3.org/2000/svg'><rect onclick='x()'/></svg>", "svg_event_handler_forbidden"),
        ("<svg xmlns='http://www.w3.org/2000/svg'><foreignObject/></svg>", "svg_foreign_object_forbidden"),
        ("<svg xmlns='http://www.w3.org/2000/svg'><image href='https://example.com/a.png'/></svg>", "svg_external_resource_forbidden"),
        ("<svg xmlns='http://www.w3.org/2000/svg'><image href='file:///etc/passwd'/></svg>", "svg_external_resource_forbidden"),
        ("<svg xmlns='http://www.w3.org/2000/svg'><image href='/etc/passwd'/></svg>", "svg_absolute_resource_forbidden"),
        ("<svg xmlns='http://www.w3.org/2000/svg'><image href='C:\\Windows\\win.ini'/></svg>", "svg_absolute_resource_forbidden"),
        ("<svg xmlns='http://www.w3.org/2000/svg'><image href='../secret.png'/></svg>", "svg_resource_traversal_forbidden"),
        ("<svg xmlns='http://www.w3.org/2000/svg'><style>.x{fill:url(http://example.com/x)}</style></svg>", "svg_external_resource_forbidden"),
        ("<svg xmlns='http://www.w3.org/2000/svg'><style>@import 'https://example.com/x.css';</style></svg>", "svg_external_resource_forbidden"),
        ("<?xml-stylesheet href='https://example.com/x.css'?><svg xmlns='http://www.w3.org/2000/svg'/>", "svg_external_resource_forbidden"),
    ],
)
def test_svg_security_gate_rejects_active_and_external_content(tmp_path: Path, svg: str, expected_code: str):
    from app.PPT_master.security import validate_svg_text

    errors = validate_svg_text(svg, project_root=tmp_path)
    assert expected_code in errors


def test_svg_security_gate_accepts_shape_only_svg(tmp_path: Path):
    from app.PPT_master.security import validate_svg_text

    svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1280 720'><rect x='0' y='0' width='10' height='10'/><text x='10' y='20'>safe</text></svg>"
    assert validate_svg_text(svg, project_root=tmp_path) == []


def test_model_svg_inspection_repairs_safe_wrappers_and_entities(tmp_path: Path):
    from app.PPT_master.security import inspect_model_svg_output

    raw = (
        "Here is the slide you requested.\n"
        "```svg\n"
        "<svg xmlns='http://www.w3.org/2000/svg'><text x='10' y='20'>AI & ML</text></svg>\n"
        "```\n"
        "Use it directly."
    )
    result = inspect_model_svg_output(raw, project_root=tmp_path)

    assert result["errors"] == []
    assert result["sanitized"] is True
    assert "&amp;" in result["svg_text"]
    assert "markdown_fence_removed" in result["repairs"]
    assert "outer_text_removed" in result["repairs"]
    assert "xml_entity_escaped" in result["repairs"]


def test_model_svg_inspection_removes_control_characters(tmp_path: Path):
    from app.PPT_master.security import inspect_model_svg_output

    raw = "<svg xmlns='http://www.w3.org/2000/svg'><text x='10' y='20'>Safe\u0001 slide</text></svg>"
    result = inspect_model_svg_output(raw, project_root=tmp_path)

    assert result["errors"] == []
    assert result["sanitized"] is True
    assert "illegal_control_chars_removed" in result["repairs"]
    assert "\u0001" not in result["svg_text"]


def test_model_svg_inspection_reports_truncated_svg_details(tmp_path: Path):
    from app.PPT_master.security import inspect_model_svg_output

    raw = "<svg xmlns='http://www.w3.org/2000/svg'><text x='10' y='20'>broken"
    result = inspect_model_svg_output(raw, project_root=tmp_path)

    assert result["errors"] == ["svg_xml_invalid"]
    assert result["svg_text"] is None
    assert result["diagnostics"][0]["category"] == "truncated_output"
    assert result["diagnostics"][0]["line"] == 1
    assert result["diagnostics"][0]["column"] > 0
    assert result["diagnostics"][0]["snippet"]


def test_svg_directory_rejects_symlink_escape(tmp_path: Path):
    from app.PPT_master.security import validate_svg_directory

    project = tmp_path / "project"
    svg_dir = project / "svg_output"
    svg_dir.mkdir(parents=True)
    outside = tmp_path / "outside.svg"
    outside.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (svg_dir / "page_01.svg").symlink_to(outside)

    errors = validate_svg_directory(project)
    assert "svg_symlink_forbidden" in errors
