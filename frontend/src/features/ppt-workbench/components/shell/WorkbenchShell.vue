<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import ChatPanel from "../chat/ChatPanel.vue";
import SlideList from "../slides/SlideList.vue";
import EditorWorkspace from "../editor/EditorWorkspace.vue";
import TemplateFillWorkspace from "../template/TemplateFillWorkspace.vue";
import NativeEnhanceWorkspace from "../template/NativeEnhanceWorkspace.vue";
import ResizablePanel from "./ResizablePanel.vue";
import type { PptWorkflowController } from "../../composables/usePptWorkflow";
import { useWorkspacePersistence } from "../../composables/useWorkspacePersistence";
import { useProjectSessionPersistence } from "../../composables/useProjectSessionPersistence";
import { usePptGenerationStore } from "../../stores/pptGeneration";
import { usePptWorkspaceStore } from "../../stores/pptWorkspace";
import { usePptProjectStore } from "../../stores/pptProject";
import { usePptSourcesStore } from "../../stores/pptSources";
import { usePptEditorStore } from "../../stores/pptEditor";
import GuidedPlanner from "../../../guided/GuidedPlanner.vue";

const props = defineProps<{ projectId: string; workflow: PptWorkflowController }>();
const workspace = usePptWorkspaceStore();
const project = usePptProjectStore();
const generation = usePptGenerationStore();
const sources = usePptSourcesStore();
const editor = usePptEditorStore();
const { status } = storeToRefs(generation);
let openingFallback: number | undefined;
let stopPersistence: (() => void) | undefined;
let stopSessionPersistence: (() => void) | undefined;
let restoreToken = 0;
const downloadMessage = ref("");
const switching = ref(false);
const templateFillOpen = ref(false);
const nativeEnhanceOpen = ref(false);

const isConversation = computed(() => workspace.workspaceMode === "conversation");
const rootStyle = computed(() => ({
  "--chat-width": workspace.chatCollapsed ? "0px" : `${workspace.chatPanelWidth}px`,
  "--rail-width": workspace.slideRailCollapsed ? "0px" : `${workspace.slideRailWidth}px`,
}));

function ensureProject() {
  if (project.project?.id === props.projectId) return;
  project.setProject({
    id: props.projectId,
    title: "未命名 PPT",
    brief: { goal: "", audience: "", slideCount: 0, constraints: [] },
    outline: [],
    presentation: { aspectRatio: "16:9", slides: [] },
    theme: null,
    validation: null,
    version: 1,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  });
}

function slidesNeedingAssetRestore() {
  return project.slides.filter((slide) => slide.status === "ready" && (
    (!slide.previewUrl && typeof slide.previewArtifactId === "number")
    || (!slide.thumbnailUrl && typeof slide.thumbnailArtifactId === "number")
  ));
}

async function restorePersistedSlideAssets(token: number) {
  const slides = slidesNeedingAssetRestore();
  if (!slides.length) return;
  const restored = await props.workflow.restoreSlideAssets?.(slides);
  if (token !== restoreToken) return;
  if (Array.isArray(restored)) restored.forEach((slide) => project.upsertSlide(slide));
}

function start(prompt: string, pageCount?: number, structuredMode?: string, workspaceId?: string) {
  const normalized = prompt.trim();
  if (!normalized || normalized.length > 4000 || sources.blocksGeneration) return;
  try {
    const run = props.workflow.start({
      projectId: props.projectId,
      chatId: `chat-${props.projectId}`,
      prompt: normalized,
      pageCount,
      attachmentFileIds: sources.attachmentFileIds,
      knowledgeDocIds: sources.knowledgeDocIds,
      sourcePolicy: sources.policy,
      pptxStructureMode: structuredMode as "flat" | "structured" | undefined,
      structuredWorkspaceId: workspaceId ?? undefined,
    });
    void Promise.resolve(run);
  } catch {
    workspace.closeWorkbench();
  }
}

async function downloadLatest() {
  downloadMessage.value = "正在校验并下载…";
  try {
    const result = await props.workflow.downloadLatest();
    downloadMessage.value = `已下载 ${result.filename}`;
  } catch (cause) {
    downloadMessage.value = cause instanceof Error ? cause.message : "PPT 下载失败";
  }
}

function finishOpening(event?: TransitionEvent) {
  if (event && event.target !== event.currentTarget) return;
  if (openingFallback !== undefined) window.clearTimeout(openingFallback);
  openingFallback = undefined;
  workspace.finishOpening();
}

watch(() => workspace.workspaceMode, (mode) => {
  if (openingFallback !== undefined) window.clearTimeout(openingFallback);
  openingFallback = mode === "opening" ? window.setTimeout(() => finishOpening(), 560) : undefined;
});

