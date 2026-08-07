<template>
  <div class="rounded-[16px] border border-[#E5E7EB] bg-white p-6 shadow-[0_1px_3px_rgba(16,24,40,0.06)]">
    <div class="mb-5 flex items-center justify-between">
      <h2 class="text-[16px] font-semibold tracking-[-0.01em] text-[#111827]">本地模型（只读）</h2>
      <button
        type="button"
        class="rounded-[10px] p-2 text-[#98A2B3] transition-all duration-150 hover:bg-[#F8FAFC] hover:text-[#475467]"
        :class="{ 'animate-spin': refreshing }"
        :disabled="refreshing"
        @click="refresh"
      >
        <RefreshCw class="size-[18px]" :stroke-width="1.5" />
      </button>
    </div>

    <div v-if="store.localModels.length === 0" class="py-4 text-center text-[13px] text-[#98A2B3]">
      加载中...
    </div>

    <div v-else class="space-y-2.5">
      <div
        v-for="m in store.localModels"
        :key="m.port"
        class="flex items-center justify-between rounded-[12px] border border-[#F2F4F7] bg-[#FCFCFD] px-4 py-3"
      >
        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <span class="truncate text-[14px] font-semibold text-[#111827]">{{ m.name }}</span>
            <span class="shrink-0 rounded-[6px] bg-[#F2F4F7] px-2 py-0.5 text-[11px] font-medium text-[#667085]">{{ m.role }}</span>
          </div>
          <div class="mt-0.5 flex items-center gap-2 text-[12px] text-[#98A2B3]">
            <span>{{ m.model }}</span>
            <span>·</span>
            <span>端口 {{ m.port }}</span>
          </div>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <span
            class="inline-block size-2 rounded-full"
            :class="m.status === 'running' ? 'bg-[#12B76A]' : 'bg-[#F04438]'"
          />
          <span
            class="text-[13px] font-medium"
            :class="m.status === 'running' ? 'text-[#067647]' : 'text-[#B42318]'"
          >
            {{ m.status === 'running' ? '运行中' : '已停止' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue"
import { RefreshCw } from "lucide-vue-next"
import { useSettingsStore } from "../stores/settings.js"

const store = useSettingsStore()
const refreshing = ref(false)

async function refresh() {
  refreshing.value = true
  await store.loadLocalModels()
  refreshing.value = false
}

onMounted(() => store.loadLocalModels())
</script>
