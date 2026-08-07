import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const source = (path: string) => readFileSync(path, "utf8");

describe("PPT host integration ownership", () => {
  it("registers PPT routes in the host router without another Pinia", () => {
    const main = source("src/main.js");
    expect(main.match(/createPinia\s*\(/g)).toHaveLength(1);
    expect(main.match(/createRouter\s*\(/g)).toHaveLength(1);
    expect(main).toContain("/ppt/:projectId");
    expect(main).toContain("PptHostPage");
    expect(main).toContain("function createPptProjectId");
    expect(main).toContain("globalThis.crypto?.randomUUID?.()");
    expect(main).toContain("ppt-${Date.now()}");
  });

  it("creates Legacy adapter at the host page with existing auth infrastructure", () => {
    const page = source("src/views/PptHostPage.vue");
    expect(page).toContain("new LegacyPptMasterAdapter");
    expect(page).toContain("getSessionToken");
    expect(page).toContain("handleUnauthorized");
    expect(page).toContain(':adapter="adapter"');
    expect(page).toContain("window.location.origin");
    expect(page).toContain("verifyDownloadSha256: Boolean(globalThis.crypto?.subtle)");
    expect(page).not.toContain("LegacyIntegrationPage");
    expect(page).not.toContain("LegacyUxPreviewPage");
  });

  it.each(["src/views/WelcomePage.vue", "src/views/ChatPage.vue", "src/views/DocumentPage.vue"])(
    "%s exposes the PPT route",
    (path) => expect(source(path)).toContain("/ppt"),
  );

  it("keeps concrete adapters out of the workbench shell", () => {
    const shell = source("src/features/ppt-workbench/components/shell/WorkbenchShell.vue");
    expect(shell).not.toMatch(/MockPptWorkflowAdapter|LegacyPptMasterAdapter|HttpPptWorkflowAdapter/);
    expect(shell).not.toMatch(/new\s+\w*PptWorkflowAdapter/);
  });

  it("links recent projects through the host PPT route", () => {
    const recent = source("src/features/ppt-workbench/components/chat/RecentPptProjects.vue");
    expect(recent).not.toContain("/ppt-workbench/");
    expect(recent).toContain("`/ppt/${encodeURIComponent(item.projectId)}`");
  });
});
