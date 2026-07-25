<script setup lang="ts">
// ErrorRetry.vue — generic error + retry component.
import { computed } from 'vue'
import { useGuidedPlanner } from './useGuidedPlanner'
import type { ApiError } from './guidedApi'

const props = defineProps<{ error: ApiError | null }>()
const emit = defineEmits<{ retry: [] }>()

const store = useGuidedPlanner()

const title = computed(() => {
  if (!props.error) return '出错了'
  if (props.error.status === 403) return '功能未授权'
  if (props.error.status === 404) return '项目不存在'
  return `请求失败 (${props.error.status || '网络'})`
})
</script>

<template>
  <div v-if="error" class="rounded-xl border border-rose-200 bg-rose-50 p-4" role="alert">
    <h3 class="text-sm font-semibold text-rose-800">{{ title }}</h3>
    <p class="mt-1 text-sm text-rose-700">{{ error.message }}<span v-if="error.error_code">（{{ error.error_code }}）</span></p>
    <div class="mt-3 flex gap-2">
      <button
        type="button"
        class="rounded-lg bg-rose-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-600"
        @click="emit('retry')"
      >
        重试
      </button>
      <button
        type="button"
        class="rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-200"
        @click="store.dismissConflict()"
      >
        关闭
      </button>
    </div>
  </div>
</template>
