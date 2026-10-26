# Basic workflow and T1 policy integration

Goal: preserve all task branches on Windows, retain the deployed f7a8b20 workflow, and connect real policy search, clauses and durable document citations on RK3588.

User-authorized scope (2026-10-26): complete steps 1–3; synchronize the current main baseline before integration. Main is aeee82b and is already an ancestor of all four branches. The latest real integration baseline is feat/basic-integration@f7a8b20.

Architecture: keep the existing Vue HTTP adapter and FastAPI document/review services. Merge T1 into this integration branch; add library browsing/import and validated citation associations to the existing document payload. Preserve source URLs and version/clause IDs; never infer legal status or fabricate an answer. Keep model egress restricted to intranet. Public-policy retrieval remains local-first and respects existing egress controls.

Constraints: preserve user data, isolate acceptance accounts/data, commit on Windows, no GitHub push, no merge into main, no T2/T3 product integration in this phase, no formal issuance. Existing source worktrees remain untouched.

## Task 1 — preserve source branches

- [x] Import verified Git bundle for basic/T1/T2/T3 into the Windows repository.
- [x] Verify every branch includes current main; merge main is a no-op.
- [x] Restore all 66 T2 delivery files and verify manifest SHA256.
- [x] Re-run T2 suite (122 passed, 5 expected failures) and commit the delivery on Windows.
- [x] Export final recovery bundle containing all four branches.

## Task 2 — retain and re-accept the basic workflow

- [x] Run baseline document/auth/material/review/export regression tests.
- [x] Use real HTTP with isolated SQLite and three accounts for create/save/reload/upload/submit/return/resubmit/approve/download, including cross-user and self-review rejection.
- [x] Verify DOCX A4, watermark and saved content.

## Task 3 — integrate T1

- [x] Merge T1, preserving both main-app router registrations; run original policy tests.
- [x] RED: test persisted server-validated citations, version conflicts, owner/status locks, source provenance, and invalid/missing IDs.
- [x] GREEN: store citation IDs with documents and resolve metadata on the server, preserving old documents and policy version history.
- [x] Add authenticated policy totals/detail/clause endpoints needed by the UI without changing current-only search defaults or egress rules.
- [x] RED/GREEN: test HTTP policy methods, explicit errors, selection/removal, account-change protection and query race handling.
- [x] Implement a policy-library panel for live browsing/search, source/clauses and admin import; reuse it to select citations in the draft workbench.
- [x] Run backend suites, frontend full tests, typecheck/build and real browser flows.
- [x] Independent whole-branch review; fix material findings and run regression.

## Task 4 — deploy and verify

- [x] Back up application data using SQLite backup and preserve current release pointers.
- [x] Build an immutable release, verify hashes and imports against a copied database before switching services.
- [x] Keep shared data/config/material paths; keep existing users/passwords.
- [x] Switch only mqw frontend/backend to the verified release and verify public health/login, durable citations and document workflow.
- [x] Record commits, commands, results, known limits and rollback in the acceptance report; export Windows recovery bundle.

Review focus: citation ID forgery, stale policy versions and status, cross-account document access, approved/pending document editing, production egress configuration, source URL safety, stale frontend requests after account changes, storage outside immutable releases, and unchanged original data after deployment.
