import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("native enhance entry", () => {
  it("exposes the existing-PPT enhancement entry from the conversation shell", () => {
    const shell = readFileSync("src/features/ppt-workbench/components/shell/WorkbenchShell.vue", "utf8");
    const landing = readFileSync("src/features/ppt-workbench/components/chat/LandingComposer.vue", "utf8");
    expect(shell).toContain("NativeEnhanceWorkspace");
    expect(landing).toContain("增强已有 PPT");
    const nativeWorkspace = readFileSync("src/features/ppt-workbench/components/template/NativeEnhanceWorkspace.vue", "utf8");
    expect(nativeWorkspace).toContain("uploadSource");
    expect(nativeWorkspace).toContain("accept=\".pptx\"");
    expect(nativeWorkspace).toContain("selectedSlideIds");
    expect(nativeWorkspace).toContain("durationMs");
    expect(nativeWorkspace).toContain("autoAdvanceMs");
    expect(nativeWorkspace).toContain("pageNumber");
    expect(nativeWorkspace).toContain("documentProperties");
  });
});
