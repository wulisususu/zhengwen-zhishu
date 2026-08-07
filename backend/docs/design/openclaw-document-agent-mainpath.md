# OpenClaw Document Agent Main Path

## Goal

The frontend already separates chat, document, knowledge-base, and PPT entry points. This design only covers the document page. When a request reaches the document page backend path, it is already `document workflow`.

OpenClaw must not decide whether the user is chatting, writing Word, creating PPT, or asking the knowledge base. OpenClaw only orchestrates the document-page user experience: short summary -> full markdown body -> document card -> downloadable task.

The backend is not the planner for the primary path. It only exposes tools, bridges OpenClaw streaming events to the existing SSE contract, and keeps the legacy document workflow as fallback.

Expected user-visible stream:

```text
user
-> token(summary, 2-3 short sentences)
-> token(full markdown body)
-> doc_task(status != error)
-> done
```

The final task must become downloadable through `download_url`.

## Boundaries

### OpenClaw Document Agent

The `doc-gen` skill owns the document workflow:

1. Treat every request arriving from the document page as an already-routed document workflow request.
2. Optionally call `local_small_model` for a short summary or phrasing help only.
3. Stream 2-3 short summary sentences to the user.
4. Continue streaming the complete markdown document body.
5. Call `document_render_docx` with the final markdown body.
6. Poll `document_task_status` or call `download_url` until the task has a usable download URL, or return a non-error task state if rendering is still in progress.
7. Return `task_id`, `status`, `title`, and `download_url` when available.

`local_small_model` must not generate long document bodies.

The original Python document workflow is converted into auxiliary document workflow skills/rules and fallback behavior. It must not run the primary user experience workflow.

### Backend SSE Bridge

`conversations.py` only:

1. Handles the document page request path.
2. Builds the OpenClaw document input.
3. Calls the OpenClaw document agent streaming endpoint.
4. Maps OpenClaw text deltas to existing SSE `token` events.
5. Maps OpenClaw tool results to existing SSE `doc_task` events.
6. Emits `done`.
7. Falls back to the legacy workflow if OpenClaw times out, fails, or returns neither text nor a task.

It must not directly orchestrate DeepSeek + Qwen + task creation as the main path. Do not add Python scripts or Python orchestration functions for the document main workflow.

### Backend Tools

The backend exposes tools for OpenClaw:

- `local_small_model`
- `attachment_parse`
- `document_render_docx`
- `document_task_status`
- `download_url`

`generate_document` is legacy-compatible only. It is not the OpenClaw docgen primary tool because it can create a task that generates the body in the backend.

### Word Formatting Contract

The document body streamed by OpenClaw must be Word-renderer friendly markdown.

Use the `word-formatting` skill together with `doc-gen` for formal Word documents. This formatting contract does not replace the workflow and must not call tools by itself. It only constrains the markdown body that OpenClaw writes before `document_render_docx` is called.

Required markdown shape:

- Use exactly one `#` title.
- Include `## 目录` after the title for formal multi-section documents such as SRS, tenders, reports, plans, and investigation reports.
- Use `##` for chapters and `###` for subsections.
- Use markdown tables for requirements, interface definitions, database schemas, risks, schedules, and responsibility matrices.
- Every markdown table must include a separator row immediately after the header row.
- Do not output loose pipe tables, task-status tables, generated-by footers, data-source/contact metadata, model names, fake download links, or tool-process narration.

The backend renderer may improve fonts, table borders, heading sizes, and the Word TOC field, but it must not become the primary document writer.

### Legacy Workflow

The old `document_agent` and backend document task generation flow remain available only as fallback. Their constraints are archived and converted into auxiliary skills/rules so OpenClaw can reuse policy knowledge without handing planning back to backend Python code.

## Acceptance

1. Source check: `conversations.py` has no `orchestrate_document_reply` dependency.
2. Source check: `openclaw_orchestrator.py` does not contain document dual-model orchestration.
3. Tool check: OpenClaw document tools expose `document_render_docx`, `document_task_status`, and `download_url`.
4. Skill check: `doc-gen/SKILL.md` requires summary -> markdown body -> render docx -> task metadata.
5. Live SSE check:

```text
user -> token -> token -> doc_task(status != error) -> done
```

6. Task check: `document_task_status` eventually returns `download_url`.
