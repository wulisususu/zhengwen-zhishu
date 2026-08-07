/**
 * P4 Animation API Adapter
 *
 * Communicates with the backend animation endpoints:
 *   GET    /api/v1/ppt-master/projects/{id}/editor/animations
 *   PUT    /api/v1/ppt-master/projects/{id}/editor/animations
 *   POST   /api/v1/ppt-master/projects/{id}/editor/animations/validate
 *   GET    /api/v1/ppt-master/projects/{id}/editor/animations/export-preview
 */

const API_BASE = "/api/v1/ppt-master/projects";

export const P4_ENTRANCE_EFFECTS = ["appear", "fade", "wipe", "fly_in", "zoom"] as const;
export type P4EntranceEffect = typeof P4_ENTRANCE_EFFECTS[number];

export interface AnimationObject {
  animation_id: string;
  element_id: string;
  category: "entrance";
  effect: P4EntranceEffect;
  order: number;
  duration_ms: number;
  delay_ms: number;
  trigger: "on_click" | "with_previous" | "after_previous";
  direction: string | null;
  repeat: number;
  enabled: boolean;
}

export interface SlideAnimations {
  slide_id: string;
  animations: AnimationObject[];
}

export interface AnimationManifest {
  version: number;
  project_id: string;
  animation_revision: number;
  slides: SlideAnimations[];
}

export interface AnimationSaveResponse {
  project_id: string;
  document_revision: number;
  animation_revision: number;
  animation_count: number;
  sha256: string;
}

export interface AnimationGetResponse {
  project_id: string;
  document_revision: number;
  animation_revision: number;
  manifest: AnimationManifest;
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface ExportPreviewTarget {
  slide_id: string;
  element_id: string;
  shape_id: number | null;
  shape_name: string;
  supported: boolean;
  reason: string;
}

export interface ExportPreviewResponse {
  project_id: string;
  document_revision: number;
  animation_revision: number;
  targets: ExportPreviewTarget[];
  errors: string[];
}

function apiHeaders(): Record<string, string> {
  const token = localStorage.getItem("token") || "";
  return {
    "Content-Type": "application/json",
    Authorization: token ? `Bearer ${token}` : "",
  };
}

async function handleResponse<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    const detail = body?.detail || {};
    const code = detail?.code || `HTTP ${resp.status}`;
    throw new Error(code);
  }
  const json = await resp.json();
  return json.data as T;
}

// ── Public API ──────────────────────────────────────────────────

export async function getAnimations(projectId: string): Promise<AnimationGetResponse> {
  const resp = await fetch(`${API_BASE}/${projectId}/editor/animations`, {
    headers: apiHeaders(),
  });
  return handleResponse<AnimationGetResponse>(resp);
}

export async function saveAnimations(
  projectId: string,
  expectedDocumentRevision: number,
  expectedAnimationRevision: number,
  manifest: AnimationManifest,
): Promise<AnimationSaveResponse> {
  const resp = await fetch(`${API_BASE}/${projectId}/editor/animations`, {
    method: "PUT",
    headers: apiHeaders(),
    body: JSON.stringify({
      expected_document_revision: expectedDocumentRevision,
      expected_animation_revision: expectedAnimationRevision,
      manifest,
    }),
  });
  return handleResponse<AnimationSaveResponse>(resp);
}

export async function validateAnimations(
  projectId: string,
  manifest: AnimationManifest,
  document?: Record<string, any>,
): Promise<ValidationResult> {
  const resp = await fetch(`${API_BASE}/${projectId}/editor/animations/validate`, {
    method: "POST",
    headers: apiHeaders(),
    body: JSON.stringify({ manifest, document }),
  });
  return handleResponse<ValidationResult>(resp);
}

export async function exportPreviewAnimations(
  projectId: string,
  documentRevision: number,
  animationRevision: number,
): Promise<ExportPreviewResponse> {
  const params = new URLSearchParams({
    document_revision: String(documentRevision),
    animation_revision: String(animationRevision),
  });
  const resp = await fetch(
    `${API_BASE}/${projectId}/editor/animations/export-preview?${params}`,
    { headers: apiHeaders() },
  );
  return handleResponse<ExportPreviewResponse>(resp);
}
