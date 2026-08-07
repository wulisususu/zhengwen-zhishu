# PPT Workbench Host Integration Design

## Objective

Integrate the frozen PPT workbench baseline `main@82a4ed4` into the existing AI office host as one feature module. The host remains the only Vue application and owns application startup, Router, Pinia, authentication, navigation, and global styling.

## Host baseline and rollback

The server working state is preserved by commit `3a7763a` and tag `pre-ppt-host-integration-20260718`. The integration branch starts at that exact snapshot. The snapshot has a known pre-existing build error in `ChatPage.vue` and malformed PPT navigation markup in `DocumentPage.vue`; both are repaired without changing Chat/Word domain behavior.

## Runtime architecture

- `src/features/ppt-workbench/` is copied from the frozen local baseline without standalone `main.ts`, Router, development JWT pages, screenshots, or global CSS reset.
- `src/views/PptHostPage.vue` is the composition boundary. It creates `LegacyPptMasterAdapter`, reads JWT through the existing `getSessionToken()`, delegates 401 handling to `handleUnauthorized()`, and injects the Adapter into `PptWorkbenchPage`.
- The host keeps one `createApp`, one `createPinia`, and one active `createRouter`. Routes `/ppt` and `/ppt/:projectId` are registered in the host route table.
- `/ppt` redirects to a generated project identifier. `/ppt/:projectId` renders the workbench and restores its existing project/session persistence.
- Chat, Document, Welcome, and PPT host navigation reuse the current Lucide icon, size, color, hover, and selected-state conventions.

## Authentication and backend

The Adapter uses `VITE_PPT_MASTER_BASE_URL`, falling back to the current host name on port 8000. It never stores a token. `getAccessToken` calls the existing host getter for every request and download; `onUnauthorized` invokes the host authentication-expired flow. Legacy authenticated Blob download and integrity verification remain inside the Adapter.

## Styling

Only PPT layout rules are moved into `src/features/ppt-workbench/ppt-workbench.css`, scoped by `.ppt-workspace-root`. The host retains its existing Tailwind entry and global font/form rules. The PPT page renders inside the current AppHeader/content frame and does not add a second application shell.

## Error handling

The host currently has no unified toast component. Authentication errors use the existing global auth event/redirect. Other normalized workflow and download errors remain visible in the workbench result/error cards; no `alert()` or new global toast is introduced.

## Verification

Vitest and Vue Test Utils run the retained PPT Adapter/Store/UI suites plus host ownership tests. Host build and typecheck must pass. Browser verification covers Welcome/Chat/Word/knowledge navigation, Mock workbench behavior, real one-page Legacy SSE/download, refresh restoration, logout/auth expiry, console output, and secret/path leakage.
