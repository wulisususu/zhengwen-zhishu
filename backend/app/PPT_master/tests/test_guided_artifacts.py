"""Tests for guided_artifacts (atomic audit-copy writer)."""
import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from PPT_master import guided_artifacts as ga  # noqa: E402


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_atomic_write_creates_files_with_revision_and_id():
    tmp = tempfile.mkdtemp()
    rec_payload = {"directions": {"safe": {}}}
    result_payload = {"page_count": 6}
    written = ga.write_artifacts(
        project_dir=tmp,
        guided_project_id="gp-123",
        revision=7,
        recommendations=rec_payload,
        result=result_payload,
        snapshot={"x": 1},
        stage1={"a": 1},
    )
    # recommendations.json + result.json always; snapshot + stage1 optional provided
    assert os.path.exists(os.path.join(tmp, "confirm_ui", "recommendations.json"))
    assert os.path.exists(os.path.join(tmp, "confirm_ui", "result.json"))
    assert os.path.exists(os.path.join(tmp, "confirm_ui", "guided_project_snapshot.json"))
    assert os.path.exists(os.path.join(tmp, "confirm_ui", "stage1.json"))

    rec = _read(os.path.join(tmp, "confirm_ui", "recommendations.json"))
    assert rec["guided_project_id"] == "gp-123"
    assert rec["revision"] == 7
    assert "id" in rec and rec["id"]
    assert "written_at" in rec
    assert rec["data"] == rec_payload

    res = _read(os.path.join(tmp, "confirm_ui", "result.json"))
    assert res["revision"] == 7 and res["id"]
    assert res["data"] == result_payload


def test_write_failure_raises(monkeypatch):
    tmp = tempfile.mkdtemp()
    # Force os.replace to fail to simulate a write failure.
    def _boom(*a, **k):
        raise OSError("simulated write failure")

    monkeypatch.setattr(ga.os, "replace", _boom)
    try:
        ga.write_artifacts(
            project_dir=tmp,
            guided_project_id="gp-err",
            revision=1,
            recommendations={"d": 1},
        )
    except OSError:
        pass
    else:
        raise AssertionError("write_artifacts must raise on write failure")


def test_invalid_args_raise():
    import pytest

    with pytest.raises(ValueError):
        ga.write_artifacts(project_dir=None, guided_project_id="x", revision=1)
    with pytest.raises(ValueError):
        ga.write_artifacts(project_dir=".", guided_project_id="", revision=1)
