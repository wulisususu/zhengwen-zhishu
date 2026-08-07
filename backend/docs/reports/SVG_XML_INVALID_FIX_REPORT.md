
# SVG_XML_INVALID_FIX_REPORT

## 1. Executive summary

On July 20, 2026, legacy PPT generation failures with blocker `svg_xml_invalid` were traced to the legacy one-shot “all slides as a JSON array” generation path. When that JSON parse failed, the backend fell back to raw text, then pushed non-SVG / non-XML content through export validation, which collapsed into the generic blocker `svg_xml_invalid`.

The backend was changed to generate slides one page at a time, sanitize and strictly parse model SVG output before acceptance, retry only failed slides, persist sanitized diagnostics, and block export only when final validation still has blocking errors.

During real acceptance on `http://127.0.0.1:8000`, a second operational problem was discovered: the 8000 service was being restarted during active SSE requests, and the service unit had `TimeoutStopUSec=1s`, so systemd escalated to `SIGKILL` before the request could drain. That issue was mitigated by:

- aligning the 8000 service startup path to the same `uvicorn` CLI mode that was verified on a diagnostic port;
- increasing `TimeoutStopSec` to 900 seconds so in-flight PPT SSE requests can finish instead of being hard-killed one second after `systemctl restart`.

After both the SVG fix and the service hardening were in place, controlled production acceptance on port 8000 completed successfully for 4-page and 8-page real tasks.

## 2. Historical failing tasks and original root cause

Confirmed historical legacy failures in `data/app.db -> ppt_generation_requests`:

| task_id | created_at (CST) | status | blocker |
| --- | --- | --- | --- |
| `ppt_f7d2c5355d11449fa6556498eef52240` | 2026-07-20 01:44:17 | failed | `svg_xml_invalid` |
| `ppt_e1c0a9056c1743f9a4525543eb2772c0` | 2026-07-20 06:49:28 | failed | `svg_xml_invalid` |

Relevant legacy log sequence (July 20, 2026):

- legacy SVG JSON parse failed;
- raw text fallback was used as a single page;
- SVG security gate then blocked export as `svg_xml_invalid`.

This meant the visible blocker was XML-invalid SVG, but the upstream defect was the legacy batch JSON generation contract itself.

## 3. Exact SVG/XML failure categories now identified

The new parser/security gate classifies and reports precise failure categories instead of only returning a generic XML failure. Implemented categories include:

- `svg_root_missing`
- `truncated_output`
- `tag_not_closed`
- `unescaped_entity`
- `xml_declaration_misplaced`
- `extra_text_after_svg`
- `xml_not_well_formed`

The sanitization path now strips or repairs, when it is safe to do so:

- Markdown code fences;
- explanatory text before/after `<svg>...</svg>`;
- illegal XML control characters;
- repeated / misplaced XML declaration;
- bare `&` entities.

Unsafe constructs remain fail-closed:

- `file://`
- external URLs
- absolute/local paths
- traversal
- symlink escapes
- `script`
- `foreignObject`
- entity / doctype usage

## 4. Code changes applied

Backend code changes:

- `app/PPT_master/security.py`
- `app/PPT_master/incremental_slides.py`
- `app/PPT_master/incremental_runner.py`
- `app/PPT_master/incremental_store.py`
- `app/PPT_master/nodes.py`
- `app/PPT_master/admission.py`
- `app/PPT_master/runner.py`

Tests added or updated:

- `tests/test_ppt_incremental_slides.py`
- `tests/test_ppt_incremental_runner.py`
- `tests/test_ppt_stage_a_security.py`
- `tests/test_ppt_stage_a_legacy_svg.py`
- `tests/test_ppt_stage_a_failure_diagnostics.py`

Operational deployment change (not in git repo):

- `/etc/systemd/system/innet_backend.service`

## 5. Repair / retry strategy after the fix

The legacy chain no longer generates all pages in one JSON batch. It now:

1. builds outline/pages;
2. generates one slide at a time;
3. extracts real SVG root from model output;
4. removes Markdown fences and outer explanation text;
5. removes illegal XML control chars;
6. safely escapes bare XML entities;
7. performs strict XML parse;
8. runs SVG safety validation;
9. retries only the failed slide when repairable;
10. preserves already completed slides;
11. blocks final `done` / export only if final validation still has blocking errors.

Legacy failure payloads now include sanitized `validation_result`, `failed_slides`, and `metrics` instead of pretending success.

## 6. Tests executed

Focused SVG/PPT regression tests:

- `/home/youyeetoo/rkllm_model_zoo/funasr_env/bin/python -m pytest -q tests/test_ppt_incremental_slides.py tests/test_ppt_incremental_runner.py tests/test_ppt_stage_a_security.py tests/test_ppt_stage_a_legacy_svg.py tests/test_ppt_stage_a_failure_diagnostics.py`
- Result: `45 passed`

All PPT-targeted tests:

- `/home/youyeetoo/rkllm_model_zoo/funasr_env/bin/python -m pytest -q tests/test_ppt_*`
- Result: `93 passed`

Full repository suite still has unrelated pre-existing failures outside PPT scope (for example docs pipeline / ASR / OpenClaw / PI-agent tests). Those were not introduced by this fix.

## 7. Real acceptance evidence

### 7.1 Isolation diagnosis

A temporary diagnostic instance on port `18082` using direct `uvicorn app.main:app` completed a real 4-page legacy task successfully.

This proved the SVG repair path itself was runnable end-to-end before returning to the production 8000 instance.

### 7.2 8000 service interruption root cause discovered during acceptance

Before service hardening, controlled 8000 acceptance attempts were interrupted by service restarts during active SSE requests.

Observed on July 20, 2026:

