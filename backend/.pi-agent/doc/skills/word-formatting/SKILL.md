---
name: word-formatting
description: Use when an OpenClaw document-page agent is writing markdown that will be rendered into a formal Word DOCX, especially reports, SRS documents, tenders, plans, tables, directories, headings, and Chinese business documents.
metadata:
  openclaw:
    role: formatting
    workflow: document
---

# Word Formatting Contract

This skill is a formatting contract for markdown that will be rendered into DOCX. It does not decide workflow routing and does not call tools by itself.

## Structure

Use stable Word-friendly markdown:

* `#` for the document title, exactly once
* `## 目录` after the title for formal multi-section documents
* `##` for chapters
* `###` for subsections
* paragraphs for explanations
* bullet lists for grouped points
* numbered lists for ordered procedures

For SRS, tender, implementation, operation, accident, and analysis documents, prefer complete chapters over short outline-like content.

For long Word documents, coverage is more important than maximal expansion. Do not let early chapters consume the whole output budget. If the user requests many entities, tables, APIs, or modules, first cover all required items with compact Word-friendly sections, then add representative detail.

## Tables

All markdown tables must include a separator row:

```text
| 字段 | 说明 | 约束 |
| --- | --- | --- |
| user_id | 用户标识 | 必填 |
```

Use tables for requirements lists, interface definitions, database schema, risk matrices, schedules, role responsibilities, acceptance criteria, and metric comparison.

Do not use tables for hidden workflow status, tool results, task ids, model names, or download state. Never output `项目 | 值` or `字段 | 值` task-status tables.

Keep each cell short. Put long narrative text before or after the table as normal paragraphs.

For database design documents:

* prefer Word-friendly table-structure tables over long SQL DDL blocks
* list all required business tables before expanding individual table details
* when the user asks for at least N tables, ensure N distinct table names appear in the body
* include index design and sharding/partitioning suggestions when requested
* use SQL code blocks only for representative examples, and always close the code fence before the document ends

## Word Style Expectations

The DOCX renderer will apply Chinese business-document styling:

* body font: Microsoft YaHei, 11pt
* headings: Microsoft YaHei, bold, larger sizes by heading level
* tables: grid style with bold header row
* `## 目录`: converted into a Word TOC field

Write clean markdown and let the renderer handle fonts, sizes, spacing, and table borders.

## Do Not Include

Do not include generated-by footers, contact email, data source, task status, backend/tool messages, fake download links, OpenClaw notes, model names, or implementation/debug details unless the user explicitly asks for them.

The short summary shown before the body is not part of the Word document and must not be sent to the DOCX renderer.
