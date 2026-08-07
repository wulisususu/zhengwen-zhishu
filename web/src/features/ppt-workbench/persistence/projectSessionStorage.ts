import type { PptChatMessage } from "../types/conversation";
import type { OutlineItem, PresentationTheme, Slide, ValidationResult } from "../types/presentation";
import type { PresentationProject } from "../types/project";
import type { PptChangeProposal } from "../types/proposal";
import type { GenerationStatus, PptGenerationTask, WorkflowError, WorkflowStage } from "../types/task";
import type { PptSourceAttachment, PptSourcePolicy } from "../stores/pptSources";

export interface PersistedProjectSession {
  projectId: string;
  project: PresentationProject | null;
  outline: OutlineItem[];
  slides: Slide[];
  theme: PresentationTheme | null;
  validation: ValidationResult | null;
  proposals: PptChangeProposal[];
  projectRevision: number;
  conversation: { chatId: string | null; messages: PptChatMessage[] };
  generation: {
    task: PptGenerationTask | null;
    workflowStage: WorkflowStage;
    status: GenerationStatus;
    progress: number;
    actualProgress?: number;
    displayProgress?: number;
    error: WorkflowError | null;
  };
  sources?: { items: PptSourceAttachment[]; policy: PptSourcePolicy; manifest: Record<string, unknown>[] };
}

export interface RecentProjectSummary { projectId: string; title: string; updatedAt: string }

const sessionKey = (projectId: string) => `ppt-workbench:session:v1:${projectId}`;
const recentKey = "ppt-workbench:recent:v1";

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

export function saveProjectSession(projectId: string, session: PersistedProjectSession) {
  if (typeof window === "undefined" || session.projectId !== projectId) return;
  window.localStorage.setItem(sessionKey(projectId), JSON.stringify(session));
  const summary: RecentProjectSummary = {
    projectId,
    title: session.project?.title || "未命名 PPT",
    updatedAt: session.project?.updatedAt || new Date().toISOString(),
  };
  const recent = loadRecentProjectSummaries().filter((item) => item.projectId !== projectId);
  window.localStorage.setItem(recentKey, JSON.stringify([summary, ...recent].slice(0, 8)));
}

export function loadProjectSession(projectId: string): PersistedProjectSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(sessionKey(projectId));
    if (!raw) return null;
    const session = JSON.parse(raw) as PersistedProjectSession;
    if (session.projectId !== projectId || !Array.isArray(session.slides) || !Array.isArray(session.conversation?.messages)) return null;
    const restored = clone(session);
    restored.slides = restored.slides.map((slide) => ({
      ...slide,
      ...(typeof slide.previewUrl === "string" && slide.previewUrl.startsWith("blob:") ? { previewUrl: undefined } : {}),
      ...(typeof slide.thumbnailUrl === "string" && slide.thumbnailUrl.startsWith("blob:") ? { thumbnailUrl: undefined } : {}),
    }));
    restored.conversation.messages = restored.conversation.messages.map((message) => ({ ...message, streaming: false }));
    if (restored.generation.status === "running" || restored.generation.status === "queued") {
      restored.generation.status = "failed";
      restored.generation.workflowStage = "failed";
      restored.generation.error = {
        code: "WORKFLOW_RESTORE_INTERRUPTED",
        message: "刷新后生成连接已中断，可重新提交需求继续生成。",
        retryable: true,
      };
    }
    if (restored.generation.task?.requestedPageCount) {
      const count = restored.generation.task.requestedPageCount;
      restored.outline = restored.outline.slice(0, count);
      restored.slides = restored.slides.filter((slide) => slide.index <= count);
      restored.project!.outline = restored.outline;
      restored.project!.presentation.slides = restored.slides;
      restored.project!.brief.slideCount = count;
    }
    return restored;
  } catch {
    return null;
  }
}

export function loadRecentProjectSummaries(): RecentProjectSummary[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(recentKey) ?? "[]") as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is RecentProjectSummary => Boolean(
      item && typeof item === "object" &&
      typeof (item as RecentProjectSummary).projectId === "string" &&
      typeof (item as RecentProjectSummary).title === "string" &&
      typeof (item as RecentProjectSummary).updatedAt === "string",
    )).slice(0, 8);
  } catch {
    return [];
  }
}
