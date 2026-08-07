<template>
  <main class="flex h-dvh min-w-0 flex-col overflow-hidden bg-[#e2e9f1] text-black">
    <AppHeader title="设置" subtitle="外部模型 · 本地模型" :show-logout="false" @goHome="router.push('/')" />

    <div class="flex min-h-0 min-w-0 flex-1 gap-3 p-3">
      <!-- Sidebar -->
      <aside class="hidden w-[232px] shrink-0 rounded-[12px] border border-[#dce6f1] bg-white px-4 py-3 md:flex md:flex-col">
        <nav class="space-y-1.5">
          <button type="button" class="flex h-10 w-full items-center gap-2.5 rounded-[14px] px-3.5 text-left text-[14px] font-semibold text-[#667085] hover:bg-[#F6F8FC] hover:text-[#111827]" @click="router.push('/chat')">
            <MessageSquare class="size-4" :stroke-width="2" /><span>聊天</span>
          </button>
          <button type="button" class="flex h-10 w-full items-center gap-2.5 rounded-[14px] px-3.5 text-left text-[14px] font-semibold text-[#667085] hover:bg-[#F6F8FC] hover:text-[#111827]" @click="router.push('/document')">
            <FileText class="size-4" :stroke-width="2" /><span>文档</span>
          </button>
          <button type="button" class="flex h-10 w-full items-center gap-2.5 rounded-[14px] px-3.5 text-left text-[14px] font-semibold text-[#667085] hover:bg-[#F6F8FC] hover:text-[#111827]" @click="router.push('/ppt')">
            <Presentation class="size-4" :stroke-width="2" /><span>PPT 生成</span>
          </button>
          <button type="button" class="flex h-10 w-full items-center gap-2.5 rounded-[14px] px-3.5 text-left text-[14px] font-semibold text-[#667085] hover:bg-[#F6F8FC] hover:text-[#111827]" @click="router.push('/knowledge')">
            <BookOpen class="size-4" :stroke-width="2" /><span>知识库</span>
          </button>
          <button type="button" class="flex h-10 w-full items-center gap-2.5 rounded-[14px] border border-[rgba(94,106,210,0.10)] bg-[#EEF2FF] px-3.5 text-left text-[14px] font-semibold text-[#5E6AD2] shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
            <SettingsIcon class="size-4" :stroke-width="2" /><span>设置</span>
          </button>
        </nav>
      </aside>

      <!-- Content -->
      <section class="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto rounded-[12px] border border-[#dce6f1] bg-white p-5">
        <div class="mx-auto w-full max-w-[640px] space-y-6">
          <ExternalModelForm />
          <LocalModelStatus />
        </div>
      </section>
    </div>
  </main>
</template>

<script setup>
import { onMounted } from "vue"
import { useRouter } from "vue-router"
import { MessageSquare, FileText, Presentation, BookOpen, Settings as SettingsIcon } from "lucide-vue-next"
import AppHeader from "../components/AppHeader.vue"
import ExternalModelForm from "../components/ExternalModelForm.vue"
import LocalModelStatus from "../components/LocalModelStatus.vue"
import { useSettingsStore } from "../stores/settings.js"

const router = useRouter()
const store = useSettingsStore()

onMounted(() => {
  store.loadExternalModel()
  store.loadLocalModels()
})
</script>
