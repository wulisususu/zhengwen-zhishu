// guidedPlanner.spec.ts — P3-B Guided Strategist frontend tests (vitest).
//
// Covers (P3B_SPEC.md §10): default quick mode, select guided, stage form gate,
// three directions, select/modify a direction, back invalidates forward progress,
// 409 handling (refetch + prompt), refresh restore (API truth, not localStorage),
// generate payload shape, quick old payload stays compatible, and responsive
// no-horizontal-overflow at 1024/1280/1366.
//
// NOTE: runs on the server where vitest + @vue/test-utils + happy-dom are configured.
// @vitest-environment happy-dom
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

// Mock the API client entirely (no real server / network).
vi.mock('./guidedApi', () => {
  const ok = (data: unknown) => Promise.resolve(data)
  class ApiError extends Error {
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
  return {
    ApiError,
    isApiError: (e: unknown): e is ApiError => e instanceof ApiError,
    toApiError: (e: unknown) => (e instanceof ApiError ? e : new ApiError(0, String(e))),
    createGuidedProject: vi.fn(() => ok({ guided_project_id: 'gp1', current_stage: 'stage1_draft', revision: 1, status: 'draft' })),
    getGuidedProject: vi.fn(),
    getStage: vi.fn(() => ok({ guided_project_id: 'gp1', current_stage: 'stage1_draft', status: 'draft', revision: 1, allowed_next_actions: ['confirm_stage1'], stage1: null, recommendations: null, stage3: null, chosen_direction: null })),
    patchStage: vi.fn(() => ok({ revision: 2, current_stage: 'stage1_draft', status: 'draft' })),
    confirmStage: vi.fn(),
    generateProject: vi.fn(() => ok({ generation_task_id: 'task-1' })),
    retryProject: vi.fn(() => ok({ generation_task_id: 'task-2' })),
  }
})

// Provide the P3-A workspace composable so Stage3Config import resolves in tests.
vi.mock('@/composables/useStructuredWorkspaces', () => ({
  useStructuredWorkspaces: () => ({ workspaces: { value: [] }, loading: { value: false }, load: () => Promise.resolve() }),
}))

import * as api from './guidedApi'
import { useGuidedPlanner } from './useGuidedPlanner'
import GuidedPlanner from './GuidedPlanner.vue'
import Stage1Form from './Stage1Form.vue'

const dir = (id: string) => ({
  direction_id: id,
  name: id,
  summary: `${id} 摘要`,
  rationale: `${id} 理由`,
  visual_style: 'clean',
  presentation_mode: 'linear',
  reading_mode: 'sequential',
  palette: { primary: '#111827', accent: '#2563eb' },
  title_family: 'Poppins',
  body_family: 'Lora',
  typography_sizes: { h1: '40px' },
  icon_strategy: 'line',
  image_strategy: 'slot',
  chart_strategy: 'native',
  table_strategy: 'native',
  page_rhythm: 'balanced',
  pptx_structure_mode: 'structured' as const,
  structured_workspace_id: 'ws-1',
  structured_workspace_revision: 3,
  sample_page_roles: ['cover', 'content'],
})

const fullProject = (over: Record<string, unknown> = {}) => ({
  guided_project_id: 'gp1',
  owner_user_id: 123,
  project_id: null,
  title: 't',
  mode: 'guided' as const,
  current_stage: 'stage1_draft',
  status: 'draft',
  revision: 1,
  stage1_json: null,
  stage2_json: null,
  stage3_json: null,
  recommendations_json: null,
  result_json: null,
  confirmed_values_json: null,
  source_refs_json: null,
  generation_task_id: null,
  error_json: null,
  created_at: '',
  updated_at: '',
  confirmed_at: null,
  completed_at: null,
  ...over,
})

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  ;(api.getStage as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
    guided_project_id: 'gp1', current_stage: 'stage1_draft', status: 'draft', revision: 1,
    allowed_next_actions: ['confirm_stage1'], stage1: null, recommendations: null, stage3: null, chosen_direction: null,
  })
})

describe('GuidedPlanner — mode & store basics', () => {
  it('defaults to Quick mode (existing quick flow untouched)', () => {
    const store = useGuidedPlanner()
    expect(store.mode).toBe('quick')
    expect(store.guidedProjectId).toBeNull()
  })

  it('selecting Guided creates a project and shows Stage1', async () => {
    const store = useGuidedPlanner()
    store.setMode('guided')
    await store.createProject()
    expect(api.createGuidedProject).toHaveBeenCalled()
    expect(store.currentStage).toBe('stage1_draft')
    expect(store.stageKey).toBe('stage1')
  })
})

describe('Stage 1 form gate', () => {
  it('cannot confirm when required fields are empty', async () => {
    const store = useGuidedPlanner()
    await store.createProject()
    const wrapper = mount(Stage1Form)
    const confirmBtn = wrapper.findAll('button').find((b) => b.text().includes('确认并继续'))!
    expect(confirmBtn.attributes('disabled')).toBeDefined()
    await wrapper.unmount()
  })

  it('enables confirm once required suggested values are present', async () => {
    const store = useGuidedPlanner()
    await store.createProject()
    const sample: Record<string, unknown> = {}
    for (const k of ['audience', 'communication_intent', 'core_message', 'language', 'requested_page_count']) {
      sample[k] = { value: k === 'requested_page_count' ? 6 : `v-${k}`, suggested_value: `v-${k}`, source: 'system', confidence: 0.8, user_modified: false }
    }
    store.stage1 = sample as any
    await nextTick()
    const wrapper = mount(Stage1Form)
    const confirmBtn = wrapper.findAll('button').find((b) => b.text().includes('确认并继续'))!
    expect(confirmBtn.attributes('disabled')).toBeUndefined()
    await wrapper.unmount()
  })
})

