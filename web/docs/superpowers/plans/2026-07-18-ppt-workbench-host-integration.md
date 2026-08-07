# PPT Workbench Host Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the frozen PPT workbench to the AI office host as a production Legacy-backed feature without duplicating host infrastructure.

**Architecture:** The host page owns Adapter construction and injects it into the unchanged workbench feature. The existing application entry owns the only Router and Pinia; PPT state stays in the five feature stores and persists with the existing feature persistence layer.

**Tech Stack:** Vue 3.5, Vite 5.4, Pinia 2.2, Vue Router 4.4, Tailwind 3.4, TypeScript, Vitest.

---

### Task 1: Freeze and repair the host baseline

**Files:**
- Modify: `src/views/ChatPage.vue`
- Modify: `src/views/DocumentPage.vue`
- Test: `tests/host-integration.spec.ts`

- [ ] Write structural tests proving Chat and Document expose valid PPT navigation buttons and the app has one runtime Router/Pinia owner.
- [ ] Run `npm test -- --run tests/host-integration.spec.ts` and confirm failure because the test infrastructure/route is absent.
- [ ] Remove the stray Chat script brace and restore the missing Document PPT button start tag.
- [ ] Run `npm run build`; expect the pre-existing parser failures to be gone.

### Task 2: Add test and typecheck infrastructure

**Files:**
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `vite.config.js`
- Create: `tsconfig.json`
- Create: `tests/host-integration.spec.ts`

- [ ] Add `test` as `vitest run` and `typecheck` as `vue-tsc --noEmit`.
- [ ] Add TypeScript, Vue TSC, Vitest, Vue Test Utils, and happy-dom development dependencies.
- [ ] Configure Vite test environment as happy-dom with CSS enabled.
- [ ] Run the host ownership test and retain its expected route/page failures.

### Task 3: Migrate the frozen feature and scope its CSS

**Files:**
- Create: `src/features/ppt-workbench/**`
- Create: `src/features/ppt-workbench/ppt-workbench.css`
- Test: `tests/*.spec.ts`

- [ ] Copy only `src/features/ppt-workbench/` from baseline `82a4ed4`.
- [ ] Copy the retained Mock, Legacy, Store, persistence, workspace, and component tests.
- [ ] Add only `.ppt-workspace-root` layout/animation rules to the feature stylesheet.
- [ ] Run the PPT suites and confirm Adapter/Store/UI behavior passes without standalone app files.

### Task 4: Register host routes and Adapter injection

**Files:**
- Create: `src/views/PptHostPage.vue`
- Create: `src/features/ppt-workbench/host/hostPptAdapter.ts`
- Modify: `src/main.js`
- Modify: `src/vite-env.d.ts`
- Test: `tests/host-integration.spec.ts`

- [ ] Test that `/ppt` and `/ppt/:projectId` use the host page and that the host page imports the existing auth getter/handler.
- [ ] Implement project-id redirect and the `PptHostPage -> PptWorkbenchPage -> usePptWorkflow -> LegacyPptMasterAdapter` injection chain.
- [ ] Resolve the backend base URL from `VITE_PPT_MASTER_BASE_URL` with same-host port 8000 fallback.
- [ ] Run the host ownership and Adapter boundary tests to green.

### Task 5: Integrate navigation and host styling

**Files:**
- Modify: `src/views/WelcomePage.vue`
- Modify: `src/views/ChatPage.vue`
- Modify: `src/views/DocumentPage.vue`
- Create: `src/components/PptHostNavigation.vue`
- Modify: `src/views/PptHostPage.vue`
- Test: `tests/host-integration.spec.ts`

- [ ] Test that Welcome, Chat, and Document navigate to `/ppt` and that PPT active navigation uses host classes/icons.
- [ ] Enable the Welcome PPT entry and bind desktop/mobile Chat and Document PPT buttons.
- [ ] Render the workbench inside AppHeader and the host content frame without a second global sidebar application.
- [ ] Run navigation tests and production build.

### Task 6: Verify, integrate live, and deliver

**Files:**
- Create: `HOST_INTEGRATION_REPORT.md`
- Create: `artifacts/host-integration/**`

- [ ] Run `npm test`, `npm run typecheck`, and `npm run build`.
- [ ] Start the host dev server with one-page Legacy configuration and log in through the normal business login page.
- [ ] Verify real SSE completion, Chinese stage cards, authenticated Blob download, refresh restoration, and Chat/Word/knowledge regression.
- [ ] Confirm browser console has no errors/warnings and evidence contains no JWT or server paths.
- [ ] Commit the feature branch, merge it into host `main`, rerun verification, and tag `ppt-workbench-host-baseline-20260718`.
