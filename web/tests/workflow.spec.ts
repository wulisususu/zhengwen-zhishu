import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { usePptWorkflow } from "../src/features/ppt-workbench/composables/usePptWorkflow";
import { MockPptWorkflowAdapter } from "../src/features/ppt-workbench/adapters/MockPptWorkflowAdapter";
import { LegacyPptMasterAdapter } from "../src/features/ppt-workbench/adapters/LegacyPptMasterAdapter";
import { usePptGenerationStore } from "../src/features/ppt-workbench/stores/pptGeneration";
import { usePptProjectStore } from "../src/features/ppt-workbench/stores/pptProject";
import { usePptWorkspaceStore } from "../src/features/ppt-workbench/stores/pptWorkspace";
import { usePptConversationStore } from "../src/features/ppt-workbench/stores/pptConversation";
import { usePptSourcesStore } from "../src/features/ppt-workbench/stores/pptSources";
import type { PptWorkflowEvent } from "../src/features/ppt-workbench/protocol/events";
import { byteStream, workflowCompletionFrames } from "./fixtures/legacySse";

const event = (taskId: string, sequence: number, type: PptWorkflowEvent["type"], payload: unknown): PptWorkflowEvent => ({
  eventId: `${taskId}-${sequence}-${type}`,
  taskId, projectId: "project-1", chatId: "chat-1", sequence, type, payload, timestamp: "2026-07-17T00:00:00.000Z",
});

