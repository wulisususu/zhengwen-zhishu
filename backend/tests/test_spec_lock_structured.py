"""Test spec_lock structured section generation."""
import pytest
from app.PPT_master.nodes import _build_default_spec_lock


def test_spec_lock_flat_mode_default():
    """Default spec_lock uses flat mode."""
    spec = _build_default_spec_lock()
    assert "## pptx_structure" in spec
    assert "mode: flat" in spec
    assert "workspace_id" not in spec


def test_spec_lock_structured_mode():
    """Structured mode includes template_adherence."""
    spec = _build_default_spec_lock(
        pptx_structure_mode="structured",
        structured_workspace_id="ws_test_123"
    )
    assert "## pptx_structure" in spec
    assert "mode: structured" in spec
    assert "template_adherence: adaptive" in spec


def test_spec_lock_structured_mode_requires_workspace_id():
    """Structured mode without workspace_id raises error."""
    with pytest.raises(ValueError, match="workspace_id.*required"):
        _build_default_spec_lock(pptx_structure_mode="structured")
