import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import SlideThumbnail from "../src/features/ppt-workbench/components/slides/SlideThumbnail.vue";
import EditorWorkspace from "../src/features/ppt-workbench/components/editor/EditorWorkspace.vue";
import ValidationPanel from "../src/features/ppt-workbench/components/validation/ValidationPanel.vue";
import { usePptProjectStore } from "../src/features/ppt-workbench/stores/pptProject";
import { usePptWorkspaceStore } from "../src/features/ppt-workbench/stores/pptWorkspace";
import { usePptGenerationStore } from "../src/features/ppt-workbench/stores/pptGeneration";
import { usePptEditorStore } from "../src/features/ppt-workbench/stores/pptEditor";
import type { Slide } from "../src/features/ppt-workbench/types/presentation";

const slide = (id: string, index: number, status: Slide["status"] = "ready"): Slide => ({
  id, index, status, title: `第 ${index} 页`, elements: [], userModifiedFields: [], revision: 1,
  speakerNotes: `第 ${index} 页演讲稿`,
});

describe("editor workspace", () => {
  let pinia: ReturnType<typeof createPinia>;
  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it.each(["pending", "generating", "ready", "error"] as const)("renders a %s thumbnail from Slide.status", (status) => {
    const wrapper = mount(SlideThumbnail, { props: { slide: slide("slide-1", 1, status), selected: false } });
    expect(wrapper.attributes("data-status")).toBe(status);
  });

  it("shows a controlled skeleton before slides arrive", () => {
    const wrapper = mount(EditorWorkspace, { global: { plugins: [pinia] } });
    expect(wrapper.get("[data-editor-skeleton]")).toBeTruthy();
  });

  it("renders locked SVG vectors stored in a historical editor document", () => {
    const editor = usePptEditorStore();
    editor.document = {
      project_id: "history-project", base_task_id: "history-task",
      slides: [{ slide_id: "history-slide-1", order: 1, width: 1280, height: 720, elements: [{
        id: "vector-1", type: "lockedVector", x: 0, y: 0, width: 0, height: 0, rotation: 0, z_index: 1, locked: true, style: {},
        content: { svg: "<text data-history-vector=\"true\" x=\"80\" y=\"100\">历史封面</text>" },
      }] }],
    };
    editor.selectedSlideId = "history-slide-1";
    const wrapper = mount(EditorWorkspace, { global: { plugins: [pinia] } });
    expect(wrapper.get("[data-editor-canvas]").html()).toContain("历史封面");
  });

  it("keeps the Animation inspector out of the canvas until an object is selected", () => {
    const editor = usePptEditorStore();
    editor.document = { project_id: "history-project", base_task_id: "history-task", slides: [{ slide_id: "history-slide-1", order: 1, width: 1280, height: 720, elements: [] }] };
    const wrapper = mount(EditorWorkspace, { global: { plugins: [pinia] } });

    expect(wrapper.find(".p4-animation-panel").exists()).toBe(false);
  });

  it("does not show the speaker-notes panel when the project has no notes", () => {
    const wrapper = mount(EditorWorkspace, { global: { plugins: [pinia] } });
    expect(wrapper.find("[data-speaker-notes]").exists()).toBe(false);
  });

  it("shares selectedSlideId across canvas and speaker notes", () => {
    const project = usePptProjectStore();
    project.upsertSlide(slide("slide-1", 1));
    project.upsertSlide(slide("slide-2", 2));
    usePptWorkspaceStore().selectSlide("slide-2");
    const wrapper = mount(EditorWorkspace, { global: { plugins: [pinia] } });
    expect(wrapper.get("[data-editor-canvas]").text()).toContain("第 2 页");
    expect(wrapper.get("[data-speaker-notes]").text()).toContain("第 2 页演讲稿");
  });

  it("keeps a historical project on its original SVG preview when Edit is selected", async () => {
    const project = usePptProjectStore();
    project.setProject({
      id: "history-project", title: "历史封面", isHistorical: true,
      brief: { goal: "", audience: "", slideCount: 1, constraints: [] }, outline: [],
      presentation: { aspectRatio: "16:9", slides: [{ ...slide("history-slide-1", 1), previewUrl: "blob:history-slide" }] },
      theme: null, validation: null, version: 1, createdAt: "2026-07-25T00:00:00.000Z", updatedAt: "2026-07-25T00:00:00.000Z",
    } as any);
    const workspace = usePptWorkspaceStore();
    workspace.selectSlide("history-slide-1");
    workspace.selectView("editor");
    const wrapper = mount(EditorWorkspace, { global: { plugins: [pinia] } });

    expect(workspace.activeView).toBe("preview");
    expect(wrapper.get("[data-preview-image]").attributes("src")).toBe("blob:history-slide");
    expect(wrapper.find(".p4-animation-panel").exists()).toBe(false);
  });

  it("switches internal views without changing slide selection", async () => {
    const project = usePptProjectStore();
    project.upsertSlide(slide("slide-1", 1));
    const workspace = usePptWorkspaceStore();
    workspace.selectSlide("slide-1");
    const wrapper = mount(EditorWorkspace, { global: { plugins: [pinia] } });
    await wrapper.get('button[aria-label="预览演示文稿"]').trigger("click");
    expect(workspace.activeView).toBe("preview");
    expect(workspace.selectedSlideId).toBe("slide-1");
    expect(wrapper.get("[data-preview-panel]")).toBeTruthy();
  });

  it("emits close from the editor header", async () => {
    const wrapper = mount(EditorWorkspace, { global: { plugins: [pinia] } });
    await wrapper.get('button[aria-label="关闭编辑工作台"]').trigger("click");
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("shows concrete passed checks when validation has no issues", () => {
    const project = usePptProjectStore();
    project.upsertSlide(slide("slide-1", 1));
    project.setValidation({ score: 100, issues: [], checkedAt: "2026-07-17T00:00:00.000Z" });
    const wrapper = mount(ValidationPanel, { global: { plugins: [pinia] } });
    expect(wrapper.get("[data-validation-passed]").text()).toContain("通过");
    expect(wrapper.get("[data-validation-passed]").text()).toContain("幻灯片内容已生成");
  });

  it("separates Legacy blocking errors, errors and warnings", () => {
    const project = usePptProjectStore();
    project.setValidation({
      score: 0,
      checkedAt: "2026-07-18T00:00:00.000Z",
      issues: [
        { id: "blocking", severity: "error", blocking: true, message: "缺少关键文件" },
        { id: "error", severity: "error", message: "版式溢出" },
        { id: "warning", severity: "warning", message: "字体已替换" },
      ],
    });
    const wrapper = mount(ValidationPanel, { global: { plugins: [pinia] } });

    expect(wrapper.get("[data-validation-blocking]").text()).toContain("阻断项 1");
    expect(wrapper.get("[data-validation-errors]").text()).toContain("错误 1");
    expect(wrapper.get("[data-validation-warnings]").text()).toContain("警告 1");
  });

  it("explains the Legacy preview boundary when only a PPTX artifact exists", async () => {
    const project = usePptProjectStore();
    project.setProject({
      id: "project-1",
      title: "Legacy 文件",
      brief: { goal: "", audience: "", slideCount: 0, constraints: [] },
      outline: [],
      presentation: { aspectRatio: "16:9", slides: [] },
      theme: null,
      validation: null,
      exportArtifact: { fileId: 1, downloadUrl: "http://backend.test/file", size: 4, sha256: "abc", valid: true, warnings: [] },
      version: 1,
      createdAt: "2026-07-18T00:00:00.000Z",
      updatedAt: "2026-07-18T00:00:00.000Z",
    });
    const workspace = usePptWorkspaceStore();
    workspace.selectView("preview");
    const wrapper = mount(EditorWorkspace, { props: { incremental: false }, global: { plugins: [pinia] } });

    expect(wrapper.get("[data-legacy-preview-ready]").text()).toContain("暂不提供在线逐页预览");
  });

  it("does not promise incremental canvas or speaker notes while Legacy is generating", () => {
    usePptGenerationStore().status = "running";
    const wrapper = mount(EditorWorkspace, { props: { incremental: false }, global: { plugins: [pinia] } });

    expect(wrapper.get("[data-legacy-editor-unavailable]").text()).toContain("一次性生成");
    expect(wrapper.text()).not.toContain("页面内容会逐步出现");
    expect(wrapper.find("[data-speaker-notes]").exists()).toBe(false);
  });

  it("does not call a failed Legacy task still generating", () => {
    usePptGenerationStore().fail({ code: "LEGACY_VALIDATION_FAILED", message: "质检未通过", retryable: false });
    usePptProjectStore().setValidation({
      score: 0,
      checkedAt: "2026-07-18T00:00:00.000Z",
      issues: [{ id: "blocking", severity: "error", blocking: true, message: "文件不完整" }],
    });
    const wrapper = mount(EditorWorkspace, { props: { incremental: false }, global: { plugins: [pinia] } });

    expect(wrapper.get("[data-legacy-editor-unavailable]").text()).toContain("未通过检查");
    expect(wrapper.text()).not.toContain("正在一次性生成");
  });

  it("does not describe a non-validation Legacy failure as failed quality checks", () => {
    usePptProjectStore().setValidation({
      score: 100,
      checkedAt: "2026-07-17T00:00:00.000Z",
      issues: [],
    });
    usePptGenerationStore().fail({ code: "AUTHENTICATION_REQUIRED", message: "请重新登录", retryable: false });
    const wrapper = mount(EditorWorkspace, { props: { incremental: false }, global: { plugins: [pinia] } });

    expect(wrapper.get("[data-legacy-editor-unavailable]").text()).toContain("本次 PPTX 未生成");
    expect(wrapper.text()).not.toContain("未通过检查");
  });
});
