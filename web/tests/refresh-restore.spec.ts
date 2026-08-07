import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import WorkbenchShell from "../src/features/ppt-workbench/components/shell/WorkbenchShell.vue";
import { mockWorkflowCapabilities } from "../src/features/ppt-workbench/protocol/capabilities";
import { saveWorkspaceState } from "../src/features/ppt-workbench/persistence/workspaceStorage";
import { saveProjectSession, type PersistedProjectSession } from "../src/features/ppt-workbench/persistence/projectSessionStorage";
import { usePptWorkspaceStore } from "../src/features/ppt-workbench/stores/pptWorkspace";
import { usePptProjectStore } from "../src/features/ppt-workbench/stores/pptProject";
import type { PptWorkflowController } from "../src/features/ppt-workbench/composables/usePptWorkflow";
import type { Slide } from "../src/features/ppt-workbench/types/presentation";

describe("refresh restore", () => {
  let pinia: ReturnType<typeof createPinia>;
  beforeEach(() => {
    localStorage.clear();
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it("restores project content and the open editor context", async () => {
    const slide = { id: "slide-2", index: 2, title: "恢复后的页面", status: "ready" as const, elements: [], userModifiedFields: [], revision: 1, speakerNotes: "恢复后的演讲稿" };
    const project = {
      id: "project-1", title: "恢复项目", brief: { goal: "恢复", audience: "管理层", slideCount: 2, constraints: [] }, outline: [],
      presentation: { aspectRatio: "16:9" as const, slides: [slide] }, theme: null, validation: null, version: 1,
      createdAt: "2026-07-17T00:00:00.000Z", updatedAt: "2026-07-17T00:00:00.000Z",
    };
    const session: PersistedProjectSession = {
      projectId: "project-1", project, outline: [], slides: [slide], theme: null, validation: null, proposals: [], projectRevision: 1,
      conversation: { chatId: "chat-1", messages: [{ id: "assistant-1", role: "assistant", content: "已恢复生成记录", createdAt: "2026-07-17T00:00:00.000Z" }] },
      generation: { task: null, workflowStage: "completed", status: "completed", progress: 100, error: null },
    };
    saveProjectSession("project-1", session);
    saveWorkspaceState("project-1", { workspaceMode: "split-workbench", activeView: "editor", selectedSlideId: "slide-2", chatPanelWidth: 410, slideRailWidth: 190, chatCollapsed: false, slideRailCollapsed: false, editorZoom: 0.9, conversationScrollTop: 12, slideRailScrollTop: 34, editorScrollTop: 56 });

    const wrapper = mount(WorkbenchShell, {
      props: {
        projectId: "project-1",
        workflow: {
          start: vi.fn(async () => {}),
          apply: vi.fn(),
          downloadLatest: vi.fn(),
          restoreSlideAssets: vi.fn(async () => {}),
          openWorkbench: vi.fn(() => usePptWorkspaceStore().beginOpening()),
          closeWorkbench: vi.fn(() => usePptWorkspaceStore().closeWorkbench()),
          switchProject: vi.fn(() => {}),
          capabilities: mockWorkflowCapabilities,
        },
      },
      global: { plugins: [pinia] },
    });
    await wrapper.vm.$nextTick();
    expect(usePptWorkspaceStore().workspaceMode).toBe("split-workbench");
    expect(usePptWorkspaceStore().selectedSlideId).toBe("slide-2");
    expect(usePptProjectStore().slides[0]?.title).toBe("恢复后的页面");
    expect(wrapper.text()).toContain("已恢复生成记录");
    expect(wrapper.get("[data-editor-canvas]").text()).toContain("恢复后的页面");
  });


  it("hydrates a historical project from the server when no browser session exists", async () => {
    const loadHistoryProject = vi.fn(async () => ({
      project: {
        id: "pptproj-history", title: "服务器历史 PPT",
        brief: { goal: "历史目标", audience: "管理层", slideCount: 1, constraints: [] },
        outline: [{ id: "outline-1", title: "历史封面", description: "历史封面内容", status: "ready" as const, children: [] }],
        presentation: { aspectRatio: "16:9" as const, slides: [{
          id: "history-slide-1", index: 1, title: "历史封面", status: "ready" as const, elements: [],
          previewArtifactId: 725, thumbnailArtifactId: 725, speakerNotes: "", userModifiedFields: [], revision: 1,
        }] },
        theme: null, validation: null, exportArtifact: {
          fileId: 730, downloadUrl: "/api/v1/files/730/download", size: 34680, sha256: "a".repeat(64), valid: true as const, warnings: [], slideCount: 1,
        }, version: 1, createdAt: "2026-07-25T00:00:00.000Z", updatedAt: "2026-07-25T00:00:00.000Z",
      },
    }));
    const restoreSlideAssets = vi.fn(async (slides: Slide[]) => slides.map((slide) => ({ ...slide, previewUrl: "blob:history", thumbnailUrl: "blob:history" })));
    const wrapper = mount(WorkbenchShell, {
      props: {
        projectId: "pptproj-history",
        workflow: {
          start: vi.fn(async () => {}), apply: vi.fn(), downloadLatest: vi.fn(), loadHistoryProject, restoreSlideAssets,
          openWorkbench: vi.fn(() => usePptWorkspaceStore().beginOpening()), closeWorkbench: vi.fn(() => usePptWorkspaceStore().closeWorkbench()),
          switchProject: vi.fn(() => {}), capabilities: mockWorkflowCapabilities,
        } as unknown as PptWorkflowController,
      },
      global: { plugins: [pinia] },
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await wrapper.vm.$nextTick();

    expect(loadHistoryProject).toHaveBeenCalledWith("pptproj-history");
    expect(usePptProjectStore().project?.title).toBe("服务器历史 PPT");
    expect(usePptWorkspaceStore().activeView).toBe("preview");
    expect(usePptProjectStore().slides[0]).toMatchObject({ title: "历史封面", previewUrl: "blob:history" });
  });

  it("rehydrates persisted slide artifact ids into fresh preview URLs after refresh", async () => {
    const slide = {
      id: "slide-1",
      index: 1,
      title: "带预览的页面",
      status: "ready" as const,
      elements: [],
      previewArtifactId: 101,
      thumbnailArtifactId: 101,
      previewUrl: undefined,
      thumbnailUrl: undefined,
      userModifiedFields: [],
      revision: 1,
    };
    const project = {
      id: "project-assets",
      title: "恢复预览项目",
      brief: { goal: "恢复预览", audience: "管理层", slideCount: 1, constraints: [] },
      outline: [],
      presentation: { aspectRatio: "16:9" as const, slides: [slide] },
      theme: null,
      validation: null,
      version: 1,
      createdAt: "2026-07-17T00:00:00.000Z",
      updatedAt: "2026-07-17T00:00:00.000Z",
    };
    const session: PersistedProjectSession = {
      projectId: "project-assets",
      project,
      outline: [],
      slides: [slide],
      theme: null,
      validation: null,
      proposals: [],
      projectRevision: 1,
      conversation: { chatId: "chat-assets", messages: [] },
      generation: { task: null, workflowStage: "completed", status: "completed", progress: 100, error: null },
    };
    saveProjectSession("project-assets", session);
    saveWorkspaceState("project-assets", { workspaceMode: "split-workbench", activeView: "preview", selectedSlideId: "slide-1", chatPanelWidth: 410, slideRailWidth: 190, chatCollapsed: false, slideRailCollapsed: false, editorZoom: 1, conversationScrollTop: 0, slideRailScrollTop: 0, editorScrollTop: 0 });
    const restoreSlideAssets = vi.fn(async (slides) => {
      const store = usePptProjectStore();
      for (const item of slides) store.upsertSlide({ ...item, previewUrl: "blob:fresh-preview", thumbnailUrl: "blob:fresh-thumb" });
    });

    const wrapper = mount(WorkbenchShell, {
      props: {
        projectId: "project-assets",
        workflow: {
          start: vi.fn(async () => {}),
          apply: vi.fn(),
          downloadLatest: vi.fn(),
          restoreSlideAssets,
          openWorkbench: vi.fn(() => usePptWorkspaceStore().beginOpening()),
          closeWorkbench: vi.fn(() => usePptWorkspaceStore().closeWorkbench()),
          switchProject: vi.fn(() => {}),
          capabilities: mockWorkflowCapabilities,
        },
      },
      global: { plugins: [pinia] },
    });
    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 0));
    await wrapper.vm.$nextTick();

    expect(restoreSlideAssets).toHaveBeenCalledWith([expect.objectContaining({ previewArtifactId: 101, thumbnailArtifactId: 101 })]);
    expect(usePptProjectStore().slides[0]?.previewUrl).toBe("blob:fresh-preview");
    expect(usePptProjectStore().slides[0]?.thumbnailUrl).toBe("blob:fresh-thumb");
    expect(wrapper.find("[data-preview-image]").exists()).toBe(true);
  });
});
