import type { OutlineItem, PresentationTheme, Slide, ValidationResult } from "../types/presentation";
import type { PptChangeProposal } from "../types/proposal";

export type PptWorkflowEventType =
  | "task.started" | "assistant.text.delta" | "brief.ready"
  | "outline.item.added" | "outline.ready" | "design.ready"
  | "slide.started" | "slide.completed" | "slide.failed"
  | "proposal.created" | "proposal.approved" | "proposal.rejected" | "proposal.applied"
  | "validation.completed" | "export.ready"
  | "task.completed" | "task.failed" | "task.cancelled";

export interface PptWorkflowEvent<T = unknown> {
  eventId: string;
  taskId: string;
  projectId: string;
  chatId: string;
  sequence: number;
  timestamp: string;
  type: PptWorkflowEventType;
  payload: T;
}

export type PptWorkflowPayload =
  | { text: string }
  | { brief: Record<string, unknown> }
  | { item: OutlineItem }
  | { outline: OutlineItem[] }
  | { theme: PresentationTheme }
  | { slideId: string }
  | { slide: Slide }
  | { proposal: PptChangeProposal }
  | { validation: ValidationResult }
  | { downloadUrl: string }
  | { code: string; message: string; retryable: boolean };
