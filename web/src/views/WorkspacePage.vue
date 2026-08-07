<template>
  <main class="flex h-dvh flex-col overflow-hidden bg-[#F5F7FB] text-black">
    <AppHeader title="" subtitle="知识库" @goHome="router.push('/')" @logout="router.push('/login')" />

    <div class="flex min-h-0 flex-1">
      <aside class="hidden w-[220px] shrink-0 border-r border-[#E6EAF2] bg-[rgba(255,255,255,0.92)] px-3 py-4 shadow-[0_2px_10px_rgba(16,24,40,0.04)] backdrop-blur-sm md:flex md:min-h-0 md:flex-col">
        <nav class="shrink-0 space-y-1.5 pb-5">
          <button type="button" class="flex h-11 w-full items-center gap-3 rounded-[14px] border border-transparent px-3.5 text-left text-[14px] font-medium text-[#667085] transition-all duration-150 hover:border-[#E6EAF2] hover:bg-[#F6F8FC] hover:text-[#111827]" @click="router.push('/chat')">
            <MessageSquare class="size-4" :stroke-width="2" />
            <span>聊天</span>
          </button>
          <button type="button" class="flex h-11 w-full items-center gap-3 rounded-[14px] border border-transparent px-3.5 text-left text-[14px] font-medium text-[#667085] transition-all duration-150 hover:border-[#E6EAF2] hover:bg-[#F6F8FC] hover:text-[#111827]" @click="router.push('/document')">
            <FileText class="size-4" :stroke-width="2" />
            <span>文档</span>
          </button>
          <button type="button" class="flex h-11 w-full items-center gap-3 rounded-[14px] border border-transparent px-3.5 text-left text-[14px] font-medium text-[#667085] transition-all duration-150 hover:border-[#E6EAF2] hover:bg-[#F6F8FC] hover:text-[#111827]" @click="router.push('/ppt')">
            <Presentation class="size-4" :stroke-width="2" />
            <span>PPT 生成</span>
          </button>
          <button class="flex h-11 w-full items-center gap-3 rounded-[14px] border border-[rgba(94,106,210,0.10)] bg-[#EEF2FF] px-3.5 text-left text-[14px] font-medium text-[#5E6AD2] shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-all duration-150">
            <FolderOpen class="size-4" :stroke-width="2" />
            <span>知识库</span>
          </button>
          <button type="button" class="flex h-11 w-full items-center gap-3 rounded-[14px] border border-transparent px-3.5 text-left text-[14px] font-medium text-[#667085] transition-all duration-150 hover:border-[#E6EAF2] hover:bg-[#F6F8FC] hover:text-[#111827]" @click="router.push('/settings')">
            <Settings class="size-4" :stroke-width="2" />
            <span>设置</span>
          </button>
        </nav>
      </aside>

      <section class="flex min-w-0 flex-1 flex-col">
        <div class="flex items-center gap-2 overflow-x-auto border-b border-[#E6EAF2] bg-[rgba(255,255,255,0.9)] px-3 py-2 md:hidden">
          <button class="h-9 shrink-0 rounded-[10px] border border-[rgba(94,106,210,0.10)] bg-[#EEF2FF] px-3 text-[14px] font-medium text-[#5E6AD2] shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
            知识库
          </button>
        </div>

        <div class="min-h-0 flex-1 overflow-hidden p-4 md:p-5">
          <KnowledgeMode />
        </div>
      </section>
    </div>
  </main>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { FileText, FolderOpen, MessageSquare, Presentation, Settings } from 'lucide-vue-next'
import AppHeader from '../components/AppHeader.vue'
import KnowledgeMode from '../components/KnowledgeMode.vue'

const router = useRouter()
</script>
