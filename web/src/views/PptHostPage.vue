<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { BookOpen, FileText, MessageSquare, Presentation } from "lucide-vue-next";
import AppHeader from "../components/AppHeader.vue";
import { handleUnauthorized } from "../api.js";
import { getSessionToken } from "../stores/auth.js";
import {
  HttpPptWorkflowAdapter,
  LegacyPptMasterAdapter,
  PptWorkbenchPage,
} from "../features/ppt-workbench";
import RecentPptProjects from "../features/ppt-workbench/components/chat/RecentPptProjects.vue";
import "../features/ppt-workbench/ppt-workbench.css";

const route = useRoute();
const router = useRouter();
const projectId = computed(() => String(route.params.projectId ?? ""));

const configuredPageCount = Number.parseInt(import.meta.env.VITE_PPT_MASTER_PAGE_COUNT ?? "8", 10);
const pageCount = Number.isInteger(configuredPageCount) && configuredPageCount >= 1 && configuredPageCount <= 12
  ? configuredPageCount
  : 8;
const baseUrl = (import.meta.env.VITE_PPT_MASTER_BASE_URL || window.location.origin).replace(/\/+$/, "");

// The host page is the composition boundary. Stores and shell only consume the
// normalized adapter contract and never read host auth or raw SSE data.
const legacyAdapter = new LegacyPptMasterAdapter({
  baseUrl,
  pageCount,
  pageFormat: "ppt169",
  getAccessToken: getSessionToken,
  onUnauthorized: handleUnauthorized,
  verifyDownloadSha256: Boolean(globalThis.crypto?.subtle),
});
const incrementalEnabled = import.meta.env.VITE_PPT_INCREMENTAL_ENABLED !== "false";
const adapter = incrementalEnabled
  ? new HttpPptWorkflowAdapter({
    baseUrl,
    pageCount,
    pageFormat: "ppt169",
    getAccessToken: getSessionToken,
    onUnauthorized: handleUnauthorized,
    verifyDownloadSha256: Boolean(globalThis.crypto?.subtle),
    fallbackAdapter: legacyAdapter,
  })
  : legacyAdapter;
</script>

<template>
  <main class="flex h-dvh min-w-0 flex-col overflow-hidden bg-[#e2e9f1] text-black">
    <AppHeader title="" subtitle="政务办公智能体" :show-logout="false" @goHome="router.push('/')" />

    <div class="flex min-h-0 min-w-0 flex-1 gap-3 p-3">
      <aside class="hidden w-[232px] shrink-0 rounded-[12px] border border-[#dce6f1] bg-white px-4 py-3 md:flex md:flex-col">
        <nav class="space-y-1.5">
          <button type="button" class="flex h-10 w-full items-center gap-2.5 rounded-[14px] px-3.5 text-left text-[14px] font-semibold text-[#667085] hover:bg-[#F6F8FC] hover:text-[#111827]" @click="router.push('/chat')">
            <MessageSquare class="size-4" :stroke-width="2" /><span>聊天</span>
          </button>
          <button type="button" class="flex h-10 w-full items-center gap-2.5 rounded-[14px] px-3.5 text-left text-[14px] font-semibold text-[#667085] hover:bg-[#F6F8FC] hover:text-[#111827]" @click="router.push('/document')">
            <FileText class="size-4" :stroke-width="2" /><span>文档</span>
          </button>
          <button type="button" class="flex h-10 w-full items-center gap-2.5 rounded-[14px] border border-[rgba(94,106,210,0.10)] bg-[#EEF2FF] px-3.5 text-left text-[14px] font-semibold text-[#5E6AD2] shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
            <Presentation class="size-4" :stroke-width="2" /><span>PPT 生成</span>
          </button>
          <button type="button" class="flex h-10 w-full items-center gap-2.5 rounded-[14px] px-3.5 text-left text-[14px] font-semibold text-[#667085] hover:bg-[#F6F8FC] hover:text-[#111827]" @click="router.push('/knowledge')">
            <BookOpen class="size-4" :stroke-width="2" /><span>知识库</span>
          </button>
        </nav>
        <RecentPptProjects :current-project-id="projectId" class="mt-5 min-h-0 flex-1 overflow-y-auto" />
      </aside>

      <section class="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[12px] border border-[#dce6f1] bg-white">
        <div class="flex shrink-0 items-center gap-2 overflow-x-auto border-b border-[#E6EAF2] bg-white px-3 py-2 md:hidden">
          <button type="button" class="h-10 shrink-0 rounded-[10px] px-3 text-[14px] font-semibold text-[#667085]" @click="router.push('/chat')">聊天</button>
          <button type="button" class="h-10 shrink-0 rounded-[10px] px-3 text-[14px] font-semibold text-[#667085]" @click="router.push('/document')">文档</button>
          <button type="button" class="h-10 shrink-0 rounded-[10px] bg-[#EEF2FF] px-3 text-[14px] font-semibold text-[#5E6AD2]">PPT 生成</button>
        </div>
        <PptWorkbenchPage :project-id="projectId" :adapter="adapter" class="min-h-0 flex-1" />
      </section>
    </div>
  </main>
</template>
