# PPT Backend Stage A Design

## Scope

Stage A only delivers security containment, registered downloads, truthful validation, minimal concurrency protection, deployment hardening, and a controlled one-slide smoke test. It does not add page-level events, cancellation APIs, replay, chat editing, or Dyad workflow features.

## Rollback boundary

- Baseline commit: `e692086acde4fb81b36c12a418580a2f55e2e179` on `main`.
- Baseline tag: `stage-a-baseline-20260717-e692086a`.
- Implementation branch: `codex/stage-a` in a linked worktree outside the deployed tree.
- Backups live under `/home/youyeetoo/.ppt-backend-backups/` with directory mode 700 and file mode 600. Runtime secrets are never copied into the repository or report.
- Deployment is a fast-forward of `main`; rollback restores tracked application code to the baseline tag, restores the SQLite backup only if migration rollback is required, and restarts the recorded launch command.

## Security boundary

The legacy `sources` field remains in the request schema for compatibility but only an empty list is accepted. SVG files pass a fail-closed gate before quality checking and export. The gate rejects DTD/entity declarations, scripts, event handlers, `foreignObject`, external schemes, absolute paths, traversal, and symlink escape. Stage A has no asset registry, so no SVG file resource reference is accepted.

Tracked `.env` and `config.yaml` are removed from the branch. Runtime copies are moved to `~/.config/ai-box/backend/`, mode 600, and exposed to both the hardened and baseline code through ignored symlinks in the deployed tree. The locally controllable JWT secret is rotated during deployment. Third-party keys require provider-console rotation and remain an explicit acceptance blocker until the operator supplies replacements.

## Artifact model and download

The existing `files` table remains the common registry. Additive nullable columns provide the Stage A contract: `owner_user_id`, `project_id`, `task_id`, `real_path`, `mime_type`, `size`, `sha256`, and `expires_at`; existing `user_id`, `filepath`, `filetype`, and `filesize` remain populated for backward compatibility. `ArtifactService` is the only PPT registration path. It verifies the real path is a regular non-symlinked PPTX below the PPT projects root, computes metadata, and applies an expiry.

The existing `/api/v1/files/{file_id}/download` route keeps its path contract. It requires JWT and owner match. Stage A artifact rows additionally require non-expiry and a resolved path below an allowlisted root. No request parameter can supply a filesystem path.

## Validation

`validation_result` has `passed`, `warnings`, `errors`, and `blocking_errors`. SVG security violations, quality-check failure/timeout, converter failure, missing PPTX, invalid ZIP, missing OOXML members, or page-count mismatch are blocking. Export never accepts a partial file. A terminal `done` is emitted only after PPTX validation and artifact registration; otherwise the terminal event is `fallback` with `valid=false` and no path.

## Concurrency and process lifecycle

Uvicorn is temporarily fixed to one worker. A process-wide limiter therefore represents the whole deployment and enforces global=1 and per-user=1. A SQLite `ppt_generation_requests` table persists request IDs and statuses. A duplicate key for the same user never starts a second pipeline: completed requests replay stored terminal artifact metadata, active requests receive a conflict, and keys owned by another user are isolated.

Subprocesses use an async process-group helper. Timeout, cancellation, and abnormal failure terminate the whole group, wait briefly, then force-kill if required. Failed projects are removed after a compact sanitized diagnostic record is written outside the project payload. Limits cover input length, page count, content length, total task time, and per-project/aggregate project bytes.

## Verification

Tests are written first and observed failing before implementation. Unit tests cover sources rejection, SVG security, artifact containment/ownership/expiry, OOXML validation, idempotency, limiter behavior, and process-group timeout cleanup. Deployment verification checks one worker, port 8000, health, an existing authenticated non-PPT endpoint, database schema, and log scanning. Smoke testing uses two temporary registered users and one one-slide generation, followed by owner/non-owner/anonymous download checks and OOXML inspection.
