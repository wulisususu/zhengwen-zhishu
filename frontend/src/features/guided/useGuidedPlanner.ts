// useGuidedPlanner.ts — Pinia store for the P3-B Guided Strategist feature.
//
// Responsibilities:
//  - hold UI mode (quick | guided, default quick)
//  - hold guided project identity + stage data (refetched from API, never trusted from storage)
//  - save / back(revise) / confirm / generate with optimistic revision locking
//  - 409 conflict handling (refetch truth + surface a prompt)
//  - failure retry
//  - refresh / relogin / back-forward restore via a *minimal recovery token*.
//
// IMPORTANT: localStorage is a cache ONLY (a hint of which project id to refetch).
// On every load we call GET /{id} and treat the API response as the source of truth.

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  ApiError,
  confirmStage as apiConfirm,
  createGuidedProject,
  generateProject,
  getGuidedProject,
  getStage,
  isApiError,
  patchStage as apiPatchStage,
  retryProject,
  toApiError,
  type Direction,
  type GuidedProject,
  type Recommendations,
  type Stage1Data,
  type Stage3Data,
} from './guidedApi'

export type PlannerMode = 'quick' | 'guided'
export type StageKey = 'stage1' | 'stage2' | 'stage3'

const RECOVERY_KEY = 'p3b:guided:recovery'

interface RecoveryToken {
  guided_project_id: string
}

// --- localStorage helpers (cache ONLY) -----------------------------------

