import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import ObjectToolbar from "../src/features/ppt-workbench/components/editor/ObjectToolbar.vue";
import SpeakerNotesPanel from "../src/features/ppt-workbench/components/editor/SpeakerNotesPanel.vue";
import EditorToolbar from "../src/features/ppt-workbench/components/editor/EditorToolbar.vue";
import SlideList from "../src/features/ppt-workbench/components/slides/SlideList.vue";
import ChatPanel from "../src/features/ppt-workbench/components/chat/ChatPanel.vue";
import PptResultCard from "../src/features/ppt-workbench/components/chat/PptResultCard.vue";
import { usePptProjectStore } from "../src/features/ppt-workbench/stores/pptProject";
import { usePptWorkspaceStore } from "../src/features/ppt-workbench/stores/pptWorkspace";
import { usePptEditorStore } from "../src/features/ppt-workbench/stores/pptEditor";
import { saveWorkspaceState, loadWorkspaceState } from "../src/features/ppt-workbench/persistence/workspaceStorage";
import { resolveWorkbenchLayout } from "../src/features/ppt-workbench/utils/resolveWorkbenchLayout";
import { MockPptWorkflowAdapter } from "../src/features/ppt-workbench/adapters/MockPptWorkflowAdapter";
import type { Slide } from "../src/features/ppt-workbench/types/presentation";

const cssPath = resolve(process.cwd(), "src/features/ppt-workbench/visual/visual-tokens.css");
const cssPathGrid = resolve(process.cwd(), "src/features/ppt-workbench/ppt-workbench.css");

const slide = (id: string, index: number, overrides: Partial<Slide> = {}): Slide => ({
  id,
  index,
  status: "ready",
  title: `第 ${index} 页`,
  elements: [],
  userModifiedFields: [],
  revision: 1,
  speakerNotes: `第 ${index} 页演讲稿`,
  ...overrides,
});

describe("visual polish — object toolbar", () => {
  it("renders a single-row icon+label toolbar with stable actions", () => {
    const wrapper = mount(ObjectToolbar, { props: { hasSelection: false, selectionType: "" } });
    expect(wrapper.attributes("role")).toBe("toolbar");
    for (const label of ["文本", "图片", "图表", "表格", "排列", "更多"]) {
      expect(wrapper.text()).toContain(label);
    }
    // Internal element node-type identifiers must not leak as raw labels.
    // (The shape submenu legitimately offers 矩形/椭圆 in Chinese; raw
    // English node ids like "rect"/"ellipse" would indicate leakage.)
    const lower = wrapper.text().toLowerCase();
    expect(lower).not.toContain("rect");
    expect(lower).not.toContain("ellipse");
    expect(wrapper.text()).not.toContain("个元素");
  });

  it("emits the add-text action from the primary text button", async () => {
    const wrapper = mount(ObjectToolbar, { props: { hasSelection: true, selectionType: "image" } });
    await wrapper.get("button:not([disabled])").trigger("click");
    expect(wrapper.emitted("action")?.[0]).toEqual(["add-text"]);
  });

  it("disables arrangement actions until a selection exists", () => {
    const wrapper = mount(ObjectToolbar, { props: { hasSelection: false, selectionType: "" } });
    const arrangeBtn = wrapper.findAll("button").find((b) => b.text().includes("置于顶层"));
    expect(arrangeBtn).toBeTruthy();
    expect(arrangeBtn?.attributes("disabled")).toBeDefined();
  });

  it("enables arrangement actions once an element is selected", () => {
    const wrapper = mount(ObjectToolbar, { props: { hasSelection: true, selectionType: "other" } });
    const arrangeBtn = wrapper.findAll("button").find((b) => b.text().includes("置于顶层"));
    expect(arrangeBtn?.attributes("disabled")).toBeUndefined();
  });
});

describe("visual polish — editor top bar", () => {
  let pinia: ReturnType<typeof createPinia>;
  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it("renders view tabs and stable aria-labelled actions", () => {
    const wrapper = mount(EditorToolbar, { props: { activeView: "editor" }, global: { plugins: [pinia] } });
    expect(wrapper.text()).toContain("编辑");
    expect(wrapper.text()).toContain("预览");
    expect(wrapper.text()).toContain("检查");
    expect(wrapper.get('button[aria-label="关闭编辑工作台"]')).toBeTruthy();
    expect(wrapper.get('button[aria-label="下载 PPT"]')).toBeTruthy();
  });
});

