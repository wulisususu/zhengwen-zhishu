---
name: long-document-chunking
description: Use when a document request is likely too long for one stable model turn, including manuals, plans, reports, policies, SOPs, specifications, implementation documents, detailed or complete long-form Word content.
---

# Long Document Chunking

Use this skill to prevent long document generation from stopping halfway, losing chapter order, repeating earlier sections, or rendering a partial DOCX as complete.

This skill is an internal generation-control protocol. It must not appear as user-facing content.

The most important rule is low-latency streaming-first: do not wait until the full document, a detailed outline, a local-small-model completion, or a large hidden plan is generated privately before showing content. The first visible output must be the SSE bridge template preface, followed immediately by the first formal body chunk. The private plan is only a lightweight control structure.

## Trigger Conditions

Enable chunked generation when any condition is true:

* the user asks for a manual, plan, report, policy, SOP, specification, SRS, tender, implementation document, technical document, operations manual, or similar formal long document
* the expected document has more than 5 major sections
* the expected body is more than 3000-5000 Chinese characters or words
* the prompt includes terms such as `详细`, `完整`, `全面`, `超详细`, `运维手册`, `实施方案`, `技术文档`, `项目文档`, `制度`, `说明书`, `报告`, `方案`, `SOP`

Do not rely on intuition alone. If the request looks like a formal document and contains multiple chapters, choose chunked generation.

## Summary And Body First

Before any heavy model planning, the user must see a short template preface generated from the current request by the SSE bridge. This preface must not depend on `local_small_model` returning a complete response.

Immediately after the summary, start the formal markdown body. Do not hold the first body chunk behind a detailed outline, full private draft, render task creation, task status query, or tool narration.

The short preface is only a first-paint message. It must be grounded in the current request and must not invent scope. Do not mention regulations, safety compliance, legal requirements, security design, or other topics unless the user explicitly asked for them.

Create the private outline and generation plan only as a concise control map. Do not show it to the user. Do not spend the turn writing long private prose before the user sees body output.

The private outline must include:

* document title
* first-level chapters
* second-level sections
* necessary third-level subsections
* the writing target for each section
* the current cursor

Represent generation state like this:

```json
{
  "outline": [],
  "required_sections": [],
  "current_section": "",
  "completed_sections": [],
  "last_heading": "",
  "last_output_tail": "",
  "chunk_index": 0,
  "is_final_chunk": false,
  "estimated_total_chunks": 0
}
```

The outline may be flattened into strings when a tool schema only accepts string arrays, for example:

```text
1. 系统概述 > 1.1 建设背景 > 目标: 说明运维对象和业务边界
```

## Streaming-First Chunk Loop

Use this loop for long documents:

1. Stream the template preface first.
2. Immediately stream the document title, directory if needed, and the first body chunk.
3. Extract `required_sections` from the current request and create or refine the concise private outline and initial `generation_state` only enough to control the next chunk.
4. After each visible chunk, update `completed_sections`, `current_section`, `last_output_tail`, and `chunk_index` internally.
5. Generate the next chunk from the outline, cursor, completed sections, and `last_output_tail`.
6. Stream that next chunk immediately.
7. Repeat until the cursor reaches the final outline section.
8. Only then call `document_render_docx` with the merged full markdown and final `generation_state`.

Never pre-generate every chunk privately before emitting the body. Never wait for a complete hidden outline before emitting the first body chunk. The user must see useful document content while the long document is being produced.

If the user explicitly lists required chapters after phrases such as `包含`, `包括`, `文档包含`, `需要包含`, or `要求包含`, every listed item is mandatory. Missing mandatory chapters are not a stylistic issue; they are an incomplete document. Patch the private outline before continuing.

For example, an SRS request that lists `项目简介、功能需求、用户角色、数据库设计、系统流程` must include those five visible sections before rendering.

## Chunk Size

Keep each chunk below the model's unstable long-output range.

Default targets:

* first visible body chunk: 300-800 Chinese characters, so the user sees progress quickly
* normal body chunks: 800-1500 Chinese characters
* continuation context: last 200-500 Chinese characters from the already streamed visible body

