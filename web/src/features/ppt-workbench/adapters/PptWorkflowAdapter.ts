import type { WorkflowCapabilities } from "../protocol/capabilities";
import type { PptWorkflowEvent } from "../protocol/events";
import type { PptExportArtifact, PresentationProject } from "../types/project";
import type { Slide } from "../types/presentation";

export interface StartPptWorkflowInput {
  projectId: string;
  chatId: string;
  prompt: string;
  pageCount?: number;
  attachmentFileIds?: number[];
  knowledgeDocIds?: number[];
  sourcePolicy?: "parsed_only" | "ready_only";
  pptxStructureMode?: 'flat' | 'structured';
  structuredWorkspaceId?: string;
}

export interface DownloadedPptFile {
  filename: string;
  size: number;
  sha256?: string;
}

export interface PptWorkflowAdapter {
  readonly capabilities: WorkflowCapabilities;
  start(input: StartPptWorkflowInput): AsyncIterable<PptWorkflowEvent>;
  cancel?(taskId: string): Promise<void>;
  disconnect?(taskId: string): void;
  dispose?(): void;
  resume?(taskId: string, afterSequence: number): AsyncIterable<PptWorkflowEvent>;
  download?(artifact: PptExportArtifact, fallbackTitle: string): Promise<DownloadedPptFile>;
  loadHistoryProject?(projectId: string): Promise<{ project: PresentationProject } | null>;
  restoreSlideAssets?(slides: Slide[]): Promise<Slide[] | void>;
}
