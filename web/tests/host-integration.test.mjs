import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = (path) => readFileSync(path, "utf8");

test("host owns one runtime Router and Pinia and registers PPT routes", () => {
  const main = source("src/main.js");
  assert.equal((main.match(/createPinia\s*\(/g) || []).length, 1);
  assert.equal((main.match(/createRouter\s*\(/g) || []).length, 1);
  assert.match(main, /\/ppt\/:projectId/);
  assert.match(main, /PptHostPage/);
  assert.match(main, /function createPptProjectId/);
  assert.match(main, /globalThis\.crypto\?\.randomUUID\?\.\(\)/);
  assert.match(main, /ppt-\$\{Date\.now\(\)\}/);
});

test("host page injects the incremental adapter with Legacy fallback and existing auth infrastructure", () => {
  const page = source("src/views/PptHostPage.vue");
  assert.match(page, /new HttpPptWorkflowAdapter/);
  assert.match(page, /new LegacyPptMasterAdapter/);
  assert.match(page, /fallbackAdapter/);
  assert.match(page, /VITE_PPT_INCREMENTAL_ENABLED/);
  assert.match(page, /getSessionToken/);
  assert.match(page, /handleUnauthorized/);
  assert.match(page, /:adapter="adapter"/);
  assert.match(page, /window\.location\.origin/);
  assert.match(page, /verifyDownloadSha256:\s*Boolean\(globalThis\.crypto\?\.subtle\)/);
});

for (const path of ["src/views/WelcomePage.vue", "src/views/ChatPage.vue", "src/views/DocumentPage.vue"]) {
  test(`${path} exposes the PPT route`, () => assert.match(source(path), /\/ppt/));
}

test("PPT feature uses the HTTP-compatible UUID boundary", () => {
  const files = [
    "src/features/ppt-workbench/adapters/LegacyPptMasterAdapter.ts",
    "src/features/ppt-workbench/adapters/MockPptWorkflowAdapter.ts",
    "src/features/ppt-workbench/composables/usePptWorkflow.ts",
  ];
  for (const path of files) {
    assert.doesNotMatch(source(path), /crypto\.randomUUID\(/);
    assert.match(source(path), /createClientUuid/);
  }
});

test("recent PPT projects use the host route", () => {
  const recent = source("src/features/ppt-workbench/components/chat/RecentPptProjects.vue");
  assert.doesNotMatch(recent, /\/ppt-workbench\//);
  assert.match(recent, /`\/ppt\/\$\{encodeURIComponent\(item\.projectId\)\}`/);
});


test("host registers the knowledge route and PPT sidebar returns to it", () => {
  const main = source("src/main.js");
  const page = source("src/views/PptHostPage.vue");
  assert.match(main, /path:\s*['"]\/knowledge['"]/);
  assert.match(page, /router\.push\(['"]\/knowledge['"]\)/);
});