- a `sudo systemctl restart innet_backend` hit the service while a PPT request was inside the `svg` stage;
- the unit had `TimeoutStopUSec=1s`;
- systemd escalated from `SIGTERM` to `SIGKILL` before the SSE request could drain.

Mitigation applied:

- `ExecStart` changed to `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`
- `TimeoutStopSec=900`

Current verified service state after mitigation:

- port 8000 health: OK
- main process: single worker
- `TimeoutStopUSec=15min`
- final unit file on disk was re-written to the same uvicorn CLI / 15-minute stop-timeout configuration after a later validation-time drift, then `daemon-reload` was applied without interrupting the healthy active worker

### 7.3 Successful 8000 production acceptance runs

Successful 4-page runs on port 8000 after hardening:

| request_id | task_id | file_id | elapsed_s | sha256 | result |
| --- | --- | --- | ---: | --- | --- |
| `svgfix-4-1-99f1594435ef` | `ppt_bad86237d4b8491fb954a3c380d79d55` | 636 | 222.23 | `1b0459ca6802…` | done / valid |
| `svgfix-4-1-6b611f975817` | `ppt_3edc74bacdc14046a9ccd0ae34dcb6ab` | 637 | 160.18 | `e06ae97771cc…` | done / valid |
| `svgfix-4-2-176fe6593925` | `ppt_9c87a2009bfd41cab2b9d3bfe9a329c0` | 638 | 213.05 | `38d99830a0be…` | done / valid |
| `svgfix-4-1-288c07bde46f` | `ppt_53172c152e8a4cfdb9d3d040de410037` | 642 | 171.18 | `be87b9388120…` | done / valid |

Successful 8-page runs on port 8000 after hardening:

| request_id | task_id | file_id | elapsed_s | sha256 | result |
| --- | --- | --- | ---: | --- | --- |
| `svgfix-8-1-3e93221c232c` | `ppt_9c240ea42c974669b369688caef3ce8b` | 639 | 328.94 | `b06f4899fc1d…` | done / valid |
| `svgfix-8-1-9277bb94e80d` | `ppt_7e71135df26f4205a533b79c1cd4952e` | 640 | 380.52 | `1242b30d403f…` | done / valid |
| `svgfix-8-2-1e3a7c1a4611` | `ppt_f597483ed94f42e3acbe66b774bd0919` | 641 | 349.25 | `e01d0a94c6ae…` | done / valid |

### 7.4 Download / ownership / OOXML checks

Verified in real acceptance:

- owner download: HTTP 200
- other user download: HTTP 404
- unauthenticated download: HTTP 401
- returned payload exposes `file_id`, `download_url`, `size`, `sha256`, `valid`
- no server filesystem path exposed in `done`
- downloaded PPTX opens as ZIP / OOXML package
- slide XML count matches expected pages
- editable PowerPoint shape/text evidence present (`p:sp` and `a:t` nodes found)
- `validation_result.passed=true` and `blocking_errors=[]` for successful accepted tasks

Sample OOXML evidence from accepted files:

- 4-page accepted samples: 24 ZIP entries, 172–251 shape nodes, 88–129 text nodes
- 8-page accepted samples: 32 ZIP entries, 429–515 shape nodes, 209–260 text nodes

## 8. Failure-rate statistics

### Historical observed failures before the fix

Observed legacy `svg_xml_invalid` failures persisted in production history on July 20, 2026:

- 2 confirmed legacy failures on July 20, 2026 (`ppt_f7d2...`, `ppt_e1c0...`)
- additional earlier legacy failures remained in July 18 history

### Controlled acceptance after the fix and service hardening

- 4-page tasks on 8000: `4/4` successful, `0%` failure
- 8-page tasks on 8000: `3/3` successful, `0%` failure
- acceptance-observed `svg_xml_invalid`: `0`
- acceptance-observed `validation_failed`: `0`

### Implemented per-task counters

The backend now records / propagates task-level counters used for SVG failure analysis:

- `model_output_count`
- `svg_xml_invalid_count`
- `svg_sanitize_success_count`
- `svg_validation_blocked_count`
- `model_repair_retry_count`

These are persisted into sanitized failure diagnostics and failure payloads. Successful legacy `done` payloads do not yet expose these counters, so cross-task aggregation for successful legacy runs is still a follow-up observability gap.

## 9. Rollback

### Service-unit rollback

To restore the previous 8000 service wrapper:

1. copy `/home/youyeetoo/ppt_stage_backups/innet_backend.service.20260720.bak` back to `/etc/systemd/system/innet_backend.service`
2. run `systemctl daemon-reload`
3. restart `innet_backend.service`

### Code rollback

The SVG fix itself is currently present in the working tree files listed in section 4. Reverting only these PPT files should be done carefully because the repository has unrelated pre-existing dirty changes. Do not hard-reset the whole repository on the production host.

## 10. Remaining P1 / P2 items

P1:

- Legacy success path still does not expose per-task SVG counters in successful `done` payloads / DB rows, so fleet-level success-case aggregation remains partial.
- Two early acceptance attempts before the service hardening were interrupted and left stale `running` rows in `ppt_generation_requests`; a startup reconciliation policy would improve idempotency hygiene.
- `GET /api/v1/ppt-master/tasks/{task_id}` currently serves incremental tasks only; querying a legacy `ppt_*` task returns 404 by design of the current route. This is not a regression from the SVG fix, but it is still a compatibility/documentation gap.

P2:

- legacy failure analytics are richer now, but a persistent aggregate dashboard / metric export is still not in place;
- broader non-PPT repository test failures remain outside this fix.

## 11. Frontend impact

No frontend change is required for the `svg_xml_invalid` fix itself.

The legacy API contract remains compatible: successful legacy generation still terminates with `done`, download stays JWT-protected, and invalid SVG is not treated as success.
