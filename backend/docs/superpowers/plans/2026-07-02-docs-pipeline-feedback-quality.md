# Docs Pipeline Feedback Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve docs pipeline user feedback and output quality without optimizing total generation time.

**Architecture:** Keep the existing LangGraph flow. Add backend helpers for chapter numbering and structured hallucination-risk metadata, then wire those helpers into node outputs and final DOCX assembly. Update the standalone frontend so users see immediate progress, chapter-level status, retries, streamed chapter content, and non-invasive risk notes.

**Tech Stack:** Python FastAPI/LangGraph, pytest-style assertions, vanilla HTML/CSS/JavaScript SSE client.

---

### Task 1: Backend Quality Helpers

**Files:**
- Create: `tests/test_docs_pipeline_quality.py`
- Modify: `app/docs_pipeline/core.py`
- Modify: `app/docs_pipeline/nodes.py`

- [x] Write failing tests for non-invasive hallucination guard and numbering normalization.
- [x] Verify failures in the project Python environment.
- [x] Implement helpers that return risk metadata without inserting audit text into content.
- [x] Normalize top-level chapter headings to `第N章 标题` during Markdown assembly.
- [x] Normalize generated subsection headings lacking numeric prefixes to `N.X 标题`.
- [x] Run the backend assertion tests and confirm pass.

### Task 2: Streaming Progress Events

**Files:**
- Modify: `app/docs_pipeline/nodes.py`
- Modify: `app/docs_pipeline/retry.py`

- [x] Add a retry callback to chapter retry logic.
- [x] Push `status` before each chapter starts with chapter index and heading.
- [x] Push `retry` when a chapter attempt fails and the 3B service is restarting.
- [x] Run the backend quality tests again.

### Task 3: Frontend Feedback and Risk Display

**Files:**
- Modify: `app/docs_pipeline/static/app.js`
- Modify: `app/docs_pipeline/static/style.css`

- [x] Set immediate progress text before `fetch` starts.
- [x] Keep generated stage visibly populated while waiting for the first SSE event.
- [x] Render `risk_findings` as a small non-blocking note under the chapter, not inline in正文.
- [x] Update retry/status text handling for chapter-level messages.

### Task 4: Verification

**Files:**
- Verify generated Markdown/DOCX behavior with a short extraction script.

- [x] Run Python compile checks for changed backend modules.
- [x] Run backend assertion tests.
- [x] Run JavaScript syntax check.
- [x] Confirm assembled Markdown has no `[审核标记]` inline text.
- [x] Confirm chapter headings include `第N章` and sixth chapter subsections include `6.X`.
