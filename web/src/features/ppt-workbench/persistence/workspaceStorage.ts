import type { PptActiveView, WorkspaceMode } from "../stores/pptWorkspace";

const LEGACY_STORAGE_KEY = "ppt-workbench:workspace:v1";
const keyForProject = (projectId: string) => `ppt-workbench:workspace:v2:${projectId}`;

export interface PersistedWorkspace {
  workspaceMode: Exclude<WorkspaceMode, "opening">;
  activeView: PptActiveView;
  selectedSlideId: string | null;
  chatPanelWidth: number;
  slideRailWidth: number;
  chatCollapsed: boolean;
  slideRailCollapsed: boolean;
  speakerNotesCollapsed?: boolean;
  editorZoom: number;
  conversationScrollTop: number;
  slideRailScrollTop: number;
  editorScrollTop: number;
}

const defaults = (): PersistedWorkspace => ({
  workspaceMode: "conversation",
  activeView: "editor",
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
});

const views: PptActiveView[] = ["brief", "outline", "slides", "editor", "preview", "validation"];
const number = (value: unknown, fallback: number, min: number, max: number) =>
  typeof value === "number" && Number.isFinite(value) ? Math.max(min, Math.min(value, max)) : fallback;

function sanitize(value: unknown): PersistedWorkspace {
  const input = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const base = defaults();
  return {
    workspaceMode: input.workspaceMode === "split-workbench" ? "split-workbench" : "conversation",
    activeView: views.includes(input.activeView as PptActiveView) ? input.activeView as PptActiveView : base.activeView,
    selectedSlideId: typeof input.selectedSlideId === "string" ? input.selectedSlideId : null,
    chatPanelWidth: number(input.chatPanelWidth, base.chatPanelWidth, 340, 520),
    slideRailWidth: number(input.slideRailWidth, base.slideRailWidth, 148, 240),
    chatCollapsed: input.chatCollapsed === true,
    slideRailCollapsed: input.slideRailCollapsed === true,
    speakerNotesCollapsed: input.speakerNotesCollapsed === true,
    editorZoom: number(input.editorZoom, base.editorZoom, 0.5, 1.5),
    conversationScrollTop: number(input.conversationScrollTop, 0, 0, Number.MAX_SAFE_INTEGER),
    slideRailScrollTop: number(input.slideRailScrollTop, 0, 0, Number.MAX_SAFE_INTEGER),
    editorScrollTop: number(input.editorScrollTop, 0, 0, Number.MAX_SAFE_INTEGER),
  };
}

export function loadWorkspaceState(projectId: string): PersistedWorkspace {
  if (typeof window === "undefined") return defaults();
  try {
    const scoped = window.localStorage.getItem(keyForProject(projectId));
    if (scoped) return sanitize(JSON.parse(scoped));
    const legacy = window.localStorage.getItem(LEGACY_STORAGE_KEY);
    return legacy ? sanitize(JSON.parse(legacy)) : defaults();
  } catch {
    return defaults();
  }
}

export function saveWorkspaceState(projectId: string, state: PersistedWorkspace) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(keyForProject(projectId), JSON.stringify(sanitize(state)));
}
