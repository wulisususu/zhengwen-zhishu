import { watch } from "vue";
import { loadWorkspaceState, saveWorkspaceState } from "../persistence/workspaceStorage";
import { usePptWorkspaceStore } from "../stores/pptWorkspace";

export function useWorkspacePersistence(projectId: string) {
  const workspace = usePptWorkspaceStore();
  if (typeof window !== "undefined") {
    const hasScoped = window.localStorage.getItem(`ppt-workbench:workspace:v2:${projectId}`) !== null;
    const hasLegacy = window.localStorage.getItem("ppt-workbench:workspace:v1") !== null;
    if (hasScoped || hasLegacy) Object.assign(workspace, loadWorkspaceState(projectId));
  }
  return watch(() => ({
    workspaceMode: workspace.workspaceMode === "opening" ? "split-workbench" as const : workspace.workspaceMode,
    activeView: workspace.activeView,
    selectedSlideId: workspace.selectedSlideId,
    chatPanelWidth: workspace.chatPanelWidth,
    slideRailWidth: workspace.slideRailWidth,
    chatCollapsed: workspace.chatCollapsed,
    slideRailCollapsed: workspace.slideRailCollapsed,
    speakerNotesCollapsed: workspace.speakerNotesCollapsed,
    editorZoom: workspace.editorZoom,
    conversationScrollTop: workspace.conversationScrollTop,
    slideRailScrollTop: workspace.slideRailScrollTop,
    editorScrollTop: workspace.editorScrollTop,
  }), (state) => saveWorkspaceState(projectId, state), { deep: true });
}
