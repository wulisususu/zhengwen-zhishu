<script setup lang="ts">
// StageStepper.vue — 3-step stepper (Stage1 -> Stage2 -> Stage3).
// Reflects current_stage from API. Cannot skip an unconfirmed stage.
// "Back" returns to a previous stage WITHOUT losing data (revise invalidates
// downstream confirmations server-side). Final generate polls until completed.
import { computed } from 'vue'
import { useGuidedPlanner } from './useGuidedPlanner'
import Stage1Form from './Stage1Form.vue'
import Stage2Directions from './Stage2Directions.vue'
import Stage3Config from './Stage3Config.vue'

const store = useGuidedPlanner()

const steps = [
  { key: 'stage1', label: '目标与信息' },
  { key: 'stage2', label: '方向选择' },
  { key: 'stage3', label: '生成配置' },
] as const

function stepState(key: string): 'done' | 'active' | 'todo' {
  if (key === 'stage1') return store.stage1Confirmed ? 'done' : 'active'
  if (key === 'stage2') return store.stage2Confirmed ? 'done' : store.stage1Confirmed ? 'active' : 'todo'
  return store.fullyConfirmed ? 'done' : store.stage2Confirmed ? 'active' : 'todo'
}

// Which stage body to show.
const showStage = computed<'stage1' | 'stage2' | 'stage3'>(() => {
  if (!store.stage1Confirmed) return 'stage1'
  if (!store.stage2Confirmed) return 'stage2'
  return 'stage3'
})

const canGenerate = computed(() => store.fullyConfirmed && !store.generating)

async function onGenerate() {
  await store.generate()
}
</script>

<template>
  <section class="stepper w-full" aria-label="引导式生成步骤">
    <!-- Stepper header -->
    <ol class="mb-6 flex items-center gap-2 text-sm">
      <li v-for="(s, i) in steps" :key="s.key" class="flex items-center gap-2">
        <span
          class="inline-flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold"
          :class="{
            'border-slate-900 bg-slate-900 text-white': stepState(s.key) === 'active',
            'border-emerald-500 bg-emerald-500 text-white': stepState(s.key) === 'done',
            'border-slate-300 text-slate-400': stepState(s.key) === 'todo',
          }"
          :aria-current="stepState(s.key) === 'active' ? 'step' : undefined"
        >
          <span v-if="stepState(s.key) === 'done'">✓</span>
          <span v-else>{{ i + 1 }}</span>
        </span>
        <span :class="stepState(s.key) === 'todo' ? 'text-slate-400' : 'text-slate-800 font-medium'">{{ s.label }}</span>
        <span v-if="i < steps.length - 1" class="mx-1 h-px w-8 bg-slate-200" aria-hidden="true" />
      </li>
    </ol>

    <!-- Stage bodies -->
    <Stage1Form v-if="showStage === 'stage1'" />
    <Stage2Directions v-else-if="showStage === 'stage2'" />
    <Stage3Config v-else />

    <!-- Completion / failure / generate -->
    <div v-if="store.fullyConfirmed" class="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <p v-if="store.isCompleted" class="text-sm text-emerald-700">生成完成。任务 ID：{{ store.generationTaskId }}</p>
      <p v-else-if="store.isFailed" class="text-sm text-rose-600">生成失败，请重试。</p>
      <p v-else class="text-sm text-slate-600">配置已确认，可发起生成。</p>

      <div class="mt-3 flex flex-wrap gap-3">
        <button
          v-if="store.isFailed"
          type="button"
          class="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 active:scale-[0.98]"
          :disabled="store.generating"
          @click="store.retry()"
        >
          重试生成
        </button>
        <button
          v-else-if="!store.isCompleted"
          type="button"
          class="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 active:scale-[0.98]"
          :disabled="!canGenerate"
          @click="onGenerate"
        >
          {{ store.generating ? '生成中…' : '生成演示文稿' }}
        </button>
      </div>
    </div>
  </section>
</template>