describe("visual polish — speaker notes drawer", () => {
  let pinia: ReturnType<typeof createPinia>;
  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it("is collapsed by default but keeps notes in the DOM", () => {
    const project = usePptProjectStore();
    project.upsertSlide(slide("slide-1", 1));
    usePptWorkspaceStore().selectSlide("slide-1");
    const wrapper = mount(SpeakerNotesPanel, { global: { plugins: [pinia] } });
    expect(wrapper.get("[data-speaker-notes]")).toBeTruthy();
    expect(wrapper.text()).toContain("第 1 页演讲稿");
    expect(wrapper.find("#speaker-notes-body").attributes("style")).toContain("max-height: 0px");
  });

  it("expands the drawer on toggle", async () => {
    const project = usePptProjectStore();
    project.upsertSlide(slide("slide-1", 1));
    usePptWorkspaceStore().selectSlide("slide-1");
    const wrapper = mount(SpeakerNotesPanel, { global: { plugins: [pinia] } });
    await wrapper.get("button").trigger("click");
    expect(wrapper.find("#speaker-notes-body").attributes("style")).toContain("max-height: 240px");
  });
});

describe("visual polish — slide rail thumbnails", () => {
  let pinia: ReturnType<typeof createPinia>;
  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it("renders real 16:9 thumbnails from the editor document without element counts", () => {
    const project = usePptProjectStore();
    project.upsertSlide(slide("slide-1", 1, { thumbnailUrl: "http://cdn.test/s1.png" }));
    const editor = usePptEditorStore();
    editor.document = {
      project_id: "p1",
      base_task_id: "b1",
      slides: [{ slide_id: "slide-1", order: 1, width: 1280, height: 720, elements: [] }],
    };
    editor.selectedSlideId = "slide-1";
    const wrapper = mount(SlideList, { props: { incremental: true }, global: { plugins: [pinia] } });
    expect(wrapper.find("[data-slide-thumbnail-image]").exists()).toBe(true);
    // Internal element counts / node names must not leak into the UI.
    expect(wrapper.text()).not.toContain("个元素");
    expect(wrapper.text().toLowerCase()).not.toContain("rect");
    expect(wrapper.text().toLowerCase()).not.toContain("ellipse");
  });
});

describe("visual polish — speaker notes collapse persistence", () => {
  let pinia: ReturnType<typeof createPinia>;
  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it("drives collapse from the persisted workspace store (not a local ref)", async () => {
    const project = usePptProjectStore();
    project.upsertSlide(slide("slide-1", 1, { speakerNotes: "备注内容" }));
    usePptWorkspaceStore().selectSlide("slide-1");
    const wrapper = mount(SpeakerNotesPanel, { global: { plugins: [pinia] } });
    // default collapsed
    expect(wrapper.find("#speaker-notes-body").attributes("style")).toContain("max-height: 0px");
    await wrapper.get("button").trigger("click");
    // toggle writes to the store so it can be persisted across reloads
    expect(usePptWorkspaceStore().speakerNotesCollapsed).toBe(false);
    expect(wrapper.find("#speaker-notes-body").attributes("style")).toContain("max-height: 240px");
  });

  it("round-trips speakerNotesCollapsed through workspace storage", () => {
    const state = {
      workspaceMode: "split-workbench" as const,
      activeView: "editor" as const,
      selectedSlideId: null,
      chatPanelWidth: 392,
      slideRailWidth: 184,
      chatCollapsed: false,
      slideRailCollapsed: false,
      speakerNotesCollapsed: true,
      editorZoom: 1,
      conversationScrollTop: 0,
      slideRailScrollTop: 0,
      editorScrollTop: 0,
    };
    saveWorkspaceState("proj-persist", state);
    const loaded = loadWorkspaceState("proj-persist");
    expect(loaded.speakerNotesCollapsed).toBe(true);
    expect(loaded.chatCollapsed).toBe(false);
  });
});

