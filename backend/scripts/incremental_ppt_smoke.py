"""Run a real four-slide incremental workflow plus Legacy compatibility checks."""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import time
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx


TERMINAL_INCREMENTAL_EVENTS = {"task.completed", "task.failed"}


def _token(response: httpx.Response) -> str:
    response.raise_for_status()
    token = response.json().get("data", {}).get("access_token")
    if not isinstance(token, str) or not token:
        raise AssertionError("registration did not return an access token")
    return token


def _contains_server_path(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return (
            "/home/" in lowered
            or "\\users\\" in lowered
            or "real_path" in lowered
            or "file://" in lowered
        )
    if isinstance(value, dict):
        return any(_contains_server_path(key) or _contains_server_path(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_server_path(item) for item in value)
    return False


def _inspect_svg(content: bytes) -> dict[str, Any]:
    text = content.decode("utf-8")
    root = ElementTree.fromstring(text)
    lowered = text.lower().replace("http://www.w3.org/2000/svg", "")
    return {
        "xml_valid": root.tag.endswith("svg"),
        "has_text": "<text" in lowered,
        "forbidden_resource_absent": not any(
            marker in lowered
            for marker in ("file://", "http://", "https://", "<script", "<!entity", "<!doctype")
        ),
    }


def _inspect_pptx(content: bytes, path: Path, expected_slides: int) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(content)
    path.chmod(0o600)
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        names = set(archive.namelist())
        slide_names = sorted(
            name
            for name in names
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
        slide_xml = b"".join(archive.read(name) for name in slide_names)
    required = {
        "[Content_Types].xml",
        "_rels/.rels",
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
    }
    return {
        "zip_integrity": bad_member is None,
        "required_ooxml": required <= names,
        "slide_count": len(slide_names),
        "slide_count_matches": len(slide_names) == expected_slides,
        "native_editable_shapes": b"<p:sp" in slide_xml and b"<a:t" in slide_xml,
        "downloaded_bytes": len(content),
    }


async def _stream_status(
    client: httpx.AsyncClient,
    path: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    async with client.stream("POST", path, headers=headers, json=body) as response:
        if response.status_code == 200:
            return response.status_code, {}
        await response.aread()
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return response.status_code, payload


async def _read_legacy(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    body: dict[str, Any],
) -> tuple[int, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    async with client.stream(
        "POST", "/api/v1/ppt-master/generate", headers=headers, json=body
    ) as response:
        if response.status_code != 200:
            await response.aread()
            return response.status_code, events
        event_type = "message"
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = json.loads(line.split(":", 1)[1].strip())
                events.append({"type": event_type, "data": payload})
                if event_type in {"done", "fallback"}:
                    break
    return response.status_code, events


async def run(base_url: str, evidence_path: Path, pptx_path: Path) -> dict[str, Any]:
    timeout = httpx.Timeout(960.0, connect=10.0)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        suffix = secrets.token_hex(6)
        credentials = [
            (f"pptinc_smoke_a_{suffix}", secrets.token_urlsafe(24)),
            (f"pptinc_smoke_b_{suffix}", secrets.token_urlsafe(24)),
        ]
        tokens = []
        for username, password in credentials:
            tokens.append(
                _token(
                    await client.post(
                        "/api/v1/auth/register",
                        json={"username": username, "password": password},
                    )
                )
            )
        headers_a = {"Authorization": f"Bearer {tokens[0]}"}
        headers_b = {"Authorization": f"Bearer {tokens[1]}"}
        request_id = f"pptinc-smoke-{suffix}"
        body = {
            "user_input": "四页简洁的企业人工智能治理方案：封面、风险、治理框架、行动计划",
            "page_count": 4,
            "page_format": "ppt169",
            "sources": [],
            "request_id": request_id,
        }

        unauthenticated = await client.post(
            "/api/v1/ppt-master/generate-incremental", json=body
        )
        rejected_sources = await client.post(
            "/api/v1/ppt-master/generate-incremental",
            headers=headers_a,
            json={**body, "request_id": f"pptinc-sources-{suffix}", "sources": ["file:///etc/passwd"]},
        )

        events: list[dict[str, Any]] = []
        planning_snapshot: dict[str, Any] = {}
        first_slide_snapshot: dict[str, Any] = {}
        preview_result: dict[str, Any] = {}
        concurrent_status: int | None = None
        began_at = time.monotonic()
        task_id = ""
        first_slide_elapsed = 0.0

        async with client.stream(
            "POST",
            "/api/v1/ppt-master/generate-incremental",
            headers=headers_a,
            json=body,
        ) as response:
            response.raise_for_status()
            event_type = "message"
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                envelope = json.loads(line.split(":", 1)[1].strip())
                events.append(envelope)
                task_id = envelope["task_id"]

                if event_type == "planning.completed":
                    planning_query = await client.get(
                        f"/api/v1/ppt-master/tasks/{task_id}", headers=headers_a
                    )
                    planning_query.raise_for_status()
                    planning_snapshot = planning_query.json()["data"]
                    concurrent_status, _ = await _stream_status(
                        client,
                        "/api/v1/ppt-master/generate-incremental",
                        headers_b,
                        {**body, "request_id": f"pptinc-concurrent-{suffix}"},
                    )

                if event_type == "slide.completed" and envelope["data"]["index"] == 1:
                    first_slide_elapsed = round(time.monotonic() - began_at, 3)
                    preview_url = envelope["data"]["preview_url"]
                    owner_preview = await client.get(preview_url, headers=headers_a)
                    other_preview = await client.get(preview_url, headers=headers_b)
                    anonymous_preview = await client.get(preview_url)
                    owner_preview.raise_for_status()
                    preview_result = {
                        "owner_status": owner_preview.status_code,
                        "other_status": other_preview.status_code,
                        "anonymous_status": anonymous_preview.status_code,
                        "content_type": owner_preview.headers.get("content-type", "").split(";", 1)[0],
                        **_inspect_svg(owner_preview.content),
                    }
                    query = await client.get(
                        f"/api/v1/ppt-master/tasks/{task_id}", headers=headers_a
                    )
                    query.raise_for_status()
                    first_slide_snapshot = query.json()["data"]

                if event_type in TERMINAL_INCREMENTAL_EVENTS:
                    break

        elapsed = round(time.monotonic() - began_at, 3)
        if not events or events[-1]["event_type"] != "task.completed":
            raise AssertionError("incremental workflow did not complete")

        completed = events[-1]["data"]
        final_file = completed["final_file"]
        owner_download = await client.get(final_file["download_url"], headers=headers_a)
        other_download = await client.get(final_file["download_url"], headers=headers_b)
        anonymous_download = await client.get(final_file["download_url"])
        owner_download.raise_for_status()
        pptx = _inspect_pptx(owner_download.content, pptx_path, expected_slides=4)

        final_query = await client.get(
            f"/api/v1/ppt-master/tasks/{task_id}", headers=headers_a
        )
        other_query = await client.get(
            f"/api/v1/ppt-master/tasks/{task_id}", headers=headers_b
        )
        final_query.raise_for_status()
        final_snapshot = final_query.json()["data"]

        duplicate_started = time.monotonic()
        duplicate_status, duplicate_payload = await _stream_status(
            client,
            "/api/v1/ppt-master/generate-incremental",
            headers_a,
            body,
        )
        duplicate_seconds = round(time.monotonic() - duplicate_started, 3)

        legacy_attempts: list[dict[str, Any]] = []
        legacy_status = 0
        legacy_events: list[dict[str, Any]] = []
        legacy_terminal: dict[str, Any] = {}
        for attempt in range(1, 3):
            legacy_body = {
                "user_input": "一页企业人工智能治理摘要",
                "page_count": 1,
                "page_format": "ppt169",
                "sources": [],
                "request_id": f"pptinc-legacy-{suffix}-{attempt}",
            }
            legacy_status, legacy_events = await _read_legacy(client, headers_a, legacy_body)
            legacy_terminal = legacy_events[-1] if legacy_events else {}
            legacy_attempts.append(
                {
                    "status": legacy_status,
                    "event_types": [event["type"] for event in legacy_events],
                    "terminal_event": legacy_terminal.get("type"),
                }
            )
            if legacy_terminal.get("type") == "done":
                break

    event_types = [event["event_type"] for event in events]
    sequences = [event["sequence"] for event in events]
    completed_indices = [
        event["data"]["index"]
        for event in events
        if event["event_type"] == "slide.completed"
    ]
    expected_types = ["planning.started", "planning.completed"]
    for index in range(1, 5):
        expected_types.extend(["slide.started", "slide.completed"])
    expected_types.extend(["validation.completed", "export.ready", "task.completed"])
    validation = next(
        event["data"] for event in events if event["event_type"] == "validation.completed"
    )
    metrics = validation.get("metrics") or {}
    result = {
        "passed": False,
        "temporary_user_prefix": f"pptinc_smoke_*_{suffix}",
        "task_id": task_id,
        "request_id": request_id,
        "http": {
            "unauthenticated_generate": unauthenticated.status_code,
            "nonempty_sources": rejected_sources.status_code,
            "concurrent_second_task": concurrent_status,
            "owner_preview": preview_result.get("owner_status"),
            "other_preview": preview_result.get("other_status"),
            "anonymous_preview": preview_result.get("anonymous_status"),
            "owner_download": owner_download.status_code,
            "other_download": other_download.status_code,
            "anonymous_download": anonymous_download.status_code,
            "other_task_query": other_query.status_code,
            "duplicate_request": duplicate_status,
            "legacy_generate": legacy_status,
        },
        "events": {
            "types": event_types,
            "sequences": sequences,
            "continuous": sequences == list(range(1, len(sequences) + 1)),
            "exact_order": event_types == expected_types,
            "completed_indices": completed_indices,
            "unique_event_ids": len({event["event_id"] for event in events}) == len(events),
            "leaks_server_path": _contains_server_path(events),
        },
        "planning": {
            "sequence": planning_snapshot.get("sequence"),
            "status": planning_snapshot.get("status"),
            "outline_count": len(planning_snapshot.get("outline") or []),
            "completed_slide_count": len(planning_snapshot.get("completed_slides") or []),
        },
        "first_slide_immediate": {
            "elapsed_seconds": first_slide_elapsed,
            "total_seconds": elapsed,
            "before_task_completed": 0 < first_slide_elapsed < elapsed,
            "snapshot_sequence": first_slide_snapshot.get("sequence"),
            "snapshot_completed_slide_count": len(first_slide_snapshot.get("completed_slides") or []),
            "later_slides_not_completed_yet": len(first_slide_snapshot.get("completed_slides") or []) == 1,
            "preview": preview_result,
        },
        "validation": {
            "passed": validation.get("passed"),
            "blocking_errors_count": len(validation.get("blocking_errors") or []),
            "svg_xml_invalid_count": metrics.get("svg_xml_invalid_count"),
            "svg_validation_blocked_count": metrics.get("svg_validation_blocked_count"),
            "svg_validation_block_rate": metrics.get("svg_validation_block_rate"),
            "model_repair_retry_count": metrics.get("model_repair_retry_count"),
        },
        "final_task": {
            "status": final_snapshot.get("status"),
            "sequence": final_snapshot.get("sequence"),
            "completed_slide_count": len(final_snapshot.get("completed_slides") or []),
            "has_final_file": bool(final_snapshot.get("final_file")),
            "leaks_server_path": _contains_server_path(final_snapshot),
        },
        "idempotency": {
            "duplicate_seconds": duplicate_seconds,
            "existing_task_id_matches": duplicate_payload.get("detail", {}).get("task_id") == task_id,
            "sequence_unchanged": final_snapshot.get("sequence") == sequences[-1],
        },
        "pptx": pptx,
        "legacy": {
            "attempts": legacy_attempts,
            "event_types": [event["type"] for event in legacy_events],
            "terminal_event": legacy_terminal.get("type"),
            "terminal_keys": sorted((legacy_terminal.get("data") or {}).keys()),
            "leaks_server_path": _contains_server_path(legacy_events),
        },
    }

    expected_http = {
        "unauthenticated_generate": 401,
        "nonempty_sources": 422,
        "concurrent_second_task": 429,
        "owner_preview": 200,
        "other_preview": 404,
        "anonymous_preview": 401,
        "owner_download": 200,
        "other_download": 404,
        "anonymous_download": 401,
        "other_task_query": 404,
        "duplicate_request": 409,
        "legacy_generate": 200,
    }
    assertions = {
        "http_contract": result["http"] == expected_http,
        "sequence_continuous": result["events"]["continuous"],
        "event_order": result["events"]["exact_order"],
        "four_slides_completed": result["events"]["completed_indices"] == [1, 2, 3, 4],
        "event_ids_unique": result["events"]["unique_event_ids"],
        "events_hide_paths": not result["events"]["leaks_server_path"],
        "outline_has_four_pages": result["planning"]["outline_count"] == 4,
        "planning_precedes_slides": result["planning"]["completed_slide_count"] == 0,
        "first_slide_precedes_terminal": result["first_slide_immediate"]["before_task_completed"],
        "later_slides_still_running": result["first_slide_immediate"]["later_slides_not_completed_yet"],
        "preview_content_type": result["first_slide_immediate"]["preview"]["content_type"] == "image/svg+xml",
        "preview_xml_valid": result["first_slide_immediate"]["preview"]["xml_valid"],
        "preview_resources_safe": result["first_slide_immediate"]["preview"]["forbidden_resource_absent"],
        "validation_passed": result["validation"]["passed"] is True,
        "validation_not_blocked": result["validation"]["blocking_errors_count"] == 0,
        "task_completed": result["final_task"]["status"] == "completed",
        "snapshot_has_four_slides": result["final_task"]["completed_slide_count"] == 4,
        "snapshot_has_final_file": result["final_task"]["has_final_file"],
        "snapshot_hides_paths": not result["final_task"]["leaks_server_path"],
        "duplicate_points_to_task": result["idempotency"]["existing_task_id_matches"],
        "duplicate_did_not_advance": result["idempotency"]["sequence_unchanged"],
        "pptx_editable_ooxml": all(
            result["pptx"][key]
            for key in ("zip_integrity", "required_ooxml", "slide_count_matches", "native_editable_shapes")
        ),
        "legacy_done": result["legacy"]["terminal_event"] == "done",
        "legacy_hides_paths": not result["legacy"]["leaks_server_path"],
    }
    result["assertions"] = assertions
    result["passed"] = all(assertions.values())

    evidence_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence_path.chmod(0o600)
    if not result["passed"]:
        failed = ",".join(name for name, passed in assertions.items() if not passed)
        raise AssertionError(f"incremental smoke failed: {failed}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--pptx", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.base_url.rstrip("/"), args.evidence, args.pptx))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
