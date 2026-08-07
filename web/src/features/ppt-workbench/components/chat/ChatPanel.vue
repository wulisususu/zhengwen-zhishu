<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { usePptConversationStore } from "../../stores/pptConversation";
import { usePptGenerationStore } from "../../stores/pptGeneration";
import { usePptProjectStore } from "../../stores/pptProject";
import LandingComposer from "./LandingComposer.vue";
import PptResultCard from "./PptResultCard.vue";
import BriefPanel from "../brief/BriefPanel.vue";
import OutlinePanel from "../outline/OutlinePanel.vue";

const props = withDefaults(defineProps<{
  running: boolean;
  mode: "conversation" | "workbench";
  downloadMessage?: string;
  incrementalSlides?: boolean;
  fileDownload?: boolean;
}>(), { incrementalSlides: true, fileDownload: false });
const emit = defineEmits<{ submit: [prompt: string, pageCount?: number, structuredMode?: string, workspaceId?: string]; "open-workbench": []; "open-template-fill": []; "open-native-enhance": []; download: [] }>();
const conversation = usePptConversationStore();
const generation = usePptGenerationStore();
const project = usePptProjectStore();
const list = ref<HTMLElement | null>(null);
const followsLatest = ref(true);

const hasTimeline = computed(() => conversation.messages.length > 0 || generation.status !== "idle");
const readySlides = computed(() => project.slides.filter((slide) => slide.status === "ready").length);
const showResult = computed(() => generation.status === "completed" || readySlides.value > 0
  || (generation.status === "failed" && Boolean(project.validation)));
const resultPageCount = computed(() => project.project?.exportArtifact?.slideCount ?? generation.task?.requestedPageCount ?? project.project?.brief.slideCount ?? readySlides.value);

function submit() {
  const prompt = conversation.draft.trim();
  if (!prompt || props.running || conversation.draft.length > 4000) return;
  emit("submit", prompt);
}

function submitLanding(prompt: string, pageCount: number, structuredMode?: string, workspaceId?: string) {
  emit("submit", prompt, pageCount, structuredMode, workspaceId);
}

function onScroll() {
  const element = list.value;
  if (!element) return;
  followsLatest.value = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
}

async function scrollToLatest() {
  await nextTick();
  if (list.value) list.value.scrollTop = list.value.scrollHeight;
  followsLatest.value = true;
}

function approveProposal(id: string) { project.approveAndApplyProposal(id); }
function rejectProposal(id: string) { project.updateProposalStatus(id, "rejected"); }

watch(() => conversation.messages.map((message) => message.content).join("|"), async () => {
  if (followsLatest.value) await scrollToLatest();
});

watch(() => props.mode, async (mode) => {
  if (mode === "conversation" && showResult.value) await scrollToLatest();
});

onMounted(() => {
  if (props.mode === "conversation" && showResult.value) void scrollToLatest();
});
</script>

