import { shouldApplyWorkflowEvent } from "../protocol/eventReducer";
import type { PptWorkflowEvent } from "../protocol/events";
import type { PptWorkflowAdapter, StartPptWorkflowInput } from "../adapters/PptWorkflowAdapter";
import { usePptConversationStore } from "../stores/pptConversation";
import { usePptGenerationStore } from "../stores/pptGeneration";
import { usePptProjectStore } from "../stores/pptProject";
import { usePptSourcesStore } from "../stores/pptSources";
import { usePptWorkspaceStore } from "../stores/pptWorkspace";
import type { PptGenerationTask, WorkflowError, WorkflowStage } from "../types/task";
import { derivePromptDisplayTitle } from "../utils/promptTitle";
import { createClientUuid } from "../utils/uuid";

const stageForEvent: Partial<Record<PptWorkflowEvent["type"], WorkflowStage>> = {
  "task.started": "understanding",
  "outline.item.added": "outline",
  "outline.ready": "outline",
  "design.ready": "design",
  "slide.started": "slides",
  "slide.completed": "slides",
  "validation.completed": "validation",
  "export.ready": "export",
};

export function usePptWorkflow(adapter: PptWorkflowAdapter) {
  const conversation = usePptConversationStore();
  const generation = usePptGenerationStore();
  const project = usePptProjectStore();
  const sources = usePptSourcesStore();
  const workspace = usePptWorkspaceStore();
  let autoOpenConsumedTaskId: string | null = null;
  let userClosedTaskId: string | null = null;
  let currentProjectId = "";
  let activeTaskId: string | null = null;

  async function start(input: StartPptWorkflowInput) {
    currentProjectId = input.projectId;
    if (project.project && (!project.project.title || project.project.title === "未命名 PPT" || project.project.titleSource === "frontend-prompt")) {
      project.setDisplayTitle(derivePromptDisplayTitle(input.prompt), "frontend-prompt");
    }
    const pageCount = input.pageCount ?? project.project?.brief.slideCount ?? generation.task?.requestedPageCount ?? 8;
    conversation.append({
      id: `user-${createClientUuid()}`,
      role: "user",
      content: `${input.prompt}\n将按${pageCount}页生成`,
      createdAt: new Date().toISOString(),
    });
    conversation.draft = "";
    try {
      for await (const event of adapter.start(input)) {
        if (event.projectId !== currentProjectId) break;
        apply(event);
      }
    } catch (cause) {
      if (input.projectId === currentProjectId) {
        generation.fail({ code: "WORKFLOW_TRANSPORT_FAILED", message: cause instanceof Error ? cause.message : "工作流连接失败", retryable: true });
      }
    }
  }

  function apply(event: PptWorkflowEvent) {
    if (currentProjectId && event.projectId && event.projectId !== currentProjectId) return;
    if (event.type === "task.started" && generation.task?.id !== event.taskId) {
      activeTaskId = event.taskId;
      const startedPayload = event.payload as { pageCount?: unknown };
      const pageCount = Number(startedPayload.pageCount);
      const task: PptGenerationTask = {
        id: event.taskId,
        projectId: event.projectId,
        chatId: event.chatId,
        stage: "understanding",
        status: "running",
        progress: 0,
        lastAppliedSequence: 0,
        ...(Number.isInteger(pageCount) && pageCount > 0 ? { requestedPageCount: pageCount } : {}),
        startedAt: event.timestamp,
      };
      generation.start(task);
      autoOpenConsumedTaskId = null;
      userClosedTaskId = null;
      project.clearExportArtifact();
      project.resetGenerationData();
      conversation.chatId = event.chatId;
      generation.acceptEvent(event.eventId, event.sequence);
      return;
    }

    if (!generation.task || generation.task.id !== event.taskId) return;
    const decision = shouldApplyWorkflowEvent(event, generation.lastAppliedSequence, generation.seenEventIds);
    if (!decision.accepted) return;

    generation.acceptEvent(event.eventId, event.sequence);
    const stage = stageForEvent[event.type];
    if (stage) {
      generation.workflowStage = stage;
      if (generation.task) generation.task.stage = stage;
    }

    const payload = event.payload as Record<string, unknown>;
    switch (event.type) {
      case "assistant.text.delta": {
        if (payload.presentation === "stage-card" && typeof payload.stage === "string"
          && ["understanding", "outline", "design", "slides", "validation", "export"].includes(payload.stage)) {
          conversation.upsertStage(
            event.taskId,
            payload.stage as WorkflowStage,
            String(payload.text ?? ""),
            typeof payload.progress === "number" ? payload.progress : undefined,
          );
        } else {
          conversation.appendDelta(event.taskId, String(payload.text ?? ""));
        }
        if (typeof payload.progress === "number") {
          generation.setActualProgress(payload.progress);
        }
        if (typeof payload.stage === "string"
          && ["understanding", "outline", "design", "slides", "validation", "export"].includes(payload.stage)) {
          generation.workflowStage = payload.stage as WorkflowStage;
          if (generation.task) generation.task.stage = generation.workflowStage;
        }
        break;
      }
      case "brief.ready": if (project.project) project.project.brief = payload.brief as typeof project.project.brief; break;
      case "outline.item.added": project.addOutlineItem(payload.item as never); break;
      case "outline.ready": project.setOutline(payload.outline as never); break;
      case "design.ready": {
        if (payload.theme) project.setTheme(payload.theme as never);
        const shouldOpen = workspace.workspaceMode === "conversation"
          && autoOpenConsumedTaskId !== event.taskId
          && userClosedTaskId !== event.taskId;
        autoOpenConsumedTaskId = event.taskId;
        if (shouldOpen) workspace.beginOpening();
        break;
      }
      case "slide.started": case "slide.completed": case "slide.failed":
        if (payload.slide) project.upsertSlide(payload.slide as never);
        if (event.type === "slide.completed") {
          const total = generation.task?.requestedPageCount ?? project.project?.brief.slideCount ?? 1;
          const completed = project.slides.filter((slide) => slide.status === "ready").length;
          generation.setActualProgress(25 + (completed / total) * 57);
        }
        break;
      case "proposal.created": project.addProposal(payload.proposal as never); break;
      case "validation.completed": project.setValidation((payload.result ?? payload.validation) as never); break;
      case "export.ready": {
        if (payload.validation) project.setValidation(payload.validation as never);
        if (payload.artifact) {
          project.setExportArtifact(payload.artifact as never);
          const artifact = payload.artifact as { slideCount?: unknown };
          if (Number.isInteger(artifact.slideCount) && project.project) project.project.brief.slideCount = Number(artifact.slideCount);
        }
        break;
      }
      case "task.completed": conversation.finishStream(); generation.complete(); break;
      case "task.cancelled": conversation.finishStream(); generation.cancel(); break;
      case "task.failed": {
        conversation.finishStream();
        const error = (payload.error ?? payload) as WorkflowError;
        const normalizedError: WorkflowError = {
          code: error.code ?? "WORKFLOW_FAILED",
          message: error.message ?? "工作流失败",
          retryable: error.retryable ?? false,
          details: error.details,
          httpStatus: error.httpStatus,
          retryAfterSeconds: error.retryAfterSeconds,
        };
        if (payload.terminalStatus === "interrupted") generation.interrupt(normalizedError);
        else generation.fail(normalizedError);
        break;
      }
    }
  }

  async function downloadLatest() {
    const artifact = project.project?.exportArtifact;
    if (!artifact || !adapter.download) throw new Error("当前工作流没有可下载的 PPT 文件");
    return adapter.download(artifact, project.project?.title ?? "演示文稿");
  }

  function openWorkbench() {
    workspace.beginOpening();
  }

  function closeWorkbench() {
    if (generation.task) userClosedTaskId = generation.task.id;
    workspace.closeWorkbench();
  }

  function switchProject(projectId: string) {
    if (activeTaskId) {
      try { adapter.disconnect?.(activeTaskId); } catch { /* best-effort cancellation */ }
    }
    activeTaskId = null;
    currentProjectId = projectId;
    generation.stopProgressAnimation();
    project.$reset();
    conversation.$reset();
    generation.$reset();
    sources.$reset();
    autoOpenConsumedTaskId = null;
    userClosedTaskId = null;
  }

  return {
    start,
    apply,
    downloadLatest,
    ...(adapter.loadHistoryProject ? { loadHistoryProject: adapter.loadHistoryProject.bind(adapter) } : {}),
    restoreSlideAssets: adapter.restoreSlideAssets?.bind(adapter),
    openWorkbench,
    closeWorkbench,
    switchProject,
    capabilities: adapter.capabilities,
  };
}

export type PptWorkflowController = ReturnType<typeof usePptWorkflow>;