Prefer ending a chunk at a paragraph or subsection boundary. If a section is too large, split it across chunks while preserving the same heading and cursor internally. The next chunk continues the same section without repeating the heading unless a new planned subsection begins.

## Continuous Chunk Generation

Generate the body by section or chunk.

Every chunk must be planned with:

* compact outline slice, not the full nested outline when that increases latency or prompt size
* completed section list
* current section cursor
* the last 200-500 Chinese characters from the previous output as continuation context

The next chunk must naturally continue after the previous chunk.

Do not:

* hold all chunks until the end
* rewrite previous content
* restart from the title
* repeat already completed sections
* repeat the document `#` title after it has appeared once
* repeat the immediately previous `##` or `###` heading
* skip chapters in the outline
* jump to a conclusion before the final cursor

Headings may reappear only when moving to the next planned section and only in outline order.

## Duplicate Prevention

Long-document chunking must keep a private `last_heading` and recent visible tail.

Before streaming or appending a chunk:

* remove a repeated top-level document title if the document title has already been emitted
* remove a repeated first heading if it matches `last_heading`
* trim any exact overlap between the previous 200-500 Chinese characters and the new chunk start
* if the chunk restarts from an already completed section, discard the restart and prompt/continue from the current cursor
* if the chunk repeats the introduction or first functional section after those sections are completed, skip the duplicate portion and resume from the next incomplete section

Never accept a chunk that begins again with the whole document title and introduction unless no body has been streamed yet.

## User-Facing Stream

The user should experience one continuous document stream.

The visible stream must start quickly:

* the local-small-model short summary must appear first
* if local-small-model is not streaming or is slow, use the already emitted template preface as the first visible summary
* the first document body chunk must follow immediately after the summary
* a private outline may be refined after visible body output has started
* subsequent chunks should append naturally without visible chunk markers

If the whole target is around 10000 Chinese characters, think of it as several invisible ranges such as 0-2500, 2500-5000, 5000-7500, 7500-10000. The exact boundaries are flexible, but each range must be streamed as soon as it is drafted and the next range must continue from the previous tail.

Never show process text such as:

* 下面继续
* 第二段开始
* 由于篇幅限制
* 我将分几次生成
* 未完待续
* 本段结束
* chunk
* cursor
* generation_state
* 分段生成

Only the formal document markdown should be visible after the short summary.

## No Early Ending

For any non-final chunk, do not output ending phrases such as:

* 以上就是完整运维手册
* 本文档到此结束
* 综上所述
* 希望对你有帮助
* 以上内容供参考

Final summary, conclusion, appendix, or closing material is allowed only when the cursor has reached the last outline section.

## Merge Before Rendering

The full markdown body must be complete and internally merged before calling `document_render_docx`.

Never render a DOCX from only the current chunk.

This does not mean hiding all chunks from the user. The visible stream is the source of truth: accumulate the same visible chunks internally into one merged markdown body, then render that merged body at the end.

Before rendering, set final generation state:

```json
{
  "is_final_chunk": true,
  "required_sections": ["all explicitly requested sections"],
  "completed_sections": ["all required sections"],
  "current_section": "done",
  "last_heading": "last visible heading",
  "chunk_index": 3,
  "estimated_total_chunks": 3
}
```

Pass `generation_state` to `document_render_docx` when supported. If the tool stores traces, the generation state must be present there for auditability.

Before rendering, run this internal quality gate:

1. Every `required_sections` item appears as a visible section or clearly equivalent heading.
2. The markdown contains exactly one top-level `#` document title.
3. No adjacent duplicate headings exist.
4. No completed section has been regenerated later in the document.
5. The final body is not ending inside a table, code fence, list, or unfinished sentence.

If any gate fails, continue or repair the markdown before calling `document_render_docx`.

## Recovery

If the model becomes unsure what to write next:

1. Look at `current_section`.
2. Compare it with `completed_sections`.
3. Continue the current section if it is incomplete.
4. Otherwise move to the next outline section.
5. Use `last_output_tail` for continuity.

Do not ask the user whether to continue unless the user explicitly interrupts or changes the request.
