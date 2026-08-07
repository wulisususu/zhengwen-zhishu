# Incremental PPT Live Acceptance

Date: 2026-07-21
Release tag: incremental-ppt-frontend-production-20260720
Production commit: 5c03fbb68f4650b1eef3c3f9880e1567e62adf65

## Scope

This acceptance covered the deployed incremental PPT frontend, the production service on port 3000, and the authenticated backend workflow on port 8000. No credentials, tokens, authorization values, server paths, or user-identifying acceptance data are recorded here.

## 8-Page Workflow

A new default eight-page task was submitted through the production browser UI. The received workflow sequence was:

- planning completed and an eight-item outline rendered in the conversation.
- design readiness transitioned through opening into split-workbench; the workbench was present after the transition delay.
- slides 1 through 8 completed incrementally. Each completed slide displayed a real thumbnail and a selectable preview.
- validation completed with score 100 and no blocking issue.
- export became ready and the task completed.
- No Legacy mode or SVG XML validation failure was observed.

The downloaded PPTX passed structural verification:

- Valid ZIP / OOXML package.
- Required content-types and presentation parts present.
- Eight slide XML parts present.
- 358 editable shape nodes and 216 text nodes found.

## Browser Acceptance

- Normal registration and login route succeeded using an isolated temporary ordinary user.
- Production navigation opened the PPT workbench backed by the incremental HTTP workflow.
- Conversation planning, split-workbench, progressive thumbnails, preview, validation, export, and authenticated download rendered correctly.
- A browser reload restored the completed eight-page project, validation state, and download action.
- Chat, document, and knowledge-base navigation loaded successfully; returning to the PPT route restored the same project.
- Browser console: 0 errors and 0 warnings.
- DOM and saved browser artifacts were cleared after acceptance; no credential-bearing screenshots or traces were retained.

## Final State

- Port 3000 returned HTTP 200.
- Backend health returned HTTP 200.
- Port 3001 had no listener.
- The temporary accounts and their workflow tasks/files were removed after validation.


## 2026-07-21 Fullstack Browser Acceptance Update

Final production browser acceptance passed in final-run-04.

- Frontend commit: 626070a
- Backend commit: c8a12d23
- Production tag: fullstack-ppt-browser-acceptance-production-20260721
- Task: pptinc_59a39debc3a04b9891bacec6452b37f6
- SSE: {"planning.started": 1, "planning.completed": 1, "slide.started": 8, "slide.completed": 8, "validation.completed": 1, "export.ready": 1, "task.completed": 1}
- Validation metrics: {"model_output_count": 8, "svg_xml_invalid_count": 0, "svg_sanitize_success_count": 0, "svg_validation_blocked_count": 0, "model_repair_retry_count": 0, "svg_validation_block_rate": 0}
- PPTX SHA-256: 6177bb63a8cdef555bf2c236889ff485d05b4c5de3564df166d5a01e3be8eb26
- Evidence: /home/youyeetoo/INnet_agent/deployment-evidence/fullstack-ppt-acceptance-20260721/final-run-04/
- Cleanup: user_id=234 and its PPT task/file rows removed after evidence copy; backup saved in evidence root.
- Origin: unreachable from deployment server; tag retained locally.
