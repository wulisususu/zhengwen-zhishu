<script setup lang="ts">
// GuidedPlanner.vue — top container for the P3-B Guided Strategist feature.
//
// - Mode toggle (Quick / Guided), DEFAULT = Quick. In Quick mode the EXISTING
//   quick flow is rendered unchanged via the #quick slot (do NOT alter it).
// - In Guided mode, render the 3-stage stepper.
// - On mount, restore() refetches truth from API if a recovery token exists
//   (localStorage is only a cache hint, never the source of truth).
//
// Integration (see shared_patches/sub4_workbench.patch.txt):
//   <GuidedPlanner>
//     <template #quick><ExistingQuickFlowComponent /></template>
//   </GuidedPlanner>
import { onMounted, ref, watch } from 'vue'
import { useGuidedPlanner } from './useGuidedPlanner'
import StageStepper from './StageStepper.vue'
import ConflictPrompt from './ConflictPrompt.vue'
import ErrorRetry from './ErrorRetry.vue'

const store = useGuidedPlanner()
const initializing = ref(false)

onMounted(async () => {
  initializing.value = true
  try {
    await store.restore()
  } catch {
    /* restore is best-effort; failure just means no prior project */
  } finally {
    initializing.value = false
  }
})

// Switching to Guided with no project -> create one (shows Stage1).
watch(
  () => store.mode,
  async (m) => {
    if (m === 'guided' && !store.guidedProjectId && !store.loading) {
      try {
        await store.createProject()
      } catch {
        /* surfaced via store.error / ErrorRetry */
      }
    }
  },
)
</script>

<template>
  <div class="guided-planner w-full max-w-[1400px] mx-auto px-4 overflow-x-hidden">
    <!-- Mode toggle -->
    <div class="mb-4 inline-flex rounded-xl bg-slate-100 p-1" role="tablist" aria-label="生成模式">
      <button
        type="button"
        role="tab"
        :aria-selected="store.mode === 'quick'"
        :class="[
          'rounded-lg px-4 py-2 text-sm font-medium transition',
          store.mode === 'quick' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700',
        ]"
        @click="store.setMode('quick')"
      >
        快速模式
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="store.mode === 'guided'"
        :class="[
          'rounded-lg px-4 py-2 text-sm font-medium transition',
          store.mode === 'guided' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700',
        ]"
        @click="store.setMode('guided')"
      >
        引导策略
      </button>
    </div>

    <!-- Quick mode: existing flow, untouched -->
    <div v-if="store.mode === 'quick'" class="quick-flow">
      <slot name="quick" />
    </div>

    <!-- Guided mode -->
    <div v-else class="guided-flow">
      <p v-if="initializing" class="text-sm text-slate-500">正在从服务端恢复引导项目…</p>
      <ErrorRetry
        v-else-if="store.error && !store.guidedProjectId"
        :error="store.error"
        @retry="store.restore"
      />
      <StageStepper v-else />
    </div>

    <ConflictPrompt />
  </div>
</template>
