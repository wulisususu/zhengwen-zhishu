import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { usePptWorkspaceStore } from "../src/features/ppt-workbench/stores/pptWorkspace";

describe("workspace mode", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("starts as a full conversation", () => {
    const workspace = usePptWorkspaceStore();
    expect(workspace.workspaceMode).toBe("conversation");
    expect(workspace.activeView).toBe("editor");
  });

  it("enters opening and then the split workbench", () => {
    const workspace = usePptWorkspaceStore();
    workspace.beginOpening();
    expect(workspace.workspaceMode).toBe("opening");
    workspace.finishOpening();
    expect(workspace.workspaceMode).toBe("split-workbench");
  });

  it("can reopen from a result card after being closed", () => {
    const workspace = usePptWorkspaceStore();
    workspace.beginOpening();
    workspace.finishOpening();
    workspace.closeWorkbench();
    expect(workspace.workspaceMode).toBe("conversation");
    workspace.beginOpening();
    expect(workspace.workspaceMode).toBe("opening");
  });

  it("keeps the selected slide and editor context when closed", () => {
    const workspace = usePptWorkspaceStore();
    workspace.selectSlide("slide-2");
    workspace.editorZoom = 0.82;
    workspace.editorScrollTop = 240;
    workspace.closeWorkbench();
    expect(workspace.selectedSlideId).toBe("slide-2");
    expect(workspace.editorZoom).toBe(0.82);
    expect(workspace.editorScrollTop).toBe(240);
  });
});