function readRecoveryToken(): RecoveryToken | null {
  try {
    const raw = localStorage.getItem(RECOVERY_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as unknown
    if (parsed && typeof (parsed as RecoveryToken).guided_project_id === 'string') {
      return parsed as RecoveryToken
    }
    return null
  } catch {
    return null
  }
}

function writeRecoveryToken(id: string): void {
  try {
    localStorage.setItem(RECOVERY_KEY, JSON.stringify({ guided_project_id: id } as RecoveryToken))
  } catch {
    /* cache write failure is non-fatal; API stays source of truth */
  }
}

function clearRecoveryToken(): void {
  try {
    localStorage.removeItem(RECOVERY_KEY)
  } catch {
    /* ignore */
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

// --- store ----------------------------------------------------------------

export const useGuidedPlanner = defineStore('guided-planner', () => {
  // UI mode — defaults to Quick (unchanged existing quick flow).
  const mode = ref<PlannerMode>('quick')

  // project identity
  const guidedProjectId = ref<string | null>(null)
  const revision = ref<number>(1)
  const currentStage = ref<string>('stage1_draft')
  const status = ref<string>('draft')
  const generationTaskId = ref<string | null>(null)

  // stage data (mirrors API json columns)
  const stage1 = ref<Stage1Data | null>(null)
  const recommendations = ref<Recommendations | null>(null)
  const chosenDirectionId = ref<string | null>(null)
  const stage3 = ref<Stage3Data | null>(null)

  // async / error / ui state
  const loading = ref(false)
  const generating = ref(false)
  const error = ref<ApiError | null>(null)
  const conflict = ref<{ serverRevision: number } | null>(null)
  const restoredFromApi = ref(false)

  // derived stage key (stage1 | stage2 | stage3)
  const stageKey = computed<StageKey>(() => {
    if (currentStage.value.startsWith('stage3')) return 'stage3'
    if (currentStage.value.startsWith('stage2')) return 'stage2'
    return 'stage1'
  })

  // confirmation booleans derived from currentStage/status (server truth)
  const stage1Confirmed = computed(() =>
    ['stage2_draft', 'stage2_confirmed', 'stage3_draft', 'confirmed', 'generating', 'completed'].includes(currentStage.value),
  )
  const stage2Confirmed = computed(() =>
    ['stage2_confirmed', 'stage3_draft', 'confirmed', 'generating', 'completed'].includes(currentStage.value),
  )
  const fullyConfirmed = computed(
    () => status.value === 'confirmed' || status.value === 'generating' || status.value === 'completed' || currentStage.value === 'confirmed',
  )
  const isCompleted = computed(() => status.value === 'completed')
  const isFailed = computed(() => status.value === 'failed')

  // reachability: you may always revisit a confirmed/earlier stage, but you may
  // NOT skip forward past an unconfirmed stage.
  function canEnterStage(target: StageKey): boolean {
    if (target === 'stage1') return true
    if (target === 'stage2') return stage1Confirmed.value
    return stage1Confirmed.value && stage2Confirmed.value
  }

  // ---- internal apply helpers (write API truth into state) --------------

  function applyProject(p: GuidedProject): void {
    guidedProjectId.value = p.guided_project_id
    revision.value = p.revision
    currentStage.value = p.current_stage
    status.value = p.status
    stage1.value = p.stage1_json
    recommendations.value = p.recommendations_json
    stage3.value = p.stage3_json
    generationTaskId.value = p.generation_task_id
    if (p.result_json && p.confirmed_values_json) {
      // a chosen direction may live in confirmed_values_json
      const cv = (p.confirmed_values_json as { chosen_direction_id?: string }) ?? {}
      if (cv.chosen_direction_id) chosenDirectionId.value = cv.chosen_direction_id
    }
  }

  function applyStage(s: {
    stage1?: Stage1Data | null
    recommendations?: Recommendations | null
    stage3?: Stage3Data | null
    chosen_direction?: Direction | null
  }): void {
    if (s.stage1) stage1.value = s.stage1
    if (s.recommendations) recommendations.value = s.recommendations
    if (s.stage3) stage3.value = s.stage3
    if (s.chosen_direction) chosenDirectionId.value = s.chosen_direction.direction_id
  }

  // ---- public actions ----------------------------------------------------

  function setMode(m: PlannerMode): void {
    mode.value = m
  }

  async function createProject(title?: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const res = await createGuidedProject({ title: title ?? '未命名引导项目' })
      guidedProjectId.value = res.guided_project_id
      revision.value = res.revision
      currentStage.value = res.current_stage
      status.value = res.status
      writeRecoveryToken(res.guided_project_id)
      await loadStage()
    } catch (e) {
      error.value = toApiError(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  // Refetch the full restorable state (truth) from API.
  async function loadProject(id: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const p = await getGuidedProject(id)
      applyProject(p)
      writeRecoveryToken(id)
      restoredFromApi.value = true
      await loadStage()
    } catch (e) {
      const ae = toApiError(e)
      // 404/403 => project gone or not ours => drop the cache hint
      if (ae.status === 404 || ae.status === 403) clearRecoveryToken()
      error.value = ae
      throw ae
    } finally {
      loading.value = false
    }
  }

  async function loadStage(): Promise<void> {
    if (!guidedProjectId.value) return
    const s = await getStage(guidedProjectId.value)
    applyStage(s)
  }

  // Refresh current truth from API (used after 409 and on restore).
  async function refreshFromApi(): Promise<void> {
    if (!guidedProjectId.value) return
    const p = await getGuidedProject(guidedProjectId.value)
    applyProject(p)
    await loadStage()
  }

  // Restore on app load / refresh / relogin / back-forward.
  // localStorage only provides the *id* to refetch; data always comes from API.
  async function restore(): Promise<boolean> {
    const token = readRecoveryToken()
    if (!token) return false
    try {
      await loadProject(token.guided_project_id)
      return true
    } catch {
      return false
    }
  }

  // PATCH stage1 draft.
  async function saveStage1(data: Stage1Data): Promise<void> {
    if (!guidedProjectId.value) throw new ApiError(400, 'no active guided project')
    loading.value = true
    error.value = null
    try {
      const res = await apiPatchStage(guidedProjectId.value, revision.value, data)
      revision.value = res.revision
      stage1.value = data
      conflict.value = null
    } catch (e) {
      await handleMutationError(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  // Confirm a stage (stage1 | stage2 | stage3).
  //  - stage1: data is PATCHed separately; we also forward it here so the server
  //    never has to fall back to stale data.
  //  - stage2: pass direction_id (sent top-level per the tolerant server contract).
  //  - stage3: the edited config lives in the component's local model and is NOT
  //    PATCHed, so we MUST forward it as the stage data dict.
  async function confirm(
    key: StageKey,
    extra?: { direction_id?: string; stage1_data?: Stage1Data; stage3_data?: Stage3Data },
  ): Promise<void> {
    if (!guidedProjectId.value) throw new ApiError(400, 'no active guided project')
    loading.value = true
    error.value = null
    try {
      // When the real stage data dict is available, send it; otherwise send the
      // stage-name marker and let the server keep the already-stored data.
      let stagePayload: StageKey | Stage1Data | Stage3Data = key
      if (key === 'stage3' && extra?.stage3_data) stagePayload = extra.stage3_data
      else if (key === 'stage1' && extra?.stage1_data) stagePayload = extra.stage1_data
      const res = await apiConfirm(guidedProjectId.value, revision.value, {
        stage: stagePayload,
        ...(extra?.direction_id ? { direction_id: extra.direction_id } : {}),
      })
      revision.value = res.revision
      currentStage.value = res.current_stage
      status.value = res.status
      conflict.value = null
      await loadStage()
    } catch (e) {
      await handleMutationError(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  // Back / revise: invalidate downstream confirmations.
  async function reviseTo(target: StageKey): Promise<void> {
    if (!guidedProjectId.value) throw new ApiError(400, 'no active guided project')
    const action = target === 'stage1' ? 'revise_stage1' : 'revise_stage2'
    loading.value = true
    error.value = null
    try {
      const res = await apiConfirm(guidedProjectId.value, revision.value, { action })
      revision.value = res.revision
      currentStage.value = res.current_stage
      status.value = res.status
      conflict.value = null
      // downstream data is reset server-side; refetch everything
      await refreshFromApi()
    } catch (e) {
      await handleMutationError(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  // Shared 409 / error handling for mutating calls.
  async function handleMutationError(e: unknown): Promise<void> {
    const ae = toApiError(e)
    error.value = ae
    if (ae.status === 409 && ae.error_code === 'revision_conflict') {
      // Recover truth from server, then surface a conflict prompt.
      try {
        await refreshFromApi()
      } catch {
        /* keep original error if refetch fails */
      }
      conflict.value = { serverRevision: revision.value }
    }
  }

  function dismissConflict(): void {
    conflict.value = null
  }

  function resolveConflict(): void {
    // User accepted server truth -> just close the prompt.
    conflict.value = null
  }

  // Generate: only valid when fullyConfirmed. Polls task until completed/failed.
  async function generate(): Promise<void> {
    if (!guidedProjectId.value) throw new ApiError(400, 'no active guided project')
    if (!fullyConfirmed.value) throw new ApiError(400, 'project not confirmed')
    generating.value = true
    error.value = null
    try {
      const res = await generateProject(guidedProjectId.value, { expected_revision: revision.value })
      generationTaskId.value = res.generation_task_id
      status.value = 'generating'
      await pollUntilDone()
    } catch (e) {
      error.value = toApiError(e)
      throw e
    } finally {
      generating.value = false
    }
  }

  async function retry(): Promise<void> {
    if (!guidedProjectId.value) throw new ApiError(400, 'no active guided project')
    if (!isFailed.value) throw new ApiError(400, 'project not in failed state')
    generating.value = true
    error.value = null
    try {
      await retryProject(guidedProjectId.value)
      status.value = 'generating'
      await pollUntilDone()
    } catch (e) {
      error.value = toApiError(e)
      throw e
    } finally {
      generating.value = false
    }
  }

  async function pollUntilDone(): Promise<void> {
    if (!guidedProjectId.value) return
    const MAX = 120 // 120 * 1.5s = 3min safety bound
    for (let i = 0; i < MAX; i++) {
      await delay(1500)
      const p = await getGuidedProject(guidedProjectId.value)
      applyProject(p)
      if (p.status === 'completed' || p.status === 'failed') break
    }
  }

  function reset(): void {
    guidedProjectId.value = null
    revision.value = 1
    currentStage.value = 'stage1_draft'
    status.value = 'draft'
    generationTaskId.value = null
    stage1.value = null
    recommendations.value = null
    chosenDirectionId.value = null
    stage3.value = null
    error.value = null
    conflict.value = null
    restoredFromApi.value = false
  }

  return {
    // state
    mode,
    guidedProjectId,
    revision,
    currentStage,
    status,
    generationTaskId,
    stage1,
    recommendations,
    chosenDirectionId,
    stage3,
    loading,
    generating,
    error,
    conflict,
    restoredFromApi,
    // derived
    stageKey,
    stage1Confirmed,
    stage2Confirmed,
    fullyConfirmed,
    isCompleted,
    isFailed,
    // helpers
    canEnterStage,
    // actions
    setMode,
    createProject,
    loadProject,
    loadStage,
    refreshFromApi,
    restore,
    saveStage1,
    confirm,
    reviseTo,
    dismissConflict,
    resolveConflict,
    generate,
    retry,
    reset,
  }
})

export { isApiError }
