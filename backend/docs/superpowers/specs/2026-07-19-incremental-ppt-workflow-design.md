# Incremental PPT Workflow Design

## Scope

Add a versioned incremental PPT workflow without changing the externally observable behavior of `POST /api/v1/ppt-master/generate`. The new workflow plans once, generates and registers each slide sequentially, streams durable milestone events, supports owner-scoped task queries, and exports the final editable PPTX through the existing file registry.

The first version deliberately does not add cancellation, replay UI, multi-worker execution, external assets, URL inputs, or arbitrary paths.

## Chosen Architecture

Use an independent endpoint and runner:

- `POST /api/v1/ppt-master/generate-incremental` starts a background coroutine and returns an SSE stream.
- `GET /api/v1/ppt-master/tasks/{task_id}` reads a SQLite task snapshot owned by the authenticated user.
- `PPTIncrementalTask` stores the current snapshot and unique `(user_id, request_id)` identity.
- `PPTIncrementalEvent` stores every event with unique `(task_id, sequence)` ordering.
- `IncrementalTaskStore` is the only component that advances sequence or mutates task snapshots.
- `incremental_runner` reuses project planning, SVG security validation, final validation/export, and `ArtifactService`, but it calls the model once per page.
- The existing single-worker global generation limiter is shared by Legacy and incremental requests.

This isolates compatibility risk. Dual-emitting new events from the Legacy LangGraph was rejected because it would change the frozen stream. A Redis/worker architecture remains the scaling path but is outside this phase.

## Event Contract

SSE event names:

- `planning.started`
- `planning.completed`
- `slide.started`
- `slide.completed`
- `slide.failed`
- `validation.completed`
- `export.ready`
- `task.completed`
- `task.failed`

Every SSE data object has this envelope:

```json
{
  "event_id": "evt_...",
  "event_type": "slide.completed",
  "task_id": "pptinc_...",
  "project_id": "pptproj_...",
  "sequence": 4,
  "timestamp": "2026-07-19T09:00:00.000000Z",
  "data": {}
}
```

Sequence starts at 1, has no gaps, and is committed before the event is offered to the SSE consumer.

`planning.completed.data` contains `page_count`, `outline`, and a bounded design summary. `slide.completed.data` contains `slide_id`, 1-based `index`, `title`, `status`, `preview_file_id`, `preview_url`, `thumbnail_file_id`, and `thumbnail_url`. URLs are `/api/v1/files/{file_id}/download`; the frontend fetches them as authenticated blobs.

`validation.completed.data.metrics` contains:

- `model_output_count`
- `svg_xml_invalid_count`
- `svg_validation_blocked_count`
- `svg_validation_block_rate`
- `model_repair_retry_count`

The block rate denominator is model SVG outputs, including repair outputs.

## Workflow

1. Validate JWT, request size, empty `sources`, idempotency key, quota, and the shared global/user limiter.
2. Reserve logical `task_id` and `project_id`; create the durable task row.
3. Start a producer coroutine. The SSE consumer may disconnect without cancelling the producer.
4. Persist and send `planning.started`.
5. Initialize the controlled project and run the existing strategist planning function without attaching a Legacy event queue.
6. Extract an ordered outline with deterministic fallbacks, then persist/send `planning.completed`.
7. For each page, persist/send `slide.started`, request one SVG, validate XML and security, and retry with explicit error codes up to two times.
8. Atomically save only a valid SVG, register it as an owner-scoped `image/svg+xml` artifact, then persist/send `slide.completed`. If all attempts fail, persist/send `slide.failed` and continue to later pages.
9. Persist/send `validation.completed`. Any failed page or global SVG quality error blocks export, but completed slide artifacts and events remain queryable.
10. If validation passes, use the existing export function, validate OOXML/page count, register the PPTX, then persist/send `export.ready` and `task.completed`.
11. Any unrecoverable error produces one sanitized `task.failed`; no raw model output or filesystem path is persisted in event data.

## Task Query Contract

`GET /api/v1/ppt-master/tasks/{task_id}` returns the existing API success envelope whose `data` contains:

- `task_id`, `project_id`, `request_id`
- `status`, `sequence`, `page_count`
- `completed_slides`
- `current_slide`
- `errors`
- `metrics`
- `final_file`
- `created_at`, `updated_at`

Missing tasks and tasks owned by another user both return 404 to avoid enumeration.

## Artifact Security

Incremental previews use the existing `files` registry, extended with a generic project-asset registration method restricted to `.svg` and `image/svg+xml`. The SVG must already pass the security gate. Download revalidates owner, expiry, allowed root, non-symlink path, suffix/MIME agreement, size, and sha256. No endpoint accepts a path.

The same registered SVG may serve as both preview and thumbnail in v1. It is a real vector rendering of the completed page, not a placeholder or fallback.

## Failure Semantics

- Invalid model output increments metrics and triggers a repair call containing stable error codes, not server details.
- A failed page emits `slide.failed`; later pages continue.
- Completed page files and snapshot entries are not removed by later page or export failure.
- Export requires every requested page and a passing global validation result.
- Task timeout or unexpected exceptions emit `task.failed` and release the shared lease.
- Raw exceptions, prompts, model output, and server paths never enter public events.

## Compatibility

The Legacy endpoint, request model, idempotency table, event names, terminal payload, download contract, and replay semantics remain unchanged. The only shared change is moving the existing limiter instance to `admission.py` so both entrypoints enforce the approved deployment-wide concurrency of one.

## Verification

- Unit tests cover envelope sequence, snapshots, owner isolation, SVG parsing/repair metrics, per-page failure preservation, artifact registration, and Legacy route stability.
- Migration preflight runs twice on a database copy and verifies existing row counts and integrity.
- A real authenticated four-page smoke test proves `planning.completed` precedes all slides, page 1 becomes downloadable before pages 2–4 complete, sequence is continuous, all preview downloads are owner-scoped, and the final PPTX remains editable and downloadable.
- The production log is scanned for secrets and absolute paths after restart.
