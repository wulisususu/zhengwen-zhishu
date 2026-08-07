# Incremental PPT Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable owner-scoped per-slide PPT event workflow and task query while preserving the frozen Legacy generation API.

**Architecture:** A new incremental router starts an independent background producer that writes every milestone to SQLite before offering it to SSE. A focused task store owns sequence/snapshots, a per-slide generator owns model parsing/security/repair, and the existing planner/export/artifact primitives are reused without dual-emitting through Legacy.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, asyncio SSE, existing GLM client, existing SVG security/export pipeline, pytest.

---

### Task 1: Durable event and task store

**Files:**
- Modify: `app/models.py`
- Create: `app/PPT_master/incremental_store.py`
- Create: `tests/test_ppt_incremental_store.py`

- [ ] **Step 1: Write failing store tests**

```python
def test_event_store_assigns_contiguous_sequence_and_updates_snapshot(db_session):
    store = IncrementalTaskStore()
    store.create_task(db_session, task_id="pptinc_1", project_id="pptproj_1", user_id=1,
                      request_id="incremental-001", page_count=2)
    first = store.append_event(db_session, "pptinc_1", "planning.started", {})
    second = store.append_event(db_session, "pptinc_1", "planning.completed",
                                {"page_count": 2, "outline": [], "design_summary": {}})
    assert [first["sequence"], second["sequence"]] == [1, 2]
    assert store.snapshot(db_session, "pptinc_1", 1)["status"] == "planning_completed"

def test_task_snapshot_preserves_completed_slides_after_later_failure(db_session):
    # append slide.completed for page 1, then slide.failed for page 2
    assert snapshot["completed_slides"][0]["index"] == 1
    assert snapshot["errors"][0]["index"] == 2

def test_task_snapshot_is_owner_scoped(db_session):
    with pytest.raises(IncrementalTaskNotFound):
        store.snapshot(db_session, "pptinc_1", owner_user_id=2)
```

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=. pytest -q tests/test_ppt_incremental_store.py`

Expected: collection fails because the models/store do not exist.

- [ ] **Step 3: Implement the models and store**

Add `PPTIncrementalTask` with unique `(user_id, request_id)` and snapshot JSON fields; add `PPTIncrementalEvent` with unique `(task_id, sequence)`. Implement:

```python
class IncrementalTaskStore:
    def create_task(self, db, *, task_id, project_id, user_id, request_id, page_count): ...
    def find_by_request(self, db, user_id, request_id): ...
    def append_event(self, db, task_id, event_type, data) -> dict: ...
    def snapshot(self, db, task_id, owner_user_id) -> dict: ...
```

`append_event` increments `task.sequence`, creates `evt_<uuid>`, applies the event to the JSON snapshot, commits once, and returns the standard envelope.

- [ ] **Step 4: Run GREEN**

Run: `PYTHONPATH=. pytest -q tests/test_ppt_incremental_store.py`

Expected: all store tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/models.py app/PPT_master/incremental_store.py tests/test_ppt_incremental_store.py
git commit -m "incremental-events: persist task milestones and snapshots"
```

### Task 2: Registered SVG preview artifacts

**Files:**
- Modify: `app/services/artifact_service.py`
- Modify: `tests/test_ppt_stage_a_artifacts.py`

- [ ] **Step 1: Write failing artifact tests**

