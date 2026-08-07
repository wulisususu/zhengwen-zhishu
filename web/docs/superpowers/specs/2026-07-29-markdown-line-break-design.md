# Markdown Body Line-Break Rendering

## Goal

Keep heading hierarchy while preventing ordinary model soft line breaks from becoming visually loose line breaks.

## Design

1. Configure MarkdownIt with standard soft-break semantics: one newline stays within a paragraph; a blank line starts a paragraph.
2. Preserve the existing semantics for headings, lists, tables, code blocks, and explicit Markdown hard breaks.
3. Reduce ordinary paragraph bottom margin from 1.18em to 0.82em. Do not change spacing for headings, lists, or tables.

## Scope

- Do not change the document-agent prompt, model routing, SSE protocol, or DOCX generation flow.
- Do not rewrite stored message data; this change affects client rendering only.
- Do not touch project bin files, create scripts, or restart services.

## Verification

- Consecutive Chinese sentences separated by one newline render as one paragraph.
- Blank-line-separated paragraphs remain distinct with compact visual spacing.
- Headings, unordered and ordered lists, tables, and code blocks render correctly.
