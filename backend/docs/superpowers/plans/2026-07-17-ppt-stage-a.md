# PPT Backend Stage A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the legacy PPT generator into a minimally production-safe, downloadable, truthfully validated, single-worker service without adding Dyad workflow features.

**Architecture:** Keep the existing FastAPI/LangGraph pipeline and shared SQLite database. Add narrowly scoped security, artifact, validation, subprocess, and admission-control services. Deploy one Uvicorn worker so the process limiter is global for this temporary architecture, while SQLite persists idempotency and artifact metadata.

**Tech Stack:** Python 3.10, FastAPI, Pydantic v2, SQLAlchemy 2, SQLite, LangGraph, OOXML ZIP inspection, pytest.

---

### Task 1: Rollback baseline

**Files:**
- External evidence: `/home/youyeetoo/.ppt-backend-backups/stage-a-20260717-e692086a/`
- Git tag: `stage-a-baseline-20260717-e692086a`

- [ ] Record HEAD, branch, dirty status, process tree, port 8000, launch command, database/configuration hashes.
- [ ] Create a consistent SQLite backup with `sqlite3.Connection.backup()`.
- [ ] Copy only non-secret files that Stage A may modify into the external backup.
- [ ] Create `codex/stage-a` in an external linked worktree without checking out tracked secret files.
- [ ] Run pytest collection and preserve pre-existing collection failures as baseline evidence.

### Task 2: Security commit

**Files:**
- Create: `app/PPT_master/security.py`
- Create: `tests/test_ppt_stage_a_security.py`
- Modify: `app/PPT_master/router.py`
- Modify: `app/PPT_master/nodes.py`
- Modify: `.gitignore`
- Delete from Git: `.env`, `config.yaml`
- Create: `.env.example`, `config.example.yaml`

- [ ] Write request-model tests asserting `sources=[]` passes and local paths, HTTP URLs, and `file://` values produce structured validation errors.
- [ ] Run the tests and verify they fail because non-empty sources are accepted.
- [ ] Write table-driven SVG tests for DTD/entity, script, event attributes, `foreignObject`, HTTP(S), `file:`, absolute paths, traversal, symlink escape, and one safe SVG.
- [ ] Run the tests and verify they fail because the security module does not exist.
- [ ] Implement fail-closed `validate_svg_text()` and `validate_svg_directory()` functions that return sanitized error codes.
- [ ] Constrain user input, page count, page format, request ID, content length, and sources.
- [ ] Invoke the SVG gate before quality checking and export.
- [ ] Add ignore rules and sanitized configuration examples; stage removal of tracked runtime secrets.
- [ ] Run security tests and Python compilation.
- [ ] Commit `security: contain PPT input and SVG resource access`.

### Task 3: Registered artifact download commit

**Files:**
- Create: `app/services/artifact_service.py`
- Create: `tests/test_ppt_stage_a_artifacts.py`
- Modify: `app/models.py`
- Modify: `app/database.py`
- Modify: `app/routers/files.py`
- Modify: `app/PPT_master/runner.py`
- Modify: `app/PPT_master/state.py`

- [ ] Write failing tests for valid registration metadata, outside-root paths, traversal, symlinks, expiry, and cross-user lookup.
- [ ] Add nullable backward-compatible columns to `File` and idempotent additive startup migrations; never rename or drop existing columns.
- [ ] Implement `ArtifactService.register_pptx()`, `get_downloadable()`, and `cleanup_expired()` with realpath containment and regular-file checks.
- [ ] Harden the download route for Stage A artifact records while preserving existing file records.
- [ ] Register validated PPTX output and emit only `file_id`, `download_url`, `size`, `sha256`, `valid`, and `validation_result`.
- [ ] Run artifact/router tests and Python compilation.
- [ ] Commit `file-download: register and authorize PPT artifacts`.

### Task 4: Truthful validation commit

**Files:**
- Create: `app/PPT_master/validation.py`
- Create: `tests/test_ppt_stage_a_validation.py`
- Modify: `app/PPT_master/nodes.py`
- Modify: `app/PPT_master/state.py`