```python
def test_register_svg_asset_is_owner_scoped_and_integrity_checked(db_session, tmp_path):
    service = ArtifactService(projects_root=tmp_path)
    svg = tmp_path / "pptproj_1" / "svg_output" / "page_01.svg"
    svg.parent.mkdir(parents=True)
    svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'><text>x</text></svg>")
    record = service.register_project_asset(db_session, owner_user_id=1,
        project_id="pptproj_1", task_id="pptinc_1", real_path=svg,
        mime_type="image/svg+xml")
    assert service.get_downloadable(db_session, record.id, 1).sha256
    with pytest.raises(ArtifactNotFoundError):
        service.get_downloadable(db_session, record.id, 2)

def test_register_project_asset_rejects_non_svg_and_symlink(...): ...
```

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=. pytest -q tests/test_ppt_stage_a_artifacts.py -k project_asset`

Expected: fail because `register_project_asset` is absent.

- [ ] **Step 3: Implement minimal generic registration**

Add a strict MIME/suffix map for PPTX and SVG. Register only files under allowed project roots, chmod files to 600/directories to 700, and make `get_downloadable` re-check MIME/suffix, size, sha256, expiry and non-symlink containment for all task artifacts.

- [ ] **Step 4: Run GREEN and full artifact regression**

Run: `PYTHONPATH=. pytest -q tests/test_ppt_stage_a_artifacts.py`

- [ ] **Step 5: Commit**

```bash
git add app/services/artifact_service.py tests/test_ppt_stage_a_artifacts.py
git commit -m "incremental-preview: register safe SVG slide artifacts"
```

### Task 3: Per-slide model parsing, validation and repair

**Files:**
- Create: `app/PPT_master/incremental_slides.py`
- Create: `tests/test_ppt_incremental_slides.py`

- [ ] **Step 1: Write failing parsing and repair tests**

```python
def test_extract_single_svg_accepts_raw_fenced_and_json_forms(): ...

def test_outline_extraction_has_exact_page_count_and_titles(): ...

def test_invalid_xml_is_retried_and_counted(tmp_path):
    outputs = iter(["<svg><text>", VALID_SVG])
    result = asyncio.run(generate_slide(..., model_call=lambda *_: anext(outputs)))
    assert result.metrics["svg_xml_invalid_count"] == 1
    assert result.metrics["model_repair_retry_count"] == 1
    assert result.errors == []

def test_all_repair_attempts_fail_without_deleting_existing_slide(tmp_path): ...
```

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=. pytest -q tests/test_ppt_incremental_slides.py`

Expected: collection fails because the module is absent.

- [ ] **Step 3: Implement minimal slide generator**

Implement `extract_outline`, `design_summary`, `extract_single_svg`, `call_single_slide_model`, and `generate_slide`. The generator performs one initial call plus at most two repair calls, validates with `validate_svg_text`, counts every invalid output, and atomically writes only the valid final SVG.

- [ ] **Step 4: Run GREEN**

Run: `PYTHONPATH=. pytest -q tests/test_ppt_incremental_slides.py`

- [ ] **Step 5: Commit**

```bash
git add app/PPT_master/incremental_slides.py tests/test_ppt_incremental_slides.py
git commit -m "incremental-slides: generate and repair one safe SVG at a time"
```

### Task 4: Incremental runner and event order

**Files:**
- Create: `app/PPT_master/incremental_runner.py`
- Create: `tests/test_ppt_incremental_runner.py`

- [ ] **Step 1: Write failing workflow tests**

