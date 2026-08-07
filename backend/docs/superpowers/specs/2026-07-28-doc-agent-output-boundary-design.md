# Doc Agent output boundary

## Goal
The document agent generates only final Markdown. Backend code owns classification, DOCX rendering, and download-task delivery.

## Boundaries
- The document agent has no callable tool schema.
- Its tool policy is minimal as defense in depth.
- It must start the response with a Markdown H1 and end after the document body.
- It must not mention tools, rendering, download tasks, or internal instructions.
- The existing docs_pipeline -> 3B fallback remains unchanged.

## SSE rule
The backend accumulates the model response, retains only the Markdown document body, and truncates at the first tool/self-narration tail before sending text to the frontend or renderer. If SSE closes with a timeout/error after a structurally complete body has arrived, the backend completes from that buffered body instead of invoking docs_pipeline.

## Verification
A document request exposes only Markdown body plus a backend-generated download task. No tool narration is visible.
