import { defineStore } from "pinia";

export type PptActiveView = "brief" | "outline" | "slides" | "editor" | "preview" | "validation";
export type WorkspaceMode = "conversation" | "opening" | "split-workbench";

export const usePptWorkspaceStore = defineStore("pptWorkspace", {
  state: () => ({
    projectId: null as string | null,
    workspaceMode: "conversation" as WorkspaceMode,
    activeView: "editor" as PptActiveView,
    selectedSlideId: null as string | null,
    chatPanelWidth: 392,
    slideRailWidth: 184,
    inspectorPanelWidth: 320,
    chatCollapsed: false,
    slideRailCollapsed: false,
    speakerNotesCollapsed: true,
    inspectorCollapsed: false,
    previewExpanded: false,
    editorZoom: 1,
    conversationScrollTop: 0,
    slideRailScrollTop: 0,
    editorScrollTop: 0,
  }),
  actions: {
    beginOpening() {
      if (this.workspaceMode !== "conversation") return;
      this.workspaceMode = "opening";
      if (!["editor", "preview", "validation"].includes(this.activeView)) this.activeView = "editor";
    },
    finishOpening() {
      if (this.workspaceMode === "opening") this.workspaceMode = "split-workbench";
    },
    closeWorkbench() { this.workspaceMode = "conversation"; },
    selectView(view: PptActiveView) { this.activeView = view; },
    selectSlide(slideId: string | null) { this.selectedSlideId = slideId; },
    setProject(projectId: string | null) { this.projectId = projectId; },
    setChatPanelWidth(width: number) { this.chatPanelWidth = Math.max(340, Math.min(width, 520)); },
    setSlideRailWidth(width: number) { this.slideRailWidth = Math.max(148, Math.min(width, 240)); },
    setEditorZoom(zoom: number) { this.editorZoom = Math.max(0.5, Math.min(zoom, 1.5)); },
    setInspectorPanelWidth(width: number) { this.inspectorPanelWidth = Math.max(260, Math.min(width, 560)); },
  },
});
