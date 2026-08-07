"""
guided_artifacts.py  (Sub-agent 3 — P3-B Guided Strategist)

Audit-copy artifact writer. The DB is the source of truth; these JSON files under
``<project_dir>/confirm_ui/`` are immutable audit copies only (never parsed back as
truth by the frontend — the frontend calls the API).

Behaviour (P3B_SPEC.md §7):
  * Atomic write: write to a temp file in the same directory, then ``os.replace``.
  * Writes ``recommendations.json`` and ``result.json`` when their payload is given.
  * Optionally writes ``guided_project_snapshot.json``, ``stage1.json``,
    ``stage2.json``, ``stage3.json``.
  * Every file carries ``guided_project_id``, ``revision``, ``id`` (uuid) and
    ``written_at`` (ISO UTC).
  * A write failure is RAISED (never silently swallowed).
  * No secrets and no un-redacted absolute paths are embedded.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from typing import Any, Dict, Optional


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    """Write ``data`` as JSON to ``path`` atomically via temp file + os.replace.

    Raises on any failure (directory creation, serialization, flush, replace).
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    # write to a sibling temp file then atomically replace
    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp", prefix=".art_", dir=directory or "."
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        # clean up the temp file if it still exists
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def _envelope(
    guided_project_id: str,
    revision: int,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "guided_project_id": guided_project_id,
        "revision": revision,
        "id": str(uuid.uuid4()),
        "written_at": _now_iso(),
        **payload,
    }


def write_artifacts(
    project_dir: str,
    guided_project_id: str,
    revision: int,
    recommendations: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    stage1: Optional[Dict[str, Any]] = None,
    stage2: Optional[Dict[str, Any]] = None,
    stage3: Optional[Dict[str, Any]] = None,
    snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Atomically write guided-project audit artifacts under ``confirm_ui/``.

    Returns a mapping of ``artifact_name -> absolute_path`` for everything written.
    Raises (does NOT silently ignore) if any requested write fails.
    """
    if project_dir is None:
        raise ValueError("project_dir is required to write artifacts")
    if not guided_project_id:
        raise ValueError("guided_project_id is required to write artifacts")

    confirm_dir = os.path.join(project_dir, "confirm_ui")
    written: Dict[str, str] = {}

    # (filename, payload) pairs
    targets = [
        ("recommendations.json", recommendations),
        ("result.json", result),
        ("guided_project_snapshot.json", snapshot),
        ("stage1.json", stage1),
        ("stage2.json", stage2),
        ("stage3.json", stage3),
    ]

    for fname, payload in targets:
        if payload is None:
            continue
        path = os.path.join(confirm_dir, fname)
        # envelope wraps the payload under a "data" key to keep envelope fields
        # separate from the business payload.
        data = _envelope(guided_project_id, revision, {"data": payload})
        _atomic_write_json(path, data)
        written[fname] = path

    if not written:
        # Nothing was requested; still create the directory so downstream code
        # finds a consistent location, but do not raise (no failure occurred).
        os.makedirs(confirm_dir, exist_ok=True)

    return written
