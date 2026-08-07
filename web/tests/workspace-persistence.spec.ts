import { beforeEach, describe, expect, it } from "vitest";
import {
  loadWorkspaceState,
  saveWorkspaceState,
} from "../src/features/ppt-workbench/persistence/workspaceStorage";
import {
  loadProjectSession,
  loadRecentProjectSummaries,
  saveProjectSession,
  type PersistedProjectSession,
} from "../src/features/ppt-workbench/persistence/projectSessionStorage";

const session = (status: "completed" | "running" = "completed"): PersistedProjectSession => ({
  projectId: "project-1",
  project: {
    id: "project-1",
    title: "年度复盘",
    brief: { goal: "年度复盘", audience: "管理层", slideCount: 4, constraints: [] },
    outline: [],
    presentation: { aspectRatio: "16:9", slides: [] },
    theme: null,
    validation: null,
    version: 1,
    createdAt: "2026-07-17T00:00:00.000Z",
    updatedAt: "2026-07-17T00:00:00.000Z",
  },
  outline: [],
  slides: [{ id: "slide-1", index: 1, title: "封面", status: "ready", elements: [], userModifiedFields: [], revision: 1 }],
  theme: null,
  validation: null,
  proposals: [],
  projectRevision: 1,
  conversation: {
    chatId: "chat-1",
    messages: [{ id: "message-1", role: "assistant", content: "正在生成", createdAt: "2026-07-17T00:00:00.000Z", streaming: true }],
  },
  generation: {
    task: null,
    workflowStage: status === "running" ? "slides" : "completed",
    status,
    progress: status === "running" ? 50 : 100,
    error: null,
  },
});

describe("workspace persistence", () => {
  beforeEach(() => localStorage.clear());

  it("migrates v1 UI state into conversation defaults", () => {
    localStorage.setItem("ppt-workbench:workspace:v1", JSON.stringify({ activeView: "preview", selectedSlideId: "slide-2", chatPanelWidth: 420 }));
    const state = loadWorkspaceState("project-1");
    expect(state.workspaceMode).toBe("conversation");
    expect(state.activeView).toBe("preview");
    expect(state.chatPanelWidth).toBe(420);
  });

  it("keeps workspace state isolated by project id", () => {
    saveWorkspaceState("project-1", { workspaceMode: "split-workbench", activeView: "editor", selectedSlideId: "slide-1", chatPanelWidth: 400, slideRailWidth: 180, chatCollapsed: false, slideRailCollapsed: false, editorZoom: 0.9, conversationScrollTop: 20, slideRailScrollTop: 30, editorScrollTop: 40 });
    expect(loadWorkspaceState("project-1").workspaceMode).toBe("split-workbench");
    expect(loadWorkspaceState("project-2").workspaceMode).toBe("conversation");
  });

  it("restores project content and normalizes streaming messages", () => {
    saveProjectSession("project-1", session());
    const restored = loadProjectSession("project-1");
    expect(restored?.slides[0]?.status).toBe("ready");
    expect(restored?.conversation.messages[0]?.streaming).toBe(false);
    expect(loadRecentProjectSummaries()[0]?.title).toBe("年度复盘");
  });

  it("preserves PPT source IDs, parser status, policy, and manifest per project", () => {
    const withSources = {
      ...session(),
      sources: {
        items: [{ kind: "file" as const, fileId: 12, filename: "brief.docx", fileType: ".docx", size: 1024, status: "done" as const, progress: 100, parsedFileId: 22 }],
        policy: "parsed_only" as const,
        manifest: [{ file_id: 12, filename: "brief.docx", chunk_id: 3 }],
      },
    };
    saveProjectSession("project-1", withSources);
    saveProjectSession("project-2", { ...session(), projectId: "project-2", project: { ...session().project!, id: "project-2" } });
    expect(loadProjectSession("project-1")?.sources?.items[0]?.fileId).toBe(12);
    expect(loadProjectSession("project-1")?.sources?.manifest[0]?.chunk_id).toBe(3);
    expect(loadProjectSession("project-2")?.sources).toBeUndefined();
  });

  it("normalizes a running snapshot to a retryable interruption", () => {
    saveProjectSession("project-1", session("running"));
    const restored = loadProjectSession("project-1");
    expect(restored?.generation.status).toBe("failed");
    expect(restored?.generation.error?.code).toBe("WORKFLOW_RESTORE_INTERRUPTED");
    expect(restored?.slides).toHaveLength(1);
  });

  it("ignores malformed project snapshots", () => {
    localStorage.setItem("ppt-workbench:session:v1:project-1", "{bad json");
    expect(loadProjectSession("project-1")).toBeNull();
  });
});
