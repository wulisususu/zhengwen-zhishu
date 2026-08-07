import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import WorkbenchShell from "../src/features/ppt-workbench/components/shell/WorkbenchShell.vue";
import { mockWorkflowCapabilities } from "../src/features/ppt-workbench/protocol/capabilities";
import { usePptWorkspaceStore } from "../src/features/ppt-workbench/stores/pptWorkspace";
import { usePptProjectStore } from "../src/features/ppt-workbench/stores/pptProject";
import { usePptGenerationStore } from "../src/features/ppt-workbench/stores/pptGeneration";
import { usePptEditorStore } from "../src/features/ppt-workbench/stores/pptEditor";
import type { PptWorkflowController } from "../src/features/ppt-workbench/composables/usePptWorkflow";

describe("split workbench shell", () => {
  let pinia: ReturnType<typeof createPinia>;
  let workflow: PptWorkflowController;

  beforeEach(() => {
    localStorage.clear();
    pinia = createPinia();
    setActivePinia(pinia);
    workflow = {
      start: vi.fn(async () => {}),
      apply: vi.fn(),
      downloadLatest: vi.fn(),
      restoreSlideAssets: vi.fn(async () => {}),
      openWorkbench: vi.fn(() => usePptWorkspaceStore().beginOpening()),
      closeWorkbench: vi.fn(() => usePptWorkspaceStore().closeWorkbench()),
      switchProject: vi.fn(() => {}),
      capabilities: mockWorkflowCapabilities,
    };
  });

  const mountShell = () => mount(WorkbenchShell, {
    props: { projectId: "project-1", workflow },
    global: { plugins: [pinia] },
  });

  async function submit(wrapper: ReturnType<typeof mountShell>, prompt: string) {
    const input = wrapper.get('[aria-label="PPT 需求输入"]');
    await input.setValue(prompt);
    await wrapper.get("form").trigger("submit");
    await flushPromises();
  }

  it("starts with only the full conversation page", () => {
    const wrapper = mountShell();
    expect(wrapper.get("[data-workspace-root]").attributes("data-workspace-mode")).toBe("conversation");
    expect(wrapper.find('[aria-label="PPT 工作区视图"]').exists()).toBe(false);
    expect(wrapper.find("[data-slide-rail]").exists()).toBe(false);
    expect(wrapper.find("[data-editor-workspace]").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("后台阶段：");
  });

  it("does not load an editor for a transient client-side project route", async () => {
    const load = vi.spyOn(usePptEditorStore(), "load");
    mount(WorkbenchShell, {
      props: { projectId: "ppt-1784902081202-a881li4i", workflow },
      global: { plugins: [pinia] },
    });
    await flushPromises();
    expect(load).not.toHaveBeenCalled();
  });

  it("keeps the full conversation after a valid submit starts", async () => {
    const wrapper = mountShell();
    await submit(wrapper, "生成年度复盘 PPT");
    expect(workflow.start).toHaveBeenCalledOnce();
    expect(usePptWorkspaceStore().workspaceMode).toBe("conversation");
  });

  afterEach(() => vi.useRealTimers());

  it("keeps conversation for empty input or a workflow that cannot start", async () => {
    const wrapper = mountShell();
    await submit(wrapper, "   ");
    expect(workflow.start).not.toHaveBeenCalled();
    expect(usePptWorkspaceStore().workspaceMode).toBe("conversation");
    vi.mocked(workflow.start).mockImplementationOnce(() => { throw new Error("cannot start"); });
    await submit(wrapper, "生成年度复盘 PPT");
    expect(usePptWorkspaceStore().workspaceMode).toBe("conversation");
  });

  it("allows the user to explicitly open the workbench during planning", async () => {
    usePptGenerationStore().start({
      id: "task-1",
      projectId: "project-1",
      chatId: "chat-1",
      stage: "understanding",
      status: "running",
      progress: 10,
      lastAppliedSequence: 1,
    });
    const wrapper = mountShell();

    await wrapper.get("[data-open-workbench-early]").trigger("click");

    expect(workflow.openWorkbench).toHaveBeenCalledOnce();
    expect(usePptWorkspaceStore().workspaceMode).toBe("opening");
  });

  it("shows chat, pending thumbnails and editor skeleton after opening", async () => {
    const workspace = usePptWorkspaceStore();
    workspace.beginOpening();
    const wrapper = mountShell();
    await wrapper.get("[data-workspace-root]").trigger("transitionend");
    expect(workspace.workspaceMode).toBe("split-workbench");
    expect(wrapper.find(".guided-planner").exists()).toBe(false);
    expect(wrapper.get("[data-chat-panel]")).toBeTruthy();
    expect(wrapper.get("[data-slide-rail]")).toBeTruthy();
    expect(wrapper.get("[data-slide-skeleton]")).toBeTruthy();
    expect(wrapper.get("[data-editor-skeleton]")).toBeTruthy();
  });

  it("finishes the opening fallback after 560ms", async () => {
    vi.useFakeTimers();
    const workspace = usePptWorkspaceStore();
    mountShell();
    workspace.beginOpening();
    await vi.advanceTimersByTimeAsync(559);
    expect(workspace.workspaceMode).toBe("opening");
    await vi.advanceTimersByTimeAsync(1);
    expect(workspace.workspaceMode).toBe("split-workbench");
  });

  it("does not change workspace mode or active view when a slide becomes ready", async () => {
    const workspace = usePptWorkspaceStore();
    workspace.workspaceMode = "split-workbench";
    workspace.selectView("preview");
    const wrapper = mountShell();
    usePptProjectStore().upsertSlide({ id: "slide-1", index: 1, title: "封面", status: "ready", elements: [], userModifiedFields: [], revision: 1 });
    await flushPromises();
    expect(workspace.workspaceMode).toBe("split-workbench");
    expect(workspace.activeView).toBe("preview");
    expect(wrapper.get("[data-preview-panel]").text()).toContain("封面");
  });

  it("shows truthful one-shot Legacy states instead of fake pending pages", async () => {
    workflow.capabilities = { ...mockWorkflowCapabilities, incrementalSlides: false };
    const workspace = usePptWorkspaceStore();
    workspace.workspaceMode = "split-workbench";
    const wrapper = mountShell();
    const generation = usePptGenerationStore();
    generation.start({
      id: "legacy-task",
      projectId: "project-1",
      chatId: "chat-1",
      stage: "understanding",
      status: "running",
      progress: 0,
      lastAppliedSequence: 0,
      requestedPageCount: 6,
    });
    await flushPromises();
    expect(wrapper.get("[data-legacy-generation-placeholder]").text()).toContain("后端正在一次性生成");
    expect(wrapper.find("[data-slide-skeleton]").exists()).toBe(false);
    expect(wrapper.findAll("[data-legacy-slide-skeleton]")).toHaveLength(6);
    expect(usePptProjectStore().slides).toHaveLength(0);
    expect(wrapper.text()).toContain("6 页占位");

    usePptProjectStore().setExportArtifact({
      fileId: 595,
      downloadUrl: "http://192.168.0.11:8000/api/v1/files/595/download",
      size: 14964,
      sha256: "a".repeat(64),
      valid: true,
      warnings: [],
    });
    generation.status = "completed";
    await flushPromises();
    expect(wrapper.get("[data-legacy-file-ready]").text()).toContain("PPTX 文件已生成");
    expect(wrapper.get("[data-legacy-editor-ready]").text()).toContain("不提供在线逐页画布");
    expect(wrapper.text()).toContain("不提供逐页预览");
  });
});