<template>
  <section data-chat-panel class="flex h-full min-h-0 flex-col bg-white" :class="mode === 'workbench' ? 'border-r border-slate-200' : ''">
    <LandingComposer v-if="mode === 'conversation' && !hasTimeline" :running="running" @submit="submitLanding" @open-template-fill="$emit('open-template-fill')" @open-native-enhance="$emit('open-native-enhance')" />
    <template v-else>
      <header class="flex h-14 shrink-0 items-center justify-between border-b border-slate-100 px-5">
        <div><strong class="text-sm text-slate-900">PPT 创作助手</strong><span v-if="running" class="ml-2 text-xs text-blue-600">正在生成</span></div>
        <div class="flex items-center gap-3">
          <span class="text-xs text-slate-400">{{ mode === 'workbench' ? '与编辑器同步' : '生成对话' }}</span>
          <button
            v-if="mode === 'conversation' && running"
            data-open-workbench-early
            type="button"
            class="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:border-blue-200 hover:text-blue-700"
            @click="$emit('open-workbench')"
          >提前打开工作台</button>
        </div>
      </header>
      <div ref="list" data-conversation-timeline class="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-5" @scroll.passive="onScroll">
        <article v-for="message in conversation.messages" :key="message.id" class="flex" :class="message.role === 'user' ? 'justify-end' : 'justify-start'">
          <div
            v-if="message.kind === 'stage'"
            data-workflow-stage-card
            class="w-full rounded-2xl border border-blue-100 bg-blue-50/70 px-4 py-3"
          >
            <div class="flex items-center gap-3"><span class="grid h-8 w-8 place-items-center rounded-full bg-blue-100 text-blue-700">✦</span><div class="min-w-0 flex-1"><strong class="text-sm text-slate-800">{{ message.content }}</strong><div class="mt-2 h-1.5 overflow-hidden rounded-full bg-blue-100"><div class="h-full rounded-full bg-blue-500 transition-[width] duration-300" :style="{ width: `${message.taskId === generation.task?.id ? generation.displayProgress : message.progress ?? 0}%` }" /></div></div><span class="text-xs tabular-nums text-blue-600">{{ message.taskId === generation.task?.id ? generation.displayProgress : message.progress ?? 0 }}%</span></div>
          </div>
          <div v-else class="max-w-[90%] rounded-2xl px-4 py-3 text-sm leading-6" :class="message.role === 'user' ? 'rounded-br-md bg-slate-900 text-white' : 'rounded-bl-md bg-slate-100 text-slate-700'">
            {{ message.content }}<span v-if="message.streaming" class="ml-1 inline-block h-4 w-1 animate-pulse rounded bg-blue-500 align-middle" aria-label="正在输入" />
          </div>
        </article>
        <article v-if="generation.error" data-workflow-error role="alert" class="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
          <strong>{{ generation.status === "interrupted" ? "连接已中断" : "生成未完成" }}</strong>
          <p class="mt-1 leading-6 text-rose-800">{{ generation.error.message }}</p>
          <p v-if="generation.error.retryAfterSeconds" class="mt-1 text-xs text-rose-700">建议 {{ generation.error.retryAfterSeconds }} 秒后再试，请勿连续重复提交。</p>
        </article>
        <BriefPanel v-if="running || project.project?.brief.goal" />
        <OutlinePanel v-if="project.outline.length || generation.workflowStage === 'outline'" />
        <article v-for="proposal in project.proposals" :key="proposal.id" class="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-slate-800">
          <div class="font-semibold">AI 修改提案</div><p class="mt-1 leading-6 text-slate-600">{{ proposal.summary }}</p>
          <div v-if="proposal.status === 'pending'" class="mt-3 flex gap-2"><button class="rounded-lg bg-blue-600 px-3 py-1.5 text-white" @click="approveProposal(proposal.id)">批准并应用</button><button class="rounded-lg border border-slate-300 bg-white px-3 py-1.5" @click="rejectProposal(proposal.id)">拒绝</button></div>
          <p v-else class="mt-2 text-xs text-slate-500">状态：{{ proposal.status }}</p>
        </article>
        <PptResultCard
          v-if="showResult"
          :title="project.project?.title || '已生成演示文稿'"
          :completed="generation.status === 'completed'"
          :failed="generation.status === 'failed'"
          :ready-slides="readySlides"
          :page-count="resultPageCount"
          :incremental-slides="incrementalSlides"
          :temporary-title="project.project?.titleSource === 'frontend-prompt'"
          :download-available="fileDownload && Boolean(project.project?.exportArtifact?.valid)"
          :warnings="project.project?.exportArtifact?.warnings ?? []"
          :validation-issues="project.validation?.issues ?? []"
          :download-message="downloadMessage"
          @download="$emit('download')"
          @open="$emit('open-workbench')"
        />
      </div>
      <button v-if="!followsLatest" type="button" class="mx-auto mb-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 shadow-sm" @click="scrollToLatest">回到最新</button>
      <form class="shrink-0 border-t border-slate-100 bg-white p-3" @submit.prevent="submit">
        <textarea v-model="conversation.draft" aria-label="PPT 需求输入" rows="3" maxlength="4000" class="w-full resize-none rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm leading-6 outline-none focus:border-blue-400 focus:bg-white" placeholder="继续修改这份演示文稿…" />
        <div class="mt-2 flex items-center justify-between"><span class="text-xs text-slate-400">修改将先形成提案</span><button type="submit" class="rounded-full bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40" :disabled="running || !conversation.draft.trim()">发送</button></div>
      </form>
    </template>
  </section>
</template>