describe("PPT workflow mainline", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("accepts a new task beginning at sequence one and ignores events from the replaced task", () => {
    const workflow = usePptWorkflow(new MockPptWorkflowAdapter(0));
    workflow.apply(event("task-old", 1, "task.started", {}));
    workflow.apply(event("task-old", 2, "assistant.text.delta", { text: "old" }));
    workflow.apply(event("task-new", 1, "task.started", {}));
    workflow.apply(event("task-old", 3, "task.completed", {}));

    const generation = usePptGenerationStore();
    expect(generation.task?.id).toBe("task-new");
    expect(generation.status).toBe("running");
  });

  it("clears source attachments before switching to another project", () => {
    const workflow = usePptWorkflow(new MockPptWorkflowAdapter(0));
    const sources = usePptSourcesStore();
    sources.upsert({ kind: "file", fileId: 12, filename: "brief.docx", fileType: ".docx", size: 1024, status: "done", progress: 100 });
    sources.setPolicy("ready_only");
    sources.setManifest([{ file_id: 12 }]);

    workflow.switchProject("project-2");

    expect(sources.items).toEqual([]);
    expect(sources.policy).toBe("parsed_only");
    expect(sources.manifest).toEqual([]);
  });

  it("applies a slide proposal only after approval", () => {
    const project = usePptProjectStore();
    project.upsertSlide({ id: "slide-1", index: 1, title: "初始标题", status: "ready", elements: [], userModifiedFields: [], revision: 1 });
    project.addProposal({ id: "proposal-1", taskId: "task-1", projectId: "project-1", target: "slide", targetId: "slide-1", baseProjectVersion: 1, status: "pending", summary: "修改标题", patch: { field: "title", to: "已批准标题" }, createdAt: "2026-07-17T00:00:00.000Z" });

    project.applyApprovedProposal("proposal-1");
    expect(project.slides[0]?.title).toBe("初始标题");
    project.approveAndApplyProposal("proposal-1");
    expect(project.slides[0]?.title).toBe("已批准标题");
    expect(project.proposals[0]?.status).toBe("applied");
  });

  it("emits a slide target identifier for a mock change proposal", async () => {
    const adapter = new MockPptWorkflowAdapter(0);
    const events: PptWorkflowEvent[] = [];
    for await (const item of adapter.start({ projectId: "project-1", chatId: "chat-1", prompt: "测试" })) events.push(item);
    const proposal = events.find((item) => item.type === "proposal.created");
    expect((proposal?.payload as { proposal: { targetId?: string } }).proposal.targetId).toBe("slide-2");
  });

  it("does not let workflow stage or slide completion preempt the user view", () => {
    const workflow = usePptWorkflow(new MockPptWorkflowAdapter(0));
    const workspace = usePptWorkspaceStore();
    workspace.workspaceMode = "split-workbench";
    workspace.selectView("preview");

    workflow.apply(event("task-1", 1, "task.started", {}));
    workflow.apply(event("task-1", 2, "slide.completed", { slide: { id: "slide-1", index: 1, title: "封面", status: "ready", elements: [], userModifiedFields: [], revision: 1 } }));
    workflow.apply(event("task-1", 3, "task.completed", {}));

    expect(workspace.workspaceMode).toBe("split-workbench");
    expect(workspace.activeView).toBe("preview");
  });

  it("stores normalized progress as a stage card instead of chat text", () => {
    const workflow = usePptWorkflow(new MockPptWorkflowAdapter(0));
    workflow.apply(event("task-1", 1, "task.started", { pageCount: 7 }));
    workflow.apply(event("task-1", 2, "assistant.text.delta", {
      text: "正在生成幻灯片",
      stage: "slides",
      progress: 35,
      presentation: "stage-card",
    }));

    const generation = usePptGenerationStore();
    const conversation = usePptConversationStore();
    expect(generation.task?.requestedPageCount).toBe(7);
    expect(conversation.messages).toContainEqual(expect.objectContaining({
      kind: "stage",
      content: "正在生成幻灯片",
      stage: "slides",
    }));
  });

  it("derives a safe frontend display title from the submitted prompt", async () => {
    const workflow = usePptWorkflow(new LegacyPptMasterAdapter({
      getAccessToken: () => "",
      pageCount: 1,
    }));
    usePptProjectStore().setProject({
      id: "project-1",
      title: "未命名 PPT",
      brief: { goal: "", audience: "", slideCount: 0, constraints: [] },
      outline: [],
      presentation: { aspectRatio: "16:9", slides: [] },
      theme: null,
      validation: null,
      version: 1,
      createdAt: "2026-07-18T00:00:00.000Z",
      updatedAt: "2026-07-18T00:00:00.000Z",
    });

    await workflow.start({ projectId: "project-1", chatId: "chat-1", prompt: "请帮我生成一份 人工智能安全年度报告 PPT" });

    expect(usePptProjectStore().project).toMatchObject({
      title: "人工智能安全年度报告",
      titleSource: "frontend-prompt",
    });
  });

  it("runs Legacy completion through the same reducer without preempting activeView", async () => {
    const project = usePptProjectStore();
    project.setProject({
      id: "project-1",
      title: "统一入口测试",
      brief: { goal: "", audience: "", slideCount: 1, constraints: [] },
      outline: [],
      presentation: { aspectRatio: "16:9", slides: [] },
      theme: null,
      validation: null,
      version: 1,
      createdAt: "2026-07-18T00:00:00.000Z",
      updatedAt: "2026-07-18T00:00:00.000Z",
    });
    const workspace = usePptWorkspaceStore();
    workspace.workspaceMode = "split-workbench";
    workspace.selectView("editor");
    const stream = byteStream([workflowCompletionFrames]);
    const adapter = new LegacyPptMasterAdapter({
      baseUrl: "http://backend.test:8000",
      getAccessToken: () => "token",
      requestIdFactory: () => "request-1",
      fetchImpl: vi.fn(async () => new Response(stream, { status: 200 })),
    });
    const workflow = usePptWorkflow(adapter);

    await workflow.start({ projectId: "project-1", chatId: "chat-1", prompt: "生成一页 PPT" });

    const generation = usePptGenerationStore();
    expect(generation.status).toBe("completed");
    expect(generation.task?.status).toBe("completed");
    expect(project.project?.exportArtifact).toMatchObject({ fileId: 594, warnings: ["字体已替换"] });
    expect(project.validation?.issues[0]?.severity).toBe("warning");
    expect(workspace.activeView).toBe("editor");
  });

  it("preserves interrupted semantics instead of fabricating a failed result", async () => {
    const adapter = new LegacyPptMasterAdapter({
      getAccessToken: () => "token",
      requestIdFactory: () => "request-1",
      fetchImpl: vi.fn(async () => { throw new TypeError("offline"); }),
    });
    const workflow = usePptWorkflow(adapter);

    await workflow.start({ projectId: "project-1", chatId: "chat-1", prompt: "生成 PPT" });

    const generation = usePptGenerationStore();
    expect(generation.status).toBe("interrupted");
    expect(generation.task?.status).toBe("interrupted");
    expect(generation.error?.code).toBe("LEGACY_NETWORK_INTERRUPTED");
  });

  it("clears the previous export artifact when a new task begins", () => {
    const project = usePptProjectStore();
    project.setProject({
      id: "project-1",
      title: "旧项目",
      brief: { goal: "", audience: "", slideCount: 1, constraints: [] },
      outline: [],
      presentation: { aspectRatio: "16:9", slides: [] },
      theme: null,
      validation: null,
      exportArtifact: { fileId: 1, downloadUrl: "http://backend.test/file", size: 4, sha256: "abc", valid: true, warnings: [] },
      version: 1,
      createdAt: "2026-07-18T00:00:00.000Z",
      updatedAt: "2026-07-18T00:00:00.000Z",
    });
    const workflow = usePptWorkflow(new MockPptWorkflowAdapter(0));

    workflow.apply(event("task-new", 1, "task.started", {}));

    expect(project.project?.exportArtifact).toBeNull();
  });
});
