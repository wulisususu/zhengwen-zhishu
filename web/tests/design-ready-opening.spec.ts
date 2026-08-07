import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { MockPptWorkflowAdapter } from "../src/features/ppt-workbench/adapters/MockPptWorkflowAdapter";
import { usePptWorkflow } from "../src/features/ppt-workbench/composables/usePptWorkflow";
import type { PptWorkflowEvent } from "../src/features/ppt-workbench/protocol/events";
import { usePptWorkspaceStore } from "../src/features/ppt-workbench/stores/pptWorkspace";

const event = (taskId: string, sequence: number, type: PptWorkflowEvent["type"], payload: unknown): PptWorkflowEvent => ({
  eventId: `${taskId}-${sequence}-${type}`,
  taskId,
  projectId: "project-1",
  chatId: "chat-1",
  sequence,
  type,
  payload,
  timestamp: "2026-07-19T00:00:00.000Z",
});

describe("design-ready host opening policy", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("keeps progress in the full conversation", () => {
    const workflow = usePptWorkflow(new MockPptWorkflowAdapter(0));
    const workspace = usePptWorkspaceStore();
    workflow.apply(event("task-1", 1, "task.started", {}));
    workflow.apply(event("task-1", 2, "assistant.text.delta", {
      text: "正在分析需求",
      stage: "understanding",
      progress: 10,
      presentation: "stage-card",
    }));
    expect(workspace.workspaceMode).toBe("conversation");
  });

  it("opens only for the current task design.ready milestone", () => {
    const workflow = usePptWorkflow(new MockPptWorkflowAdapter(0));
    const workspace = usePptWorkspaceStore();
    workflow.apply(event("task-1", 1, "task.started", {}));
    workflow.apply(event("task-1", 2, "design.ready", { specification: {} }));
    expect(workspace.workspaceMode).toBe("opening");
  });

  it("consumes design.ready once", () => {
    const workflow = usePptWorkflow(new MockPptWorkflowAdapter(0));
    const workspace = usePptWorkspaceStore();
    workflow.apply(event("task-1", 1, "task.started", {}));
    workflow.apply(event("task-1", 2, "design.ready", {}));
    workspace.finishOpening();
    workflow.closeWorkbench();
    workflow.apply(event("task-1", 3, "design.ready", {}));
    expect(workspace.workspaceMode).toBe("conversation");
  });

  it("ignores design.ready from a replaced task", () => {
    const workflow = usePptWorkflow(new MockPptWorkflowAdapter(0));
    const workspace = usePptWorkspaceStore();
    workflow.apply(event("task-old", 1, "task.started", {}));
    workflow.apply(event("task-new", 1, "task.started", {}));
    workflow.apply(event("task-old", 2, "design.ready", {}));
    expect(workspace.workspaceMode).toBe("conversation");
  });

  it("does not reopen after the user closes the current task", () => {
    const workflow = usePptWorkflow(new MockPptWorkflowAdapter(0));
    const workspace = usePptWorkspaceStore();
    workflow.apply(event("task-1", 1, "task.started", {}));
    workflow.openWorkbench();
    workspace.finishOpening();
    workflow.closeWorkbench();
    workflow.apply(event("task-1", 2, "design.ready", {}));
    expect(workspace.workspaceMode).toBe("conversation");
  });

  it("keeps conversation when planning fails before design.ready", () => {
    const workflow = usePptWorkflow(new MockPptWorkflowAdapter(0));
    const workspace = usePptWorkspaceStore();
    workflow.apply(event("task-1", 1, "task.started", {}));
    workflow.apply(event("task-1", 2, "task.failed", {
      error: { code: "PLANNING_FAILED", message: "规划失败", retryable: false },
    }));
    expect(workspace.workspaceMode).toBe("conversation");
  });

  it("does not let validation or completion change workspace mode", () => {
    const workflow = usePptWorkflow(new MockPptWorkflowAdapter(0));
    const workspace = usePptWorkspaceStore();
    workflow.apply(event("task-1", 1, "task.started", {}));
    workflow.apply(event("task-1", 2, "validation.completed", {
      result: { score: 100, issues: [], checkedAt: "2026-07-19T00:00:00.000Z" },
    }));
    workflow.apply(event("task-1", 3, "task.completed", {}));
    expect(workspace.workspaceMode).toBe("conversation");
  });
});
