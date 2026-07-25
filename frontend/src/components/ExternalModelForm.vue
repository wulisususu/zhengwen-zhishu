<template>
  <div class="rounded-[16px] border border-[#E5E7EB] bg-white p-6 shadow-[0_1px_3px_rgba(16,24,40,0.06)]">
    <h2 class="mb-5 text-[16px] font-semibold tracking-[-0.01em] text-[#111827]">外部大模型配置</h2>

    <div class="space-y-4">
      <div>
        <label class="mb-1.5 block text-[13px] font-medium text-[#475467]">服务地址</label>
        <input
          v-model="form.base_url"
          type="text"
          placeholder="https://api.deepseek.com"
          class="w-full rounded-[10px] border border-[#D0D5DD] bg-white px-3.5 py-2.5 text-[14px] text-[#111827] placeholder-[#98A2B3] outline-none transition-all duration-150 focus:border-[#5E6AD2] focus:ring-2 focus:ring-[#5E6AD2]/20"
          :disabled="store.saving || store.testing"
        />
      </div>

      <div>
        <label class="mb-1.5 block text-[13px] font-medium text-[#475467]">API Key</label>
        <div class="relative">
          <input
            v-model="form.api_key"
            :type="showKey ? 'text' : 'password'"
            placeholder="请输入 API Key"
            class="w-full rounded-[10px] border border-[#D0D5DD] bg-white py-2.5 pl-3.5 pr-10 text-[14px] text-[#111827] placeholder-[#98A2B3] outline-none transition-all duration-150 focus:border-[#5E6AD2] focus:ring-2 focus:ring-[#5E6AD2]/20"
            :disabled="store.saving || store.testing"
          />
          <button
            type="button"
            class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#98A2B3] transition-colors hover:text-[#475467]"
            @click="showKey = !showKey"
          >
            <Eye v-if="!showKey" class="size-[18px]" :stroke-width="1.5" />
            <EyeOff v-else class="size-[18px]" :stroke-width="1.5" />
          </button>
        </div>
      </div>

      <div>
        <label class="mb-1.5 block text-[13px] font-medium text-[#475467]">模型名称</label>
        <input
          v-model="form.model"
          type="text"
          placeholder="deepseek-chat"
          class="w-full rounded-[10px] border border-[#D0D5DD] bg-white px-3.5 py-2.5 text-[14px] text-[#111827] placeholder-[#98A2B3] outline-none transition-all duration-150 focus:border-[#5E6AD2] focus:ring-2 focus:ring-[#5E6AD2]/20"
          :disabled="store.saving || store.testing"
        />
      </div>

      <div>
        <label class="mb-1.5 block text-[13px] font-medium text-[#475467]">超时（秒）</label>
        <input
          v-model.number="form.timeout_seconds"
          type="number"
          min="30"
          max="600"
          class="w-36 rounded-[10px] border border-[#D0D5DD] bg-white px-3.5 py-2.5 text-[14px] text-[#111827] outline-none transition-all duration-150 focus:border-[#5E6AD2] focus:ring-2 focus:ring-[#5E6AD2]/20"
          :disabled="store.saving || store.testing"
        />
      </div>
    </div>

    <!-- Buttons -->
    <div class="mt-5 flex items-center gap-3">
      <!-- Step 1: Test -->
      <button
        type="button"
        class="flex items-center gap-2 rounded-[12px] px-5 py-2.5 text-[14px] font-semibold shadow-[0_1px_2px_rgba(16,24,40,0.05)] transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-50"
        :class="store.testing ? 'bg-[#98A2B3] text-white' : 'bg-[#5E6AD2] text-white hover:bg-[#4E5AC2] active:scale-[0.98]'"
        :disabled="store.testing || store.saving || !form.base_url || !form.model"
        @click="handleTest"
      >
        <Loader v-if="store.testing" class="size-[18px] animate-spin" :stroke-width="2" />
        {{ store.testing ? '测试中...' : '测试连接' }}
      </button>

      <!-- Step 2: Save (only after test passes) -->
      <button
        type="button"
        class="flex items-center gap-2 rounded-[12px] px-5 py-2.5 text-[14px] font-semibold shadow-[0_1px_2px_rgba(16,24,40,0.05)] transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-50"
        :class="store.saving ? 'bg-[#98A2B3] text-white' : 'bg-[#12B76A] text-white hover:bg-[#0E9F5E] active:scale-[0.98]'"
        :disabled="store.saving || store.testing || !testPassed"
        @click="handleSave"
      >
        <Loader v-if="store.saving" class="size-[18px] animate-spin" :stroke-width="2" />
        {{ store.saving ? '保存中...' : '保存配置' }}
      </button>
    </div>

    <!-- Test result -->
    <div v-if="store.testResult" class="mt-4 space-y-2">
      <!-- Connectivity -->
      <div class="flex items-center gap-2.5 text-[13px]" :class="store.testResult.connectivity.ok ? 'text-[#067647]' : 'text-[#B42318]'">
        <CircleCheck v-if="store.testResult.connectivity.ok" class="size-[16px]" :stroke-width="2" />
        <CircleAlert v-else class="size-[16px]" :stroke-width="2" />
        <span>连通性测试：{{ store.testResult.connectivity.message }}</span>
      </div>
      <!-- Tool call -->
      <div v-if="store.testResult.connectivity.ok" class="flex items-center gap-2.5 text-[13px]" :class="store.testResult.tool_call.ok ? 'text-[#067647]' : 'text-[#B42318]'">
        <CircleCheck v-if="store.testResult.tool_call.ok" class="size-[16px]" :stroke-width="2" />
        <CircleAlert v-else class="size-[16px]" :stroke-width="2" />
        <span>Tool Call 验证：{{ store.testResult.tool_call.message }}</span>
      </div>
      <!-- Summary -->
      <div v-if="store.testResult.connectivity.ok && store.testResult.tool_call.ok" class="flex items-center gap-2 rounded-[10px] bg-[#ECFDF3] px-3.5 py-2.5 text-[13px] font-medium text-[#067647]">
        <CircleCheck class="size-[16px]" :stroke-width="2" />
        <span>测试全部通过，可以保存配置</span>
      </div>
    </div>

    <!-- Save success / agent status -->
    <div v-if="!store.saving && !store.saveError && store.externalModel.applied" class="mt-4 flex items-center gap-2 rounded-[10px] bg-[#ECFDF3] px-3.5 py-2.5 text-[13px] font-medium text-[#067647]">
      <CircleCheck class="size-[16px]" :stroke-width="2" />
      <span>配置已保存，Agent {{ store.externalModel.agent_status === 'running' ? '运行中' : '状态: ' + store.externalModel.agent_status }}</span>
    </div>

    <!-- Error -->
    <div v-if="!store.saving && !store.testing && store.saveError" class="mt-4 flex items-start gap-2 rounded-[10px] bg-[#FEF3F2] px-3.5 py-2.5 text-[13px] font-medium text-[#B42318]">
      <CircleAlert class="mt-0.5 size-[16px] shrink-0" :stroke-width="2" />
      <span>{{ store.saveError }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { Eye, EyeOff, Loader, CircleCheck, CircleAlert } from "lucide-vue-next"
import { useSettingsStore } from "../stores/settings.js"

const store = useSettingsStore()

const form = reactive({
  base_url: "",
  api_key: "",
  model: "",
  timeout_seconds: 240,
})

const showKey = ref(false)

// Reset test result when form changes
watch([() => form.base_url, () => form.model, () => form.api_key], () => {
  store.testResult = null
})

watch(() => store.externalModel, (m) => {
  form.base_url = m.base_url || ""
  form.api_key = m.api_key || ""
  form.model = m.model || ""
  form.timeout_seconds = m.timeout_seconds || 240
}, { immediate: true })

const testPassed = computed(() => store.testResult?.all_passed === true)

function buildConfig() {
  return {
    base_url: form.base_url.trim(),
    api_key: form.api_key.trim(),
    model: form.model.trim(),
    timeout_seconds: form.timeout_seconds,
  }
}

async function handleTest() {
  store.saveError = ""
  store.testResult = null
  await store.runTest(buildConfig())
}

async function handleSave() {
  store.saveError = ""
  store.testResult = null
  await store.saveExternalModel(buildConfig())
}
</script>
