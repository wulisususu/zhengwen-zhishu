<script setup lang="ts">
// Stage3Config.vue — Stage 3 "生成配置" (P3B_SPEC.md §5 Stage3).
// Production config form. structured_workspace_id reuses the P3-A structured
// workspace LIST (useStructuredWorkspaces). On confirm -> status='confirmed'.
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useGuidedPlanner } from './useGuidedPlanner'
// P3-A structured workspace list (relative path within the ppt-workbench feature).
import { useStructuredWorkspaces } from '../ppt-workbench/composables/useStructuredWorkspaces'
import type { Stage3Data } from './guidedApi'

const store = useGuidedPlanner()
const wsComposable = useStructuredWorkspaces() as any
const workspaces = ref<any[]>(wsComposable?.workspaces?.value ?? wsComposable?.data?.value ?? [])
const wsLoading = ref<boolean>(!!wsComposable?.loading?.value)

onMounted(async () => {
  try {
    if (typeof wsComposable?.load === 'function') await wsComposable.load()
    if (typeof wsComposable?.refresh === 'function') await wsComposable.refresh()
  } catch {
    /* non-fatal: user can still pick flat mode */
  }
  workspaces.value = wsComposable?.workspaces?.value ?? wsComposable?.data?.value ?? workspaces.value
})

// Controlled image sources (P1-A image slots only — no network / AI URLs).
const IMAGE_SOURCES = ['builtin_icon', 'preset_photo', 'image_slot_1', 'image_slot_2']

const model = reactive<Stage3Data>({
  generation_mode: 'structured',
  page_count: 6,
  image_sources: [],
  native_chart_policy: 'native',
  native_table_policy: 'native',
  formula_policy: 'native',
  pptx_structure_mode: 'structured',
  structured_workspace_id: null,
  structured_workspace_revision: null,
  animation_policy: 'none',
  refinement_policy: 'conservative',
  source_handling_summary: '',
})

// Hydrate from server-prepared stage3 defaults (truth), preserving user edits.
watch(
  () => store.stage3,
  (s) => {
    if (s) Object.assign(model, s)
  },
  { immediate: true },
)

function toggleImage(src: string) {
  const i = model.image_sources.indexOf(src)
  if (i >= 0) model.image_sources.splice(i, 1)
  else model.image_sources.push(src)
}

function onWorkspaceChange(id: string) {
  model.structured_workspace_id = id || null
  const found = workspaces.value.find((w) => String(w.id) === String(id))
  model.structured_workspace_revision = found?.revision ?? found?.version ?? null
  // keep structure mode consistent with chosen workspace
  if (id) model.pptx_structure_mode = 'structured'
}

// When structure mode flips to flat, clear the workspace binding.
watch(
  () => model.pptx_structure_mode,
  (m) => {
    if (m === 'flat') {
      model.structured_workspace_id = null
      model.structured_workspace_revision = null
    }
  },
)

const canConfirm = computed(() => model.page_count > 0 && !store.loading)

async function onConfirm() {
  if (!canConfirm.value) return
  // stage3 is edited in-place and never PATCHed, so forward the config dict as
  // the stage data (the server keeps stored data only when a dict is supplied).
  await store.confirm('stage3', { stage3_data: { ...model } })
}
</script>

<template>
  <section class="stage3 w-full" aria-label="Stage 3 生成配置">
    <header class="mb-4">
      <h2 class="text-lg font-semibold tracking-tight text-slate-900">第 3 步 · 生成配置</h2>
      <p class="text-sm text-slate-500">确认最终生成参数，提交后状态变为已确认，可发起生成。</p>
    </header>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium text-slate-700">生成模式</label>
        <select v-model="model.generation_mode" class="rounded-lg border border-slate-200 px-3 py-2 text-sm">
          <option value="structured">结构化 (structured)</option>
          <option value="flat">扁平 (flat)</option>
        </select>
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium text-slate-700">页数</label>
        <input v-model.number="model.page_count" type="number" min="1" class="rounded-lg border border-slate-200 px-3 py-2 text-sm" />
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium text-slate-700">PPTX 结构模式</label>
        <select v-model="model.pptx_structure_mode" class="rounded-lg border border-slate-200 px-3 py-2 text-sm">
          <option value="flat">flat</option>
          <option value="structured">structured</option>
        </select>
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium text-slate-700">结构化工作区</label>
        <select
          :value="model.structured_workspace_id ?? ''"
          class="rounded-lg border border-slate-200 px-3 py-2 text-sm"
          :disabled="model.pptx_structure_mode === 'flat'"
          @change="onWorkspaceChange(($event.target as HTMLSelectElement).value)"
        >
          <option value="">— 不使用 —</option>
          <option v-for="w in workspaces" :key="w.id" :value="w.id">{{ w.name || w.id }}</option>
        </select>
        <p v-if="wsLoading" class="text-xs text-slate-400">工作区加载中…</p>
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium text-slate-700">图表策略 (P1-B)</label>
        <select v-model="model.native_chart_policy" class="rounded-lg border border-slate-200 px-3 py-2 text-sm">
          <option value="native">native</option>
          <option value="none">none</option>
        </select>
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium text-slate-700">表格策略 (P1-B)</label>
        <select v-model="model.native_table_policy" class="rounded-lg border border-slate-200 px-3 py-2 text-sm">
          <option value="native">native</option>
          <option value="none">none</option>
        </select>
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium text-slate-700">公式策略</label>
        <select v-model="model.formula_policy" class="rounded-lg border border-slate-200 px-3 py-2 text-sm">
          <option value="native">native</option>
          <option value="none">none</option>
        </select>
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium text-slate-700">动画策略 (仅 none / basic_allowed)</label>
        <select v-model="model.animation_policy" class="rounded-lg border border-slate-200 px-3 py-2 text-sm">
          <option value="none">none</option>
          <option value="basic_allowed">basic_allowed</option>
        </select>
      </div>

      <div class="flex flex-col gap-1 md:col-span-2">
        <label class="text-sm font-medium text-slate-700">精修策略</label>
        <input v-model="model.refinement_policy" type="text" class="rounded-lg border border-slate-200 px-3 py-2 text-sm" />
      </div>

      <div class="flex flex-col gap-1 md:col-span-2">
        <label class="text-sm font-medium text-slate-700">来源处理说明</label>
        <textarea v-model="model.source_handling_summary" rows="2" class="rounded-lg border border-slate-200 px-3 py-2 text-sm" />
      </div>

      <div class="flex flex-col gap-1 md:col-span-2">
        <label class="text-sm font-medium text-slate-700">图片来源（受控，仅 P1-A 图位）</label>
        <div class="flex flex-wrap gap-2">
          <label v-for="src in IMAGE_SOURCES" :key="src" class="inline-flex items-center gap-1 text-sm text-slate-600">
            <input type="checkbox" :checked="model.image_sources.includes(src)" @change="toggleImage(src)" />
            {{ src }}
          </label>
        </div>
      </div>
    </div>

    <div class="mt-5 flex flex-wrap gap-3">
      <button
        type="button"
        class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50"
        :disabled="store.loading || !store.stage2Confirmed"
        @click="store.reviseTo('stage2')"
      >
        返回修改第 2 步
      </button>
      <button
        type="button"
        class="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 active:scale-[0.98]"
        :disabled="!canConfirm"
        @click="onConfirm"
      >
        确认配置
      </button>
    </div>
  </section>
</template>
