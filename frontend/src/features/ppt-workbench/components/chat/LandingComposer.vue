<script setup lang="ts">
import { computed, watch } from "vue";
import { usePptConversationStore } from "../../stores/pptConversation";
import { usePptUiStore } from "../../stores/pptUi";
import PromptSuggestions from "./PromptSuggestions.vue";
import { parsePromptPageCount, pptPageCountOptions } from "../../utils/pageCount";
import { useStructuredWorkspaces } from "../../composables/useStructuredWorkspaces";
import PptSourceAttachments from "./PptSourceAttachments.vue";
import { usePptSourcesStore } from "../../stores/pptSources";

defineProps<{ running: boolean }>();
const emit = defineEmits<{ submit: [prompt: string, pageCount: number, structuredMode?: string, workspaceId?: string]; "open-template-fill": []; "open-native-enhance": [] }>();
const conversation = usePptConversationStore();
const ui = usePptUiStore();
const sources = usePptSourcesStore();
const sourceBlocked = computed(() => sources.blocksGeneration);
const { workspaces, loading: workspacesLoading, loadError: workspacesError, load: loadWorkspaces } = useStructuredWorkspaces();

function onStructuredModeChange(value: "flat" | "structured") {
  ui.setStructuredMode(value, ui.structuredWorkspaceId);
  if (value === "structured") {
    void loadWorkspaces().then(() => {
      if (!ui.structuredWorkspaceId && workspaces.value.length > 0) {
        ui.setStructuredMode("structured", workspaces.value[0].workspace_id);
      }
    });
  }
}

const suggestions = [
  "做一份面向管理层的年度复盘 PPT",
  "把产品方案整理成 8 页路演稿",
  "生成一份培训课程演示文稿",
  "制作一个简洁的项目汇报 PPT",
];

function submit() {
  const prompt = conversation.draft.trim();
  if (!prompt || conversation.draft.length > 4000 || sourceBlocked.value) return;
  emit("submit", prompt, ui.selectedPageCount, ui.structuredMode, ui.structuredWorkspaceId ?? undefined);
}

watch(() => conversation.draft, (prompt) => {
  const detected = parsePromptPageCount(prompt);
  if (detected) ui.syncPageCountFromPrompt(detected);
});
</script>

<template>
  <section class="flex min-h-full w-full flex-col items-center justify-center px-6 py-12">
    <div class="w-full max-w-4xl text-center">
      <span class="inline-flex rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">AI 演示文稿工作台</span>
      <h1 class="mt-5 text-3xl font-semibold tracking-tight text-slate-900 sm:text-5xl">想做一份什么样的 PPT？</h1>
      <p class="mx-auto mt-4 max-w-2xl text-sm leading-7 text-slate-500 sm:text-base">描述主题、受众和使用场景，我会先梳理需求，再逐步生成大纲与幻灯片。</p>
      <form class="mx-auto mt-8 max-w-3xl rounded-3xl border border-slate-200 bg-white p-3 text-left shadow-[0_18px_55px_rgba(15,23,42,0.08)]" @submit.prevent="submit">
        <textarea
          v-model="conversation.draft"
          aria-label="PPT 需求输入"
          rows="5"
          maxlength="4000"
          class="min-h-32 w-full resize-none rounded-2xl border-0 bg-transparent px-4 py-3 text-base leading-7 text-slate-800 outline-none placeholder:text-slate-400"
          placeholder="例如：为管理层制作一份 8 页产品年度复盘，突出增长、挑战与下一步计划。"
        />
        <PptSourceAttachments :show-trigger="false" />
        <div v-if="sourceBlocked" class="mt-2 flex flex-wrap items-center gap-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <span>有来源文件尚未解析完成或解析失败。</span>
          <button type="button" class="rounded-md border border-amber-300 bg-white px-2 py-1 font-medium" @click="sources.setPolicy('ready_only')">仅使用已解析文件继续</button>
        </div>
        <div v-else-if="sources.policy === 'ready_only' && sources.items.length" class="mt-2 text-xs text-amber-700">将忽略仍在解析或解析失败的文件。</div>
        <div class="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-2 pt-3">
          <label class="flex min-w-0 items-center gap-2 text-xs text-slate-500">
            <PptSourceAttachments :show-cards="false" />
            <span class="shrink-0">生成页数</span>
            <select
              :value="ui.selectedPageCount"
              aria-label="生成页数"
              class="min-w-[74px] rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 outline-none focus:border-blue-400"
              @change="ui.setPageCount(($event.target as HTMLSelectElement).value)"
            >
              <option v-for="count in pptPageCountOptions" :key="count" :value="count">{{ count }}页</option>
            </select>
          </label>
          <label class="flex min-w-0 items-center gap-2 text-xs text-slate-500">
            <span class="shrink-0">PPT</span>
            <select
              :value="ui.structuredMode"
              aria-label="pptx-structure"
              class="min-w-[110px] rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 outline-none focus:border-blue-400"
              @change="onStructuredModeChange(($event.target as HTMLSelectElement).value as 'flat' | 'structured')"
            >
              <option value="flat">Fast (Flat)</option>
              <option value="structured">Structured</option>
            </select>
          </label>
          <label v-if="ui.structuredMode === 'structured'" class="flex min-w-0 items-center gap-2 text-xs text-slate-500">
            <span class="shrink-0">Workspace</span>
            <select
              :value="ui.structuredWorkspaceId ?? ''"
              aria-label="structured-workspace"
              :disabled="workspacesLoading || workspaces.length === 0"
              class="min-w-[140px] rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 outline-none focus:border-blue-400 disabled:opacity-50"
              @change="ui.setStructuredMode('structured', ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="ws in workspaces" :key="ws.workspace_id" :value="ws.workspace_id">{{ ws.name }}</option>
            </select>
            <span v-if="workspacesError" class="text-[11px] text-red-500">{{ workspacesError }}</span>
          </label>
          <button type="submit" class="rounded-full bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40" :disabled="running || !conversation.draft.trim() || sourceBlocked">
            {{ running ? "正在启动…" : "开始生成" }}
          </button>
        </div>
      </form>
      <div class="mt-5 flex flex-col items-center gap-3">
        <button type="button" data-open-native-enhance class="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="$emit('open-native-enhance')">增强已有 PPT</button>
        <button type="button" data-open-template-fill class="rounded-full border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-100" @click="$emit('open-template-fill')">使用我的 PPT 模板</button>
        <PromptSuggestions :suggestions="suggestions" @select="conversation.draft = $event" />
      </div>
    </div>
  </section>
</template>
