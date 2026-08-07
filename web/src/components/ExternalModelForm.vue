<template>
  <div class="rounded-[16px] border border-[#E5E7EB] bg-white p-6 shadow-[0_1px_3px_rgba(16,24,40,0.06)]">
    <h2 class="mb-2 text-[16px] font-semibold text-[#111827]">外部 OpenAI 兼容模型</h2>
    <p class="mb-5 text-[13px] text-[#667085]">保存后：外部模型优先；Chat 与文档均可降级到本地 Qwen 0.6B。</p>
    <div class="space-y-4">
      <div class="relative">
        <label class="mb-1.5 block text-[13px] font-medium text-[#475467]">服务地址</label>
        <input v-model="form.base_url" type="text" placeholder="http://192.168.1.10:8000/v1" :disabled="busy" class="input" />
      </div>
      <div class="relative">
        <label class="mb-1.5 block text-[13px] font-medium text-[#475467]">API Key（可选）</label>
        <input v-model="form.api_key" :type="showKey ? 'text' : 'password'" :placeholder="store.externalModel.api_key_configured ? '已配置，留空则保留原 Token' : '无鉴权服务可留空'" :disabled="busy || form.clear_api_key" class="input pr-10" />
        <button type="button" class="absolute right-3 top-9 text-[#98A2B3]" @click="showKey=!showKey"><Eye v-if="!showKey" class="size-[18px]" /><EyeOff v-else class="size-[18px]" /></button>
        <label v-if="store.externalModel.api_key_configured" class="mt-2 flex items-center gap-2 text-[12px] text-[#667085]"><input v-model="form.clear_api_key" type="checkbox" :disabled="busy" />清除已保存的 Token（仅无鉴权内网服务）</label>
      </div>
      <div class="relative"><label class="mb-1.5 block text-[13px] font-medium text-[#475467]">模型名称</label><input v-model="form.model" type="text" placeholder="deepseek-chat" :disabled="busy" class="input" /></div>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div class="relative"><label class="mb-1.5 block text-[13px] font-medium text-[#475467]">超时（秒）</label><input v-model.number="form.timeout_seconds" type="number" min="30" max="600" :disabled="busy" class="input" /></div>
        <div class="relative"><label class="mb-1.5 block text-[13px] font-medium text-[#475467]">上下文窗口</label><input v-model.number="form.context_window" type="number" min="4096" max="1048576" :disabled="busy" class="input" /></div>
        <div class="relative"><label class="mb-1.5 block text-[13px] font-medium text-[#475467]">最大输出</label><input v-model.number="form.max_tokens" type="number" min="256" :max="form.context_window" :disabled="busy" class="input" /></div>
      </div>
    </div>
    <div class="mt-5 flex gap-3">
      <button type="button" :disabled="busy || !form.base_url || !form.model" class="btn bg-[#5E6AD2] text-white" @click="handleTest"><Loader v-if="store.testing" class="size-4 animate-spin" />{{ store.testing ? '测试中...' : '测试连接与 Tool Call' }}</button>
      <button type="button" :disabled="busy || !testPassed" class="btn bg-[#12B76A] text-white" @click="handleSave"><Loader v-if="store.saving" class="size-4 animate-spin" />{{ store.saving ? '保存中...' : '保存并应用' }}</button>
    </div>
    <div v-if="store.testResult" class="mt-4 space-y-2 text-[13px]">
      <p :class="store.testResult.connectivity.ok ? 'text-[#067647]' : 'text-[#B42318]'">连通性：{{ store.testResult.connectivity.message }}</p>
      <p :class="store.testResult.tool_call.ok ? 'text-[#067647]' : 'text-[#B42318]'">Tool Call：{{ store.testResult.tool_call.message }}</p>
    </div>
    <p v-if="!store.saving && !store.saveError && store.externalModel.applied" class="mt-4 text-[13px] font-medium text-[#067647]">配置已保存，Chat 与 Doc Agent 已恢复运行。</p>
    <p v-if="!store.saving && !store.testing && store.saveError" class="mt-4 text-[13px] text-[#B42318]">{{ store.saveError }}</p>
  </div>
</template>
<script setup>
import { computed, reactive, ref, watch } from "vue"
import { Eye, EyeOff, Loader } from "lucide-vue-next"
import { useSettingsStore } from "../stores/settings.js"
const store = useSettingsStore()
const showKey = ref(false)
const form = reactive({ base_url:"", api_key:"", model:"", timeout_seconds:600, context_window:262144, max_tokens:32768, clear_api_key:false })
const busy = computed(() => store.saving || store.testing)
const testPassed = computed(() => store.testResult?.all_passed === true)
watch([() => form.base_url, () => form.api_key, () => form.model, () => form.timeout_seconds, () => form.context_window, () => form.max_tokens, () => form.clear_api_key], () => { store.testResult = null })
watch(() => store.externalModel, (value) => {
  form.base_url = value.base_url || ""; form.model = value.model || ""
  form.timeout_seconds = value.timeout_seconds || 600; form.context_window = value.context_window || 262144
  form.max_tokens = value.max_tokens || 32768; form.api_key = ""; form.clear_api_key = false
}, { immediate:true })
function buildConfig() {
  return { base_url:form.base_url.trim(), api_key:form.api_key.trim(), api_key_mode:form.clear_api_key ? "clear" : (form.api_key.trim() ? "replace" : "keep"), model:form.model.trim(), timeout_seconds:form.timeout_seconds, context_window:form.context_window, max_tokens:form.max_tokens }
}
async function handleTest() { await store.runTest(buildConfig()) }
async function handleSave() { await store.saveExternalModel(buildConfig()) }
</script>

<style scoped>.input{width:100%;border:1px solid #D0D5DD;border-radius:10px;padding:10px 14px;font-size:14px;outline:none}.input:focus{border-color:#5E6AD2}.btn{display:flex;align-items:center;gap:8px;border-radius:12px;padding:10px 18px;font-size:14px;font-weight:600}.btn:disabled{opacity:.5;cursor:not-allowed}</style>