describe("visual polish — save / export / conflict status", () => {
  let pinia: ReturnType<typeof createPinia>;
  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it("shows a version-conflict (409) status with danger tone", () => {
    const editor = usePptEditorStore();
    editor.savingState = "conflict";
    const wrapper = mount(EditorToolbar, { props: { activeView: "editor" }, global: { plugins: [pinia] } });
    expect(wrapper.text()).toContain("版本冲突");
    expect(wrapper.get(".ppt-status").classes()).toContain("ppt-status-danger");
  });

  it("shows an exporting status with busy tone", () => {
    const editor = usePptEditorStore();
    editor.savingState = "saved";
    editor.exportState = "exporting";
    const wrapper = mount(EditorToolbar, { props: { activeView: "editor" }, global: { plugins: [pinia] } });
    expect(wrapper.text()).toContain("导出中");
    expect(wrapper.get(".ppt-status").classes()).toContain("ppt-status-busy");
  });

  it("announces status changes to assistive tech via aria-live", () => {
    const wrapper = mount(EditorToolbar, { props: { activeView: "editor" }, global: { plugins: [pinia] } });
    const status = wrapper.get(".ppt-status");
    expect(status.attributes("role")).toBe("status");
    expect(status.attributes("aria-live")).toBe("polite");
  });
});

describe("visual polish — no internal id leakage in normal UI", () => {
  let pinia: ReturnType<typeof createPinia>;
  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  function assertNoLeak(wrapper: ReturnType<typeof mount>) {
    const text = wrapper.text();
    const lower = text.toLowerCase();
    expect(text).not.toContain("个元素");
    expect(lower).not.toContain("rect");
    expect(lower).not.toContain("ellipse");
    expect(lower).not.toMatch(/图片\d+/);
    expect(lower).not.toMatch(/db[:\s]/);
  }

  it("keeps ChatPanel / LandingComposer free of element ids", () => {
    const wrapper = mount(ChatPanel, { props: { mode: "conversation", running: false }, global: { plugins: [pinia] } });
    assertNoLeak(wrapper);
  });

  it("keeps the result card free of element ids", () => {
    const wrapper = mount(PptResultCard, {
      props: {
        title: "演示文稿",
        completed: true,
        readySlides: 3,
        pageCount: 3,
        incrementalSlides: true,
        downloadAvailable: true,
        warnings: [],
        validationIssues: [],
      },
      global: { plugins: [pinia] },
    });
    assertNoLeak(wrapper);
  });
});

describe("visual polish — responsive layout resolver", () => {
  it("classifies the documented breakpoint tiers", () => {
    expect(resolveWorkbenchLayout(1920).tier).toBe("wide");
    expect(resolveWorkbenchLayout(1600).tier).toBe("wide");
    expect(resolveWorkbenchLayout(1440).tier).toBe("standard");
    expect(resolveWorkbenchLayout(1366).tier).toBe("standard");
    expect(resolveWorkbenchLayout(1280).tier).toBe("standard");
    expect(resolveWorkbenchLayout(1024).tier).toBe("narrow");
    expect(resolveWorkbenchLayout(800).tier).toBe("compact");
  });

  it("caps side-panel widths so columns never overflow at 1024px", () => {
    const layout = resolveWorkbenchLayout(1024);
    expect(layout.maxChat + layout.maxRail).toBeLessThan(1024);
  });
});

describe("visual polish — toolbar never goes vertical", () => {
  it("uses a nowrap, horizontally-scrollable flex row (.ppt-tool-row)", () => {
    const wrapper = mount(ObjectToolbar, { props: { hasSelection: false, selectionType: "" } });
    expect(wrapper.classes()).toContain("ppt-tool-row");
  });

  it("guarantees nowrap + flex in the token stylesheet (no per-glyph vertical text)", () => {
    const css = readFileSync(cssPath, "utf8");
    const toolRow = css.slice(css.indexOf(".ppt-tool-row"));
    expect(toolRow).toContain("white-space: nowrap");
    expect(toolRow).toContain("display: flex");
    expect(toolRow).toContain("overflow-x: auto");
  });

  it("lets the editor column shrink (minmax(0,1fr)) to avoid overflow at 1366", () => {
    const css = readFileSync(cssPathGrid, "utf8");
    expect(css).toContain("minmax(0, 1fr)");
  });
});

describe("visual polish — workflow adapter entries remain wired", () => {
  it("exposes flat, legacy and structured adapters without breaking", async () => {
    expect(MockPptWorkflowAdapter).toBeDefined();
    const legacy = await import("../src/features/ppt-workbench/adapters/LegacyPptMasterAdapter");
    const http = await import("../src/features/ppt-workbench/adapters/HttpPptWorkflowAdapter");
    expect(legacy.LegacyPptMasterAdapter).toBeDefined();
    expect(http.HttpPptWorkflowAdapter).toBeDefined();
  });
});