- [ ] Write failing tests for valid OOXML, corrupt ZIP, missing content types, missing presentation XML, missing slides, and expected-page mismatch.
- [ ] Implement `validation_result` and `validate_pptx(path, expected_pages)` using ZIP integrity and OOXML member counts.
- [ ] Populate the same result from SVG security and quality checking.
- [ ] Stop export when blocking errors exist; quality timeout/nonzero is blocking.
- [ ] Delete the partial-export success path. Converter nonzero always fails.
- [ ] Validate final PPTX before `done`; otherwise return fallback with `valid=false` and no path.
- [ ] Run validation/security/artifact tests and Python compilation.
- [ ] Commit `validation: enforce blocking SVG and PPTX checks`.

### Task 5: Minimal concurrency commit

**Files:**
- Create: `app/PPT_master/admission.py`
- Create: `app/PPT_master/subprocesses.py`
- Create: `tests/test_ppt_stage_a_concurrency.py`
- Create: `tests/test_ppt_stage_a_subprocesses.py`
- Modify: `app/models.py`
- Modify: `app/database.py`
- Modify: `app/PPT_master/router.py`
- Modify: `app/PPT_master/runner.py`
- Modify: `app/PPT_master/nodes.py`
- Modify: `run.py`

- [ ] Write failing tests for global=1, per-user=1, duplicate active request, completed replay, user isolation, and subprocess process-tree cleanup.
- [ ] Add `PPTGenerationRequest` with a unique `(user_id, request_id)` constraint.
- [ ] Implement SQLite transitions `accepted/running/completed/failed` and a one-process limiter; acquire admission before returning StreamingResponse.
- [ ] Implement async process-group execution with timeout/cancel TERM, grace, and KILL fallback; replace PPT `subprocess.run` calls.
- [ ] Enforce task timeout and project quotas; sanitize diagnostics and clean failed project payloads.
- [ ] Set `run.py` to one worker and document the global-limit assumption.
- [ ] Run all Stage A tests and selected existing fast tests.
- [ ] Commit `concurrency: serialize PPT generation with SQLite idempotency`.

### Task 6: Migration preflight and deployment

**Files:**
- Runtime configuration: `~/.config/ai-box/backend/`
- Deployment tree: `/home/youyeetoo/INnet_agent/backend`

- [ ] Run migrations against a copy of the baseline SQLite backup; compare table counts, run `PRAGMA integrity_check`, and verify only additive schema changes.
- [ ] Move runtime `.env` and `config.yaml` outside the repository with mode 600; create ignored symlinks compatible with Stage A and baseline code.
- [ ] Rotate the JWT secret without printing it; mark third-party keys pending provider-console rotation.
- [ ] Run Stage A tests, compilation, secret scan, and diff review.
- [ ] Fast-forward `main`, record old PIDs, restart with the recorded environment, and verify one worker.
- [ ] Verify port 8000, health, auth 401, and a non-PPT endpoint.
- [ ] On failure, restore the baseline tag and compatible runtime symlinks, restart, and verify health.

### Task 7: Controlled smoke and report commit

**Files:**
- Create: `STAGE_A_IMPLEMENTATION_REPORT.md`
- Create: `evidence/stage-a-smoke-redacted.json`

- [ ] Register two temporary users through the public API; retain credentials only in process memory.
- [ ] Verify anonymous 401, malformed 422, and non-empty sources rejection.
- [ ] Generate one `ppt169` slide with a unique request ID and record redacted SSE timing.
- [ ] Verify terminal data has no path; owner download succeeds; other-user download is denied; anonymous download is 401.
- [ ] Inspect PPTX ZIP/OOXML for one slide and native DrawingML shapes.
- [ ] Repeat the request ID and verify no second model task/project is created.
- [ ] Hold admission and verify a second request receives an explicit busy/conflict result.
- [ ] Run a synthetic subprocess timeout and verify no descendant remains.
- [ ] Scan logs/evidence for key, JWT, and path values without printing matches.
- [ ] Rehearse rollback non-disruptively by verifying tag, backup, symlink compatibility, and launch command.
- [ ] Write the report and redacted evidence.
- [ ] Commit `smoke-test: verify and document Stage A deployment`.
