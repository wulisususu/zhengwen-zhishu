<script setup lang="ts">
// Stage2Directions.vue — Stage 2 "方向选择" (P3B_SPEC.md §5 Stage2).
// Renders the 3 coordinated direction cards (safe / shifted / bold) from
// GET /stage recommendations; the user selects one and confirms.
import { computed, ref, watch } from 'vue'
import { useGuidedPlanner } from './useGuidedPlanner'
import type { Direction } from './guidedApi'

const store = useGuidedPlanner()

const directions = computed<Direction[]>(() => store.recommendations?.directions ?? [])

// Pre-select the previously chosen direction (restored from API truth).
const selected = ref<string | null>(store.chosenDirectionId)
watch(
  () => store.chosenDirectionId,
  (id) => {
    if (id) selected.value = id
  },
  { immediate: true },
)

const canConfirm = computed(() => !!selected.value && !store.loading)

async function onConfirm() {
  if (!selected.value) return
  await store.confirm('stage2', { direction_id: selected.value })
}
</script>

<template>
  <section class="stage2 w-full" aria-label="Stage 2 方向选择">
    <header class="mb-4">
      <h2 class="text-lg font-semibold tracking-tight text-slate-900">第 2 步 · 方向选择</h2>
      <p class="text-sm text-slate-500">选择一种演示方向，三张卡片在视觉与结构上彼此协调且互不相同。</p>
    </header>

    <p v-if="!directions.length" class="text-sm text-slate-400">暂无方向建议，请先在第一步确认。</p>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <button
        v-for="d in directions"
        :key="d.direction_id"
        type="button"
        :aria-pressed="selected === d.direction_id"
        class="text-left rounded-2xl border p-4 transition active:scale-[0.99] focus:outline-none focus:ring-2 focus:ring-slate-400"
        :class="selected === d.direction_id ? 'border-slate-900 bg-slate-50 shadow-sm' : 'border-slate-200 hover:border-slate-300'"
        @click="selected = d.direction_id"
      >
        <div class="flex items-center justify-between">
          <h3 class="font-semibold text-slate-900">{{ d.name }}</h3>
          <span
            class="inline-block h-4 w-4 rounded-full border"
            :class="selected === d.direction_id ? 'border-slate-900 bg-slate-900' : 'border-slate-300'"
            aria-hidden="true"
          />
        </div>
        <p class="mt-1 text-sm text-slate-600">{{ d.summary }}</p>
        <p class="mt-2 text-xs text-slate-400">{{ d.rationale }}</p>

        <dl class="mt-3 space-y-1 text-xs text-slate-500">
          <div class="flex gap-2"><dt class="font-medium">结构</dt><dd>{{ d.pptx_structure_mode }}</dd></div>
          <div class="flex gap-2"><dt class="font-medium">演示</dt><dd>{{ d.presentation_mode }}</dd></div>
          <div class="flex gap-2"><dt class="font-medium">阅读</dt><dd>{{ d.reading_mode }}</dd></div>
          <div class="flex gap-2"><dt class="font-medium">标题字体</dt><dd>{{ d.title_family }}</dd></div>
        </dl>

        <div v-if="d.palette && Object.keys(d.palette).length" class="mt-3 flex gap-1">
          <span
            v-for="(hex, role) in d.palette"
            :key="role"
            class="h-5 w-5 rounded"
            :style="{ backgroundColor: String(hex) }"
            :title="`${String(role)}: ${String(hex)}`"
          />
        </div>
      </button>
    </div>

    <div class="mt-5 flex flex-wrap gap-3">
      <button
        type="button"
        class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50"
        :disabled="store.loading || !store.stage1Confirmed"
        @click="store.reviseTo('stage1')"
      >
        返回修改第 1 步
      </button>
      <button
        type="button"
        class="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 active:scale-[0.98]"
        :disabled="!canConfirm"
        @click="onConfirm"
      >
        确认方向并继续
      </button>
    </div>
  </section>
</template>
