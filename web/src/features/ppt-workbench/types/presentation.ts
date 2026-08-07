export interface OutlineItem {
  id: string;
  title: string;
  description: string;
  status: "pending" | "ready";
  children: OutlineItem[];
}

export interface Presentation {
  aspectRatio: "16:9" | "4:3";
  slides: Slide[];
}

export interface PresentationTheme {
  id: string;
  name: string;
  primaryColor: string;
  backgroundColor: string;
  fontFamily: string;
}

export interface Slide {
  id: string;
  index: number;
  title: string;
  status: "pending" | "generating" | "ready" | "error";
  elements: SlideElement[];
  previewArtifactId?: number;
  thumbnailArtifactId?: number;
  thumbnailUrl?: string;
  previewUrl?: string;
  speakerNotes?: string;
  userModifiedFields: string[];
  revision: number;
}

export type SlideElement = TextElement | ImageElement | ShapeElement;

export interface ElementBase { id: string; x: number; y: number; width: number; height: number; rotation?: number; }
export interface TextElement extends ElementBase { type: "text"; text: string; fontSize: number; color: string; }
export interface ImageElement extends ElementBase { type: "image"; src: string; alt: string; }
export interface ShapeElement extends ElementBase { type: "shape"; shape: "rect" | "circle" | "line"; fill: string; stroke?: string; }

export interface ValidationResult { score: number; issues: ValidationIssue[]; checkedAt: string; }
export interface ValidationIssue { id: string; severity: "info" | "warning" | "error"; slideId?: string; message: string; blocking?: boolean; }


