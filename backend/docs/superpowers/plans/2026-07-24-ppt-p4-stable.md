# PPT P4 Stable Implementation Plan

> **For agentic workers:** Execute inline with review checkpoints; native Codex agents may provide independent audits, but Superpowers multi-agent orchestration is intentionally not used.

**Goal:** Release the P4 object-animation stable build only after contract, OOXML, P2-B, regression, review, deployment, and browser gates pass.

**Architecture:** The backend owns the five-effect entrance-only matrix and rejects unsupported values; the web adapter renders only that matrix. Editor export resolves explicit editor element IDs to stable PPTX shape IDs and passes a manifest to the native converter. Tests and a committed OOXML detector prove the exported package rather than trusting UI state.

**Actual baseline:** Backend production HEAD `4111a46` (one commit after hotfix tag `136c0760`); web production HEAD `22ebfc9` (the requested hotfix tag does not exist). Stable branches start from these verified production SHAs.

## P1 — production red tests and contract baseline

- [ ] Replace the three stale/miswritten P4 test assertions with policy assertions: the five entrance effects are exactly supported; emphasis and exit are empty; a constructed `exit/fade` object is rejected by service validation.
- [ ] Run the P4 API and target test files with the reusable P2-B virtualenv. Record the original two-red/three-red provenance and require zero failures before advancing.
- [ ] Commit the red-test repair independently.

## P2 — source-of-truth support and explicit export

- [ ] Locate the real editor export seam, converter effect map, HTTP exception mapping, and web animation API/store/panel in the stable worktrees.
- [ ] Add failing backend and web tests for `fade_out`, `pulse`, and `disappear`; require 422 `unsupported_animation_effect`, no fallback mapping, and no unsupported UI option.
- [ ] Implement the smallest shared five-effect matrix and explicit-only target validation. Preserve legacy auto through its separate code path and tests.
- [ ] Add committed end-to-end fixture and namespace-aware OOXML detector for the required 7 configured = 7 resolved = 7 exported targets, timing on slides 1–4 only, and no orphans.
- [ ] Run P2-B CLI `--help`, then a real native enhance round trip. Persist source/enhanced IDs and hashes, animation fingerprints, package inventory, and preservation results.

## P3 — complete automated validation and independent review

- [ ] Execute backend P4 API/service/target/OOXML/editor-export/P2-B/P3 regression suites, syntax checks, and `git diff --check`.
- [ ] Execute frontend tests including AnimationPanel, undo/redo, project/slide isolation, 409, unsupported effect, then typecheck, build, and `git diff --check`.
- [ ] Request an independent native-agent review against the full P4 stable gate. Fix every Critical or Important issue with a new failing test before its implementation.

## P4 — release and post-release evidence

- [ ] Produce the pre-release checkpoint (matrix, counts, SHA, IDs, fingerprints, trigger distribution, review, commits); confirm clean stable worktrees and tested rollback references.
- [ ] Tag rollback points, merge stable commits to the production release worktrees, tag `production-ppt-p4-object-animations-stable-YYYYMMDD`, restart services with the prescribed per-port/user-service commands, and verify 3000/8000 health and unique PIDs.
- [ ] Only after P4 gates pass, restart from P1 on the real browser at `http://192.168.0.117:3000/`: perform the 28-item editor/save/refresh/export/download flow, capture screenshots, console/page-error/network logs, and inspect the downloaded PPTX.
- [ ] Write the seven required P4_STABLE reports with exact commands, test counts, files/SHAs, OOXML/P2-B/browser evidence, tags, PIDs, health, and known limits.

## Verification rule

No test may be deleted, skipped, xfailed, or weakened to hide a defect. A passing claim requires the fresh command output in the report; any production code change follows a demonstrated failing test.