async function activateProject(id: string) {
  if (!id) return;
  stopSessionPersistence?.();
  stopSessionPersistence = undefined;
  stopPersistence?.();
  stopPersistence = undefined;
  props.workflow.switchProject(id);
  switching.value = true;
  restoreToken += 1;
  const token = restoreToken;
  workspace.setProject(id);
  let history = null;
  if (props.workflow.capabilities.incrementalSlides && !id.startsWith("ppt-") && props.workflow.loadHistoryProject) {
    try { history = await props.workflow.loadHistoryProject(id); } catch { history = null; }
  }
  if (token !== restoreToken) return;
  const session = useProjectSessionPersistence(id);
  stopSessionPersistence = session.stop;
  if (history) {
    project.setProject({ ...history.project, isHistorical: true });
    workspace.selectSlide(history.project.presentation.slides[0]?.id ?? null);
    workspace.selectView("preview");
  } else if (!session.restored) ensureProject();
  // `/ppt` creates a client-side `ppt-*` session before generation. It has no
  // server draft yet, so loading the incremental editor would make a known 404.
  if (props.workflow.capabilities.incrementalSlides && !id.startsWith("ppt-")) {
    void editor.load(id).then(() => {
      // Only a server-backed draft may enter the editable workbench. A legacy
      // project never presents a fake editable canvas.
      if (token === restoreToken && editor.document?.project_id === id) workspace.beginOpening();
    });
  }
  void restorePersistedSlideAssets(token).finally(() => {
    if (token === restoreToken) switching.value = false;
  });
  stopPersistence = useWorkspacePersistence(id);
}

onMounted(() => { void activateProject(props.projectId); });

watch(() => props.projectId, (id, prev) => {
  if (id && id !== prev) void activateProject(id);
});

onBeforeUnmount(() => {
  if (openingFallback !== undefined) window.clearTimeout(openingFallback);
  stopPersistence?.();
  stopSessionPersistence?.();
});
</script>

<template>
  <main
    data-workspace-root
    :data-workspace-mode="workspace.workspaceMode"
    data-responsive-fallback
    class="ppt-workspace-root relative h-full min-h-0 min-w-0 bg-slate-50 text-slate-900"
    :style="rootStyle"
    @transitionend="finishOpening"
  >
    <div
      v-if="switching"
      data-project-switching
      class="absolute inset-0 z-30 flex items-center justify-center bg-white/80 backdrop-blur-sm"
    >
      <div class="flex items-center gap-2 text-sm font-medium text-slate-500">
        <span class="size-4 animate-spin rounded-full border-2 border-slate-300 border-t-[#5E6AD2]"></span>
        <span>正在切换 PPT 会话…</span>
      </div>
    </div>
    <template v-if="isConversation">
      <GuidedPlanner>
        <template #quick>
          <TemplateFillWorkspace v-if="templateFillOpen" @close="templateFillOpen = false" />
          <NativeEnhanceWorkspace v-else-if="nativeEnhanceOpen" @close="nativeEnhanceOpen = false" />
          <ChatPanel v-else mode="conversation" :running="status === 'running'" :incremental-slides="props.workflow.capabilities.incrementalSlides" :file-download="props.workflow.capabilities.fileDownload" :download-message="downloadMessage" @submit="start" @download="downloadLatest" @open-workbench="props.workflow.openWorkbench" @open-template-fill="templateFillOpen = true" @open-native-enhance="nativeEnhanceOpen = true" />
        </template>
      </GuidedPlanner>
    </template>
    <template v-else>
      <ResizablePanel v-show="!workspace.chatCollapsed" :width="workspace.chatPanelWidth" :min="340" :max="520" label="调整对话宽度" @update:width="workspace.setChatPanelWidth">
        <ChatPanel mode="workbench" :running="status === 'running'" :incremental-slides="props.workflow.capabilities.incrementalSlides" :file-download="props.workflow.capabilities.fileDownload" :download-message="downloadMessage" @submit="start" @download="downloadLatest" @open-workbench="props.workflow.openWorkbench" />
      </ResizablePanel>
      <ResizablePanel v-show="!workspace.slideRailCollapsed" :width="workspace.slideRailWidth" :min="148" :max="240" label="调整幻灯片栏宽度" @update:width="workspace.setSlideRailWidth">
        <SlideList :incremental="props.workflow.capabilities.incrementalSlides" />
      </ResizablePanel>
      <EditorWorkspace :project-id="props.projectId" :incremental="props.workflow.capabilities.incrementalSlides" @close="props.workflow.closeWorkbench" />
      <button v-if="workspace.chatCollapsed" type="button" class="ppt-panel-restore left-2" @click="workspace.chatCollapsed = false">显示对话</button>
      <button v-if="workspace.slideRailCollapsed" type="button" class="ppt-panel-restore left-24" @click="workspace.slideRailCollapsed = false">显示页面</button>
    </template>
  </main>
</template>
