// guidedApi.ts — typed HTTP client for the P3-B Guided Strategist API.
//
// All endpoints are mounted under /api/v1/ppt-master (see P3B_SPEC.md §6).
// The frontend treats the API as the single source of truth. localStorage is
// NEVER used to restore stage data — it only caches a recovery *hint* (the
// project id) so we know what to REFETCH on reload.

export const GUIDED_API_BASE = '/api/v1/ppt-master'

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

export interface ApiErrorDetail {
  error_code?: string
  message?: string
  detail?: unknown
}

export class ApiError extends Error {
  status: number
  error_code?: string
  detail?: unknown
  constructor(status: number, message: string, error_code?: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.error_code = error_code
    this.detail = detail
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError
}

function toApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e
  return new ApiError(0, e instanceof Error ? e.message : String(e))
}

// ---------------------------------------------------------------------------
// Domain types (mirrors P3B_SPEC.md §4/§5)
// ---------------------------------------------------------------------------

export interface StageField {
  value: unknown
  suggested_value: unknown
  source: string
  confidence: number
  user_modified: boolean
}

export type Stage1Data = Record<string, StageField>

export interface Direction {
  direction_id: string
  name: string
  summary: string
  rationale: string
  visual_style: string
  presentation_mode: string
  reading_mode: string
  palette: Record<string, string>
  title_family: string
  body_family: string
  typography_sizes: Record<string, string>
  icon_strategy: string
  image_strategy: string
  chart_strategy: string
  table_strategy: string
  page_rhythm: string
  pptx_structure_mode: 'flat' | 'structured'
  structured_workspace_id: string
  structured_workspace_revision: number
  sample_page_roles: string[]
}

export interface Recommendations {
  directions: Direction[]
}

export type AnimationPolicy = 'none' | 'basic_allowed'

export interface Stage3Data {
  generation_mode: 'structured' | 'flat'
  page_count: number
  image_sources: string[]
  native_chart_policy: 'none' | 'native'
  native_table_policy: 'none' | 'native'
  formula_policy: 'none' | 'native'
  pptx_structure_mode: 'flat' | 'structured'
  structured_workspace_id: string | null
  structured_workspace_revision: number | null
  animation_policy: AnimationPolicy
  refinement_policy: string
  source_handling_summary: string
}

export interface GuidedProject {
  guided_project_id: string
  owner_user_id: number
  project_id: string | null
  title: string
  mode: 'guided'
  current_stage: string
  status: string
  revision: number
  stage1_json: Stage1Data | null
  stage2_json: unknown
  stage3_json: Stage3Data | null
  recommendations_json: Recommendations | null
  result_json: unknown
  confirmed_values_json: unknown
  source_refs_json: unknown
  generation_task_id: string | null
  error_json: unknown | null
  created_at: string
  updated_at: string
  confirmed_at: string | null
  completed_at: string | null
}

export interface CreateResponse {
  guided_project_id: string
  current_stage: string
  revision: number
  status: string
}

export interface ListResponse {
  items: Array<Pick<GuidedProject, 'guided_project_id' | 'title' | 'current_stage' | 'status' | 'revision' | 'updated_at'>>
  total: number
  page: number
  page_size: number
}

export interface StageResponse {
  guided_project_id: string
  current_stage: string
  status: string
  revision: number
  allowed_next_actions: string[]
  stage1: Stage1Data | null
  recommendations: Recommendations | null
  stage3: Stage3Data | null
  chosen_direction: Direction | null
}

export interface ConfirmResponse {
  revision: number
  current_stage: string
  status: string
}

export interface GenerateResponse {
  generation_task_id: string
}

// ---------------------------------------------------------------------------
// Low level transport
// ---------------------------------------------------------------------------

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${GUIDED_API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
      ...init,
    })
  } catch (networkErr) {
    throw new ApiError(0, networkErr instanceof Error ? networkErr.message : 'network error')
  }

  const text = await res.text()
  let data: any = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }

  if (!res.ok) {
    const code = data?.error_code as string | undefined
    const msg = (data?.message as string) || res.statusText || `HTTP ${res.status}`
    throw new ApiError(res.status, msg, code, data?.detail)
  }
  return data as T
}

function jsonBody(body: unknown): RequestInit {
  return { method: 'POST', body: JSON.stringify(body) }
}

// ---------------------------------------------------------------------------
// Endpoint calls (§6)
// ---------------------------------------------------------------------------

export function createGuidedProject(body: { title?: string; prompt?: string; source_refs?: unknown }): Promise<CreateResponse> {
  return request<CreateResponse>('/guided-projects', jsonBody(body))
}

export function listGuidedProjects(page = 1, page_size = 20): Promise<ListResponse> {
  return request<ListResponse>(`/guided-projects?page=${page}&page_size=${page_size}`)
}

export function getGuidedProject(id: string): Promise<GuidedProject> {
  return request<GuidedProject>(`/guided-projects/${encodeURIComponent(id)}`)
}

export function getStage(id: string): Promise<StageResponse> {
  return request<StageResponse>(`/guided-projects/${encodeURIComponent(id)}/stage`)
}

export function patchStage(id: string, expected_revision: number, stage_data: Stage1Data): Promise<ConfirmResponse> {
  return request<ConfirmResponse>(`/guided-projects/${encodeURIComponent(id)}/stage`, {
    method: 'PATCH',
    body: JSON.stringify({ expected_revision, stage_data }),
  })
}

export function confirmStage(
  id: string,
  expected_revision: number,
  body: { stage?: 'stage1' | 'stage2' | 'stage3' | Stage1Data | Stage3Data; action?: 'revise_stage1' | 'revise_stage2'; direction_id?: string },
): Promise<ConfirmResponse> {
  return request<ConfirmResponse>(`/guided-projects/${encodeURIComponent(id)}/confirm`, jsonBody({ expected_revision, ...body }))
}

export function generateProject(id: string, body?: { expected_revision?: number }): Promise<GenerateResponse> {
  return request<GenerateResponse>(`/guided-projects/${encodeURIComponent(id)}/generate`, jsonBody(body ?? {}))
}

export function retryProject(id: string): Promise<GenerateResponse> {
  return request<GenerateResponse>(`/guided-projects/${encodeURIComponent(id)}/retry`, jsonBody({}))
}

export { toApiError }
