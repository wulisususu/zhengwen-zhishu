# PPT Source Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow PPT incremental generation to use explicitly selected, parsed local files and knowledge documents with durable source provenance.

**Architecture:** The frontend sends only selected file/document IDs plus an explicit pending-source policy. The backend validates ownership and parse readiness, builds a bounded per-source context and manifest, persists both on the incremental task, and threads the context through planning and slide generation.

**Tech Stack:** Vue 3, Pinia, TypeScript, FastAPI, SQLAlchemy, Pydantic, pytest, Vitest.

---

### Task 1: Restore dependable PDF parsing

**Files:**
- Modify: `app/services/file_parse_service.py`
- Test: `tests/test_file_parse_service.py`

- [ ] Add a failing test for a PDF text extraction fallback that uses installed Poppler tools without the missing OpenDataLoader runner.
- [ ] Replace the missing-runner dependency with a local `pdftotext`-first parser and retain rendered-page MiniCPM visual analysis for scanned/image pages.
- [ ] Run the focused test and commit the PDF parser change.

### Task 2: Resolve PPT source references on the backend

**Files:**
- Create: `app/PPT_master/source_context.py`
- Modify: `app/PPT_master/incremental_router.py`
- Modify: `app/PPT_master/incremental_store.py`
- Modify: `app/models.py`
- Test: `tests/test_ppt_source_context.py`
- Test: `tests/test_ppt_incremental_api.py`

- [ ] Add failing tests for ownership validation, pending/failed gates, selected-document-only context, fair source allocation, and durable source manifest snapshots.
- [ ] Add request fields `attachment_file_ids`, `knowledge_doc_ids`, and `source_policy`.
- [ ] Build `source_context` and `source_manifest` strictly from selected IDs; persist them with the task.
- [ ] Run focused tests and commit the source contract.

### Task 3: Feed source context into incremental generation

**Files:**
- Modify: `app/PPT_master/incremental_runner.py`
- Modify: `app/PPT_master/state.py`
- Modify: `app/PPT_master/nodes.py`
- Modify: `app/PPT_master/incremental_slides.py`
- Test: `tests/test_ppt_incremental_runner.py`

- [ ] Add failing tests proving source context reaches planning and slide generation prompts.
- [ ] Thread source context/manifest through state, planning, outline, and per-slide generation without changing page-count behavior.
- [ ] Run focused tests and commit.

### Task 4: Add PPT attachment UI and request wiring

**Files:**
- Create: `src/features/ppt-workbench/components/chat/PptSourceAttachments.vue`
- Modify: `src/features/ppt-workbench/components/chat/LandingComposer.vue`
- Modify: `src/features/ppt-workbench/components/chat/ChatPanel.vue`
- Modify: `src/features/ppt-workbench/components/shell/WorkbenchShell.vue`
- Modify: `src/features/ppt-workbench/adapters/PptWorkflowAdapter.ts`
- Modify: `src/features/ppt-workbench/adapters/HttpPptWorkflowAdapter.ts`
- Test: `tests/http-adapter.spec.ts`

- [ ] Add failing adapter and component tests for selected IDs, pending gating, retry/remove, and explicit parsed-only policy.
- [ ] Reuse `/files/upload`, parse polling, and `KnowledgeFilePicker`; retain only IDs/statuses in browser state.
- [ ] Send IDs and policy through the incremental adapter and restore references from task snapshots.
- [ ] Run typecheck, focused tests, and commit.

### Task 5: Integration verification

**Files:**
- Test: `tests/test_ppt_incremental_api.py`
- Test: `tests/test_ppt_incremental_runner.py`
- Test: `tests/http-adapter.spec.ts`

- [ ] Run backend tests, frontend test/typecheck/build, and temporary-port browser flows.
- [ ] Exercise DOCX, image, normal PDF, scanned PDF, XLSX low-fidelity behavior, selected knowledge documents, mixed sources, pending/failed source behavior, deletion, snapshot restoration, and final PPT source references.
- [ ] Commit implementation and report temporary-environment evidence before production deployment.
