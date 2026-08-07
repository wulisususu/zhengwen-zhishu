export type WorkflowStage = "idle" | "understanding" | "outline" | "design" | "slides" | "validation" | "export" | "completed" | "failed" | "cancelled";
export type GenerationStatus = "idle" | "queued" | "running" | "completed" | "failed" | "interrupted" | "cancelled";

export interface PptGenerationTask {
  id: string;
  projectId: string;
  chatId: string;
  stage: WorkflowStage;
  status: GenerationStatus;
  progress: number;
  lastAppliedSequence: number;
  requestedPageCount?: number;
  startedAt?: string;
  completedAt?: string;
}

export interface WorkflowError {
  code: string;
  message: string;
  retryable: boolean;
  details?: unknown;
  httpStatus?: number;
  retryAfterSeconds?: number;
}