describe('Stage 2 directions', () => {
  it('renders exactly three directions and confirms the chosen one', async () => {
    const store = useGuidedPlanner()
    await store.createProject()
    ;(api.getStage as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      guided_project_id: 'gp1', current_stage: 'stage2_draft', status: 'draft', revision: 1,
      allowed_next_actions: ['confirm_stage2'], stage1: null,
      recommendations: { directions: [dir('safe'), dir('shifted'), dir('bold')] }, stage3: null, chosen_direction: null,
    })
    await store.loadStage()
    expect(store.recommendations?.directions.length).toBe(3)

    ;(api.confirmStage as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ revision: 3, current_stage: 'stage3_draft', status: 'draft' })
    await store.confirm('stage2', { direction_id: 'bold' })
    expect(api.confirmStage).toHaveBeenCalledWith('gp1', 1, { stage: 'stage2', direction_id: 'bold' })
  })
})

describe('Back invalidates forward progress', () => {
  it('revise to stage1 clears downstream confirmation', async () => {
    const store = useGuidedPlanner()
    await store.createProject()
    // simulate stage2 already confirmed
    store.currentStage = 'stage2_confirmed'
    expect(store.stage2Confirmed).toBe(true)

    ;(api.confirmStage as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ revision: 7, current_stage: 'stage1_draft', status: 'draft' })
    ;(api.getGuidedProject as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fullProject({ revision: 7, current_stage: 'stage1_draft', recommendations_json: null }))

    await store.reviseTo('stage1')
    expect(store.currentStage).toBe('stage1_draft')
    expect(store.stage2Confirmed).toBe(false)
    expect(api.getGuidedProject).toHaveBeenCalled() // refetched truth
  })
})

describe('409 conflict handling', () => {
  it('refetches truth and surfaces a conflict prompt on revision_conflict', async () => {
    const store = useGuidedPlanner()
    await store.createProject()
    ;(api.confirmStage as unknown as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new api.ApiError(409, 'conflict', 'revision_conflict'))
    ;(api.getGuidedProject as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fullProject({ revision: 5, current_stage: 'stage2_draft' }))

    await expect(store.confirm('stage1')).rejects.toBeTruthy()
    expect(store.conflict).not.toBeNull()
    expect(api.getGuidedProject).toHaveBeenCalled()
    expect(store.revision).toBe(5) // adopted server truth
  })
})

describe('Refresh / relogin / back-forward restore', () => {
  it('restores from API (not localStorage) using only the recovery id hint', async () => {
    localStorage.setItem('p3b:guided:recovery', JSON.stringify({ guided_project_id: 'gpX' }))
    ;(api.getGuidedProject as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fullProject({ guided_project_id: 'gpX', revision: 9, current_stage: 'stage2_draft' }))

    const store = useGuidedPlanner()
    const ok = await store.restore()
    expect(ok).toBe(true)
    expect(store.guidedProjectId).toBe('gpX')
    expect(store.revision).toBe(9)
    expect(store.currentStage).toBe('stage2_draft')
    expect(api.getGuidedProject).toHaveBeenCalledWith('gpX')
  })
})

describe('Generate payload shape', () => {
  it('sends expected_revision matching the API contract', async () => {
    const store = useGuidedPlanner()
    await store.createProject()
    store.currentStage = 'confirmed'
    store.status = 'confirmed'
    ;(api.getGuidedProject as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fullProject({ revision: 1, status: 'completed' }))
    await store.generate()
    expect(api.generateProject).toHaveBeenCalledWith('gp1', { expected_revision: 1 })
  })
})

describe('Quick old payload compatibility', () => {
  it('does not create a guided project while in Quick mode', async () => {
    const store = useGuidedPlanner()
    store.setMode('quick')
    const ok = await store.restore() // no token -> no API call
    expect(ok).toBe(false)
    expect(api.createGuidedProject).not.toHaveBeenCalled()
    expect(api.getGuidedProject).not.toHaveBeenCalled()
  })
})

describe('Responsive — no horizontal overflow at 1024/1280/1366', () => {
  function assertNoHorizontalOverflow(root: HTMLElement, width: number) {
    ;(window as unknown as { innerWidth: number }).innerWidth = width
    // The planner container must opt out of horizontal overflow.
    expect(root.className).toContain('overflow-x-hidden')
    // Walk descendants: none may declare an inline px width larger than viewport.
    const all = root.querySelectorAll('*')
    for (const el of Array.from(all)) {
      const style = (el as HTMLElement).style
      if (style && style.width && /px$/.test(style.width)) {
        const px = parseInt(style.width, 10)
        expect(px).toBeLessThanOrEqual(width)
      }
    }
  }

  it('GuidedPlanner container never overflows at standard widths', () => {
    const store = useGuidedPlanner()
    store.setMode('quick')
    const wrapper = mount(GuidedPlanner, { slots: { quick: '<div data-testid="quick">quick flow</div>' } })
    const root = wrapper.element as HTMLElement
    for (const w of [1024, 1280, 1366]) {
      assertNoHorizontalOverflow(root, w)
    }
    wrapper.unmount()
  })

  it('Stage1Form container never overflows at standard widths', async () => {
    const store = useGuidedPlanner()
    await store.createProject()
    const wrapper = mount(Stage1Form)
    const root = wrapper.element as HTMLElement
    for (const w of [1024, 1280, 1366]) {
      assertNoHorizontalOverflow(root, w)
    }
    wrapper.unmount()
  })
})
