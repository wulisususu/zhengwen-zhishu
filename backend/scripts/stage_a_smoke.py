"""Run the Stage A two-user production smoke test without printing credentials."""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx


def _token(response: httpx.Response) -> str:
    response.raise_for_status()
    payload = response.json()
    token = payload.get("data", {}).get("access_token")
    if not isinstance(token, str) or not token:
        raise AssertionError("registration did not return an access token")
    return token


def _contains_server_path(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return "/home/" in lowered or "\\users\\" in lowered or "real_path" in lowered
    if isinstance(value, dict):
        return any(_contains_server_path(key) or _contains_server_path(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_server_path(item) for item in value)
    return False


async def _read_sse(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    body: dict[str, Any],
    started: asyncio.Event | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    async with client.stream("POST", "/api/v1/ppt-master/generate", headers=headers, json=body) as response:
        if started:
            started.set()
        status = response.status_code
        if status != 200:
            await response.aread()
            return status, events
        event_type = "message"
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
                events.append({"type": event_type, "data": data})
                if event_type in {"done", "fallback"}:
                    break
    return status, events


def _inspect_pptx(path: Path, expected_slides: int) -> dict[str, Any]:
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
    }


async def run(base_url: str, evidence_path: Path, pptx_path: Path) -> dict[str, Any]:
    timeout = httpx.Timeout(960.0, connect=10.0)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        suffix = secrets.token_hex(6)
        username_a = f"stagea_smoke_a_{suffix}"
        username_b = f"stagea_smoke_b_{suffix}"
        password_a = secrets.token_urlsafe(24)
        password_b = secrets.token_urlsafe(24)
        token_a = _token(await client.post("/api/v1/auth/register", json={"username": username_a, "password": password_a}))
        token_b = _token(await client.post("/api/v1/auth/register", json={"username": username_b, "password": password_b}))
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        request_id = f"stagea-{suffix}-primary"
        request_body = {
            "user_input": "一页简洁的人工智能安全概览，包含标题、三项关键原则和结论",
            "page_count": 1,
            "page_format": "ppt169",
            "sources": [],
            "request_id": request_id,
        }

        unauthorized = await client.post("/api/v1/ppt-master/generate", json=request_body)
        invalid_page = await client.post(
            "/api/v1/ppt-master/generate",
            headers=headers_a,
            json={**request_body, "request_id": f"stagea-{suffix}-invalid", "page_count": 13},
        )
        rejected_sources = await client.post(
            "/api/v1/ppt-master/generate",
            headers=headers_a,
            json={**request_body, "request_id": f"stagea-{suffix}-sources", "sources": ["file:///etc/passwd"]},
        )

        started = asyncio.Event()
        began_at = time.monotonic()
        primary_task = asyncio.create_task(_read_sse(client, headers_a, request_body, started))
        await asyncio.wait_for(started.wait(), timeout=10)
        active_duplicate = await client.post("/api/v1/ppt-master/generate", headers=headers_a, json=request_body)
        concurrent = await client.post(
            "/api/v1/ppt-master/generate",
            headers=headers_b,
            json={**request_body, "request_id": f"stagea-{suffix}-concurrent"},
        )
        primary_status, primary_events = await primary_task
        primary_seconds = round(time.monotonic() - began_at, 3)

        terminal = [event for event in primary_events if event["type"] in {"done", "fallback"}]
        if len(terminal) != 1 or terminal[0]["type"] != "done":
            raise AssertionError("primary generation did not finish with exactly one done event")
        done = terminal[0]["data"]

        replay_started = time.monotonic()
        replay_status, replay_events = await _read_sse(client, headers_a, request_body)
        replay_seconds = round(time.monotonic() - replay_started, 3)
        replay_done = [event["data"] for event in replay_events if event["type"] == "done"]

        file_id = done["file_id"]
        download_url = done["download_url"]
        owner_download = await client.get(download_url, headers=headers_a)
        other_download = await client.get(download_url, headers=headers_b)
        anonymous_download = await client.get(download_url)
        owner_download.raise_for_status()
        pptx_path.parent.mkdir(parents=True, exist_ok=True)
        pptx_path.write_bytes(owner_download.content)
        ooxml = _inspect_pptx(pptx_path, expected_slides=1)

        validation = done.get("validation_result") or {}
        result = {
            "http": {
                "unauthenticated_generate": unauthorized.status_code,
                "invalid_page_count": invalid_page.status_code,
                "nonempty_sources": rejected_sources.status_code,
                "active_duplicate": active_duplicate.status_code,
                "concurrent_second_task": concurrent.status_code,
                "primary_stream": primary_status,
                "idempotent_replay": replay_status,
                "owner_download": owner_download.status_code,
                "other_user_download": other_download.status_code,
                "anonymous_download": anonymous_download.status_code,
            },
            "sse_event_types": [event["type"] for event in primary_events],
            "primary_seconds": primary_seconds,
            "replay_seconds": replay_seconds,
            "done_contract": {
                "keys": sorted(done.keys()),
                "file_id": file_id,
                "download_url_shape": download_url == f"/api/v1/files/{file_id}/download",
                "size": done.get("size"),
                "sha256": done.get("sha256"),
                "valid": done.get("valid"),
                "leaks_server_path": _contains_server_path(done),
            },
            "validation": {
                "passed": validation.get("passed"),
                "warnings_count": len(validation.get("warnings") or []),
                "errors_count": len(validation.get("errors") or []),
                "blocking_errors_count": len(validation.get("blocking_errors") or []),
                "consistent_with_valid": bool(done.get("valid"))
                == (validation.get("passed") is True and not validation.get("blocking_errors")),
            },
            "idempotency": {
                "same_file_id": bool(replay_done) and replay_done[0].get("file_id") == file_id,
                "replay_is_faster": replay_seconds < primary_seconds,
            },
            "pptx": {**ooxml, "downloaded_bytes": len(owner_download.content)},
        }

        expected = {
            "unauthenticated_generate": 401,
            "invalid_page_count": 422,
            "nonempty_sources": 422,
            "active_duplicate": 409,
            "concurrent_second_task": 429,
            "primary_stream": 200,
            "idempotent_replay": 200,
            "owner_download": 200,
            "other_user_download": 404,
            "anonymous_download": 401,
        }
        if result["http"] != expected:
            raise AssertionError(f"unexpected HTTP outcomes: {result['http']}")
        assertions = [
            result["done_contract"]["download_url_shape"],
            not result["done_contract"]["leaks_server_path"],
            result["done_contract"]["valid"] is True,
            result["validation"]["consistent_with_valid"],
            result["validation"]["blocking_errors_count"] == 0,
            result["idempotency"]["same_file_id"],
            all(result["pptx"][key] for key in ("zip_integrity", "required_ooxml", "slide_count_matches", "native_editable_shapes")),
        ]
        result["passed"] = all(assertions)
        if not result["passed"]:
            raise AssertionError("one or more smoke assertions failed")

    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
