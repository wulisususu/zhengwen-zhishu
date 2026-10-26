# Execution ledger — plan: docs/superpowers/plans/2026-10-26-policy-integration.md

Task 1: four branch refs imported into Windows from verified incremental Git bundle.
Task 1: all branch heads already contain main@aeee82b. Basic integration is f7a8b20, so merging old main alone cannot add the live HTTP workflow.
Task 1: T2 archive SHA256 verified for all 66 files; source verification 122 passed / 5 xfailed; saved on Windows as fd5803b.
Ruling: preserve existing source worktrees and edit Windows worktrees — current chat starts outside a repository and native worktree creation cannot select the external repository — costs a separate Windows checkout.
Ruling: extend the existing integration branch for T1 under the user's explicit steps 1–3 request — supersedes its earlier exclusion of T1; T2/T3 remain saved separate branches — costs an additional scoped policy integration change set.
Ruling: preserve intranet model policy and local public-policy search — enabling policy integration does not authorize broad model cloud egress — online import may require file upload in intranet mode.
Pre-flight: T1 and basic both register app.main routers; Git auto-merge retained registrations. Document schemas currently reject policyRefs and serialization drops them; add validated citation associations before enabling UI selection.

Task 2: complete — real browser login/create/save/reload/upload/submit/return/revise/resubmit/approve/DOCX/cross-user flow; 55 real government HTTP requests and zero page errors. Evidence: artifacts/20261026/basic-browser/result.json outside the repository.
Task 3: RED — four missing backend policy-association/detail contracts failed, then passed. Five HTTP policy contracts and the policy-library component failed before implementation, then passed.
Final review: fresh read-only reviewer found three Important issues; no Critical or deferred Minor findings.
Final: fixed DOCX table loss — document-order/table text regression RED→GREEN; table imports now mark clause segmentation for human review.
Final: fixed historical-version warning loss — export regression and UI warning regression RED→GREEN.
Final: fixed policy lookup failure blocking documents — missing-ID and store-error regressions RED→GREEN; reads preserve explicit unresolved metadata and server-origin snapshots, while new selections remain strict.
Task 3: verification — actual RK3588 candidate: 211 backend tests passed in 80.16s; frontend 16 host tests and 243 Vitest tests passed; vue-tsc and production build exited zero.
Task 3: browser — real official HTML import, unverified clause search, reference selection, refresh/save and DOCX download passed with zero page errors. Raw source and SHA256 retained outside repository; status never auto-promoted to current.
Ruling: policy lookup outages must not block basic document reading/editing — preserve server-origin source/version snapshots and mark unresolved references unverified — costs visible repair warnings until policy service recovers.
Ruling: Windows-only network-guard test failures are caused by the stdlib event-loop socketpair using loopback; do not weaken the guard — validate the entire relevant suite on actual Linux/RK3588 instead — costs a second test environment.
Full backend Windows pytest: collection blocked by optional python-pptx/docxtpl dependencies in existing PPT/document/pediatric tests; not reported as passing. Targeted Linux verification above is green.
Task 4 preflight: complete app.main on RK3588 with a SQLite backup of production passed real HTTP workflow and policy integration; original counts unchanged (168 users, 1008 conversations, 2475 messages, 606 files, 393 document tasks). No test accounts were created in production.
Main verification: GitHub connector compare aeee82b..main returned identical (ahead=0, behind=0), confirming no newer main commit was missed despite missing CLI credentials.
Task 4: complete — release 0a695d7 switched on RK3588; public browser login/create/save/search/cite/reload/DOCX passed with zero page errors. Temporary production acceptance account/document removed; original counts restored exactly.
Task 4: deployment checks twice caused automatic rollback; HTTP ISO-8859-1 text comparison replaced by exact response bytes, and Git core.worktree updated in the existing worktree-specific config. Final services active and Git worktree clean.
Ruling: retain all development worktrees and feature branches — user requested saved separate deliverables and incremental integration — costs keeping separate source snapshots until future T2/T3 work.
Ruling: initialize one genuine gov.cn policy as unverified — provides a real searchable source without fabricating validity — users must manually verify status or explicitly include unverified clauses.
Final review declined items: legal validity remains human verification; vendor/PPT and T2/T3 remain out of scope. Production preservation and remote-site behavior were accepted by full app/main and actual public-browser tests, not inferred from unit mocks.
Final evidence: docs/superpowers/2026-10-26-policy-integration-acceptance.md. Current model egress remains intranet; no main merge or GitHub push performed.
