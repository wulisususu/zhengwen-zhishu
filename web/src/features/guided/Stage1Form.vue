<script setup lang="ts">
// Stage1Form.vue — Stage 1 "目标与信息" form (P3B_SPEC.md §5 Stage1).
// Each field keeps an editable `value` plus the API `suggested_value`, source and
// confidence hints. Save = PATCH /stage, Confirm = POST /confirm{stage:'stage1'}.
import { computed, reactive, watch } from 'vue'
import { useGuidedPlanner } from './useGuidedPlanner'
import type { Stage1Data, StageField } from './guidedApi'

const store = useGuidedPlanner()

interface FieldMeta {
  key: string
  label: string
  type: 'text' | 'textarea' | 'number' | 'select'
  required: boolean
  options?: string[]
  help?: string
}

// Required gate: these must be non-empty before Confirm is allowed.
const FIELDS: FieldMeta[] = [
  { key: 'audience', label: '目标受众', type: 'text', required: true, help: '谁会看到这份演示？' },
  { key: 'communication_intent', label: '沟通意图', type: 'select', required: true, options: ['告知', '说服', '激励', '培训', '汇报'], help: '你希望受众看完后做什么？' },
  { key: 'audience_outcome', label: '受众收获', type: 'textarea', required: false },
  { key: 'core_message', label: '核心信息', type: 'textarea', required: true, help: '一句话主张。' },
  { key: 'delivery_context', label: '交付场景', type: 'text', required: false, help: '会议 / 路演 / 在线？' },
  { key: 'artifact_afterlife', label: '产物后续用途', type: 'text', required: false },
  { key: 'content_divergence', label: '内容发散度', type: 'select', required: false, options: ['保守', '均衡', '发散'] },
  { key: 'canvas', label: '画布比例', type: 'select', required: false, options: ['16:9', '4:3', 'A4'] },
  { key: 'language', label: '语言', type: 'text', required: true, help: '如 zh-CN / en-US' },
  { key: 'requested_page_count', label: '期望页数', type: 'number', required: true },
]

interface EditableField {
  value: string
  user_modified: boolean
}

const model = reactive<Record<string, EditableField>>({})

function emptyField(): EditableField {
  return { value: '', user_modified: false }
}

// Sync local model from the API-backed store.stage1 (truth), preserving edits.
function hydrate() {
  const src = store.stage1 as Stage1Data | null
  for (const f of FIELDS) {
    const existing = model[f.key] ?? emptyField()
    if (src && src[f.key]) {
      const sf = src[f.key] as StageField
      // Only adopt the server value if the user has not locally modified it.
      if (!existing.user_modified) existing.value = sf.value == null ? '' : String(sf.value)
    } else if (!existing.user_modified) {
      existing.value = ''
    }
    model[f.key] = existing
  }
}

watch(() => store.stage1, hydrate, { immediate: true, deep: true })

function onInput(f: FieldMeta, raw: string) {
  model[f.key].value = raw
  model[f.key].user_modified = true
}

function suggested(key: string): string {
  const sf = store.stage1?.[key] as StageField | undefined
  if (!sf || sf.suggested_value == null) return ''
  return String(sf.suggested_value)
}

function hint(key: string): string {
  const sf = store.stage1?.[key] as StageField | undefined
  if (!sf) return ''
  return `来源:${sf.source} 置信度:${(sf.confidence * 100).toFixed(0)}%`
}

const missingRequired = computed(() =>
  FIELDS.filter((f) => f.required && !String(model[f.key]?.value ?? '').trim()).map((f) => f.label),
)

const canConfirm = computed(() => missingRequired.value.length === 0 && !store.loading)

function buildPayload(): Stage1Data {
  const payload: Stage1Data = {}
  for (const f of FIELDS) {
    const src = (store.stage1?.[f.key] as StageField) || null
    payload[f.key] = {
      value: f.type === 'number' ? Number(model[f.key].value) : model[f.key].value,
      suggested_value: src ? src.suggested_value : model[f.key].value,
      source: src ? src.source : 'user',
      confidence: src ? src.confidence : 0,
      user_modified: model[f.key].user_modified,
    }
  }
  return payload
}

async function onSave() {
  await store.saveStage1(buildPayload())
}

async function onConfirm() {
  if (!canConfirm.value) return
  const payload = buildPayload()
  await store.saveStage1(payload)
  await store.confirm('stage1', { stage1_data: payload })
}
</script>

<template>
  <section class="stage1 w-full overflow-x-hidden" aria-label="Stage 1 目标与信息">
    <header class="mb-4">
      <h2 class="text-lg font-semibold tracking-tight text-slate-900">第 1 步 · 目标与信息</h2>
      <p class="text-sm text-slate-500">系统已给出建议值（灰色），可直接采用或编辑。</p>
    </header>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div v-for="f in FIELDS" :key="f.key" class="flex flex-col gap-1">
        <label :for="`s1-${f.key}`" class="text-sm font-medium text-slate-700">
          {{ f.label }}<span v-if="f.required" class="text-rose-500"> *</span>
        </label>

        <p v-if="suggested(f.key)" class="text-xs text-slate-400">建议：{{ suggested(f.key) }} · {{ hint(f.key) }}</p>

        <textarea
          v-if="f.type === 'textarea'"
          :id="`s1-${f.key}`"
          :value="model[f.key]?.value ?? ''"
          rows="2"
          class="rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
          @input="onInput(f, ($event.target as HTMLTextAreaElement).value)"
        />
        <select
          v-else-if="f.type === 'select'"
          :id="`s1-${f.key}`"
          :value="model[f.key]?.value ?? ''"
          class="rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
          @change="onInput(f, ($event.target as HTMLSelectElement).value)"
        >
          <option value="">— 请选择 —</option>
          <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
        </select>
        <input
          v-else
          :id="`s1-${f.key}`"
          :type="f.type === 'number' ? 'number' : 'text'"
          :value="model[f.key]?.value ?? ''"
          class="rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
          @input="onInput(f, ($event.target as HTMLInputElement).value)"
        />

        <p v-if="f.help" class="text-xs text-slate-400">{{ f.help }}</p>
      </div>
    </div>

    <p v-if="missingRequired.length" class="mt-3 text-sm text-rose-600">
      请先填写必填项：{{ missingRequired.join('、') }}
    </p>

    <div class="mt-5 flex flex-wrap gap-3">
      <button
        type="button"
        class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50"
        :disabled="store.loading"
        @click="onSave"
      >
        保存草稿
      </button>
      <button
        type="button"
        class="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 active:scale-[0.98]"
        :disabled="!canConfirm"
        @click="onConfirm"
      >
        确认并继续
      </button>
    </div>
  </section>
</template>
