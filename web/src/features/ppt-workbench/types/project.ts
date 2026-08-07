import type { OutlineItem, Presentation, PresentationTheme, ValidationResult } from "./presentation";

export interface PptExportArtifact {
  fileId: number;
  downloadUrl: string;
  size: number;
  sha256: string;
  valid: true;
  warnings: string[];
  slideCount?: number;
}

export interface PresentationProject {
  id: string;
  title: string;
  titleSource?: "frontend-prompt" | "backend";
  isHistorical?: boolean;
  brief: PptBrief;
  outline: OutlineItem[];
  presentation: Presentation;
  theme: PresentationTheme | null;
  validation: ValidationResult | null;
  exportArtifact?: PptExportArtifact | null;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface PptBrief {
  goal: string;
  audience: string;
  slideCount: number;
  constraints: string[];
}