```python
def test_four_page_workflow_emits_planning_before_contiguous_slides(...):
    events = asyncio.run(run_fake_incremental_workflow(page_count=4))
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert event_types[:2] == ["planning.started", "planning.completed"]
    assert event_types.index("slide.completed") < event_types.index("task.completed")

def test_page_failure_keeps_first_completed_page_and_continues(...):
    assert [e["data"]["index"] for e in events if e["event_type"] == "slide.started"] == [1, 2, 3]
    assert snapshot["completed_slides"][0]["index"] == 1
    assert terminal["event_type"] == "task.failed"
```

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=. pytest -q tests/test_ppt_incremental_runner.py`

- [ ] **Step 3: Implement the producer**

Implement `run_incremental_workflow` with injected planner/slide/export dependencies for tests. Persist each milestone before queueing it. Register each valid SVG, aggregate metrics, preserve completed files on failure, and register the final PPTX before `export.ready/task.completed`.

- [ ] **Step 4: Run GREEN**

Run: `PYTHONPATH=. pytest -q tests/test_ppt_incremental_runner.py`

- [ ] **Step 5: Commit**

```bash
git add app/PPT_master/incremental_runner.py tests/test_ppt_incremental_runner.py
git commit -m "incremental-runner: stream durable planning and slide milestones"
```

### Task 5: Versioned SSE endpoint, query and shared admission

**Files:**
- Modify: `app/PPT_master/admission.py`
- Modify: `app/PPT_master/router.py`
- Create: `app/PPT_master/incremental_router.py`
- Create: `tests/test_ppt_incremental_api.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_incremental_generate_requires_jwt_empty_sources_and_request_id(client): ...
def test_task_query_hides_other_users_task(client, db_session): ...
def test_incremental_and_legacy_routes_share_one_limiter(): ...
def test_legacy_generate_route_and_terminal_contract_are_unchanged(): ...
```

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=. pytest -q tests/test_ppt_incremental_api.py`

- [ ] **Step 3: Implement router**

Create the new POST/GET endpoints. The POST validates the same limits, rejects duplicate request IDs, acquires the shared limiter, creates a producer task retained in a module-level set, and streams queue events. A done callback releases the lease even if the SSE consumer disconnects. Include the new router from the existing PPT router without changing the Legacy route body.

- [ ] **Step 4: Run GREEN plus all Stage A/Legacy tests**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_ppt_incremental_*.py
PYTHONPATH=. pytest -q tests/test_ppt_stage_a_*.py
PYTHONPATH=. pytest -q tests/test_pi_agent_integration.py tests/test_local_small_model.py
```

- [ ] **Step 5: Commit**

```bash
git add app/PPT_master/admission.py app/PPT_master/router.py \
  app/PPT_master/incremental_router.py tests/test_ppt_incremental_api.py
git commit -m "incremental-api: add owner-scoped SSE tasks and query"
```

### Task 6: Migration, deployment, real evidence and report

**Files:**
- Create: `scripts/incremental_ppt_smoke.py`
- Create: `evidence/incremental-ppt-4-page-redacted.json`
- Create: `INCREMENTAL_PPT_BACKEND_REPORT.md`

- [ ] **Step 1: Run migration twice on a database copy**

Run `init_db()` twice against the copied production database. Verify integrity, all existing table row counts, new tables/constraints, and no removed columns.

- [ ] **Step 2: Run fresh pre-deploy verification**

Run all incremental, Stage A, Legacy quick regression, `py_compile`, `git diff --check`, tracked-secret scan, and report failures honestly.

- [ ] **Step 3: Fast-forward deploy with rollback guard**

Record old PID, stop the service, back up the stopped database, fast-forward `main`, migrate, restart one worker, and verify health/OpenAPI/auth. On failure, run the baseline tag with the pre-deploy database backup.

- [ ] **Step 4: Run authenticated real four-page smoke**

Create two temporary ordinary users through normal auth. Verify continuous standard events, `planning.completed` before slide events, page 1 owner preview download before pages 2–4 complete, other-user 404, final PPTX OOXML/editability/download, task query, and unchanged Legacy one-page generation/idempotent download.

- [ ] **Step 5: Write evidence and report**

The JSON evidence contains only IDs, timings, status codes, event types/sequences, hashes and booleans. The report contains API/event contracts, schema, test evidence, Legacy compatibility, deployment and rollback; it contains no token or server path.

- [ ] **Step 6: Clean temporary users and commit**

Back up smoke artifacts outside the project, delete only test-created users/task/event/file rows and controlled project directories, then commit:

```bash
git add scripts/incremental_ppt_smoke.py evidence/incremental-ppt-4-page-redacted.json \
  INCREMENTAL_PPT_BACKEND_REPORT.md
git commit -m "incremental-smoke: verify four-page progressive workflow"
```
