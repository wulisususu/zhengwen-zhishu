<script setup lang="ts">
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { ArrowUp, ArrowDown } from "lucide-vue-next";
import { usePptProjectStore } from "../../stores/pptProject";
import { usePptWorkspaceStore } from "../../stores/pptWorkspace";
import { usePptGenerationStore } from "../../stores/pptGeneration";
import { usePptEditorStore } from "../../stores/pptEditor";
import type { Slide } from "../../types/presentation";
import SlideThumbnail from "./SlideThumbnail.vue";

const props = defineProps<{ incremental: boolean }>();
const projectStore = usePptProjectStore(); const { slides, project } = storeToRefs(projectStore);
const workspace = usePptWorkspaceStore(); const generation = usePptGenerationStore(); const editor = usePptEditorStore(); const list = ref<HTMLElement | null>(null);
const editorSlides = computed(() => editor.document?.slides ?? []);
const skeletonCount = computed(() => Math.max(3, Math.min(project.value?.brief.slideCount || 4, 12)));
const legacySkeletonCount = computed(() => Math.max(1, Math.min(generation.task?.requestedPageCount ?? 1, 12)));
const legacyArtifactReady = computed(() => !props.incremental && generation.status === "completed" && Boolean(project.value?.exportArtifact));
const railSummary = computed(() => editorSlides.value.length ? `${editorSlides.value.length} 页` : slides.value.length ? `${slides.value.length} 页` : !props.incremental ? legacyArtifactReady.value ? "文件已生成" : generation.status === "running" ? `${legacySkeletonCount.value} 页占位` : "无逐页预览" : `${skeletonCount.value} 页`);

// Map editor slides to Slide-shaped objects so the existing, tested
// SlideThumbnail component renders real 16:9 previews (when available)
// without leaking internal ids or element counts into the UI.
const displaySlides = computed<Slide[]>(() =>
  editorSlides.value.map((slide, index) => {
    const gen = slides.value[index];
    return {
      id: slide.slide_id,
      index: index + 1,
      title: gen?.title ?? "",
      status: "ready",
      elements: slide.elements,
      thumbnailUrl: gen?.thumbnailUrl ?? gen?.previewUrl ?? undefined,
      speakerNotes: "",
      userModifiedFields: [],
      revision: 1,
    } as unknown as Slide;
  }),
);

function selectSlide(id: string) { editor.selectedSlideId = id; workspace.selectSlide(id); }
function reorder(index: number, delta: number) {
  const target = index + delta;
  if (target < 0 || target >= editorSlides.value.length) return;
  editor.reorderSlides(index, target);
  editor.scheduleSave();
}
function saveScroll() { if (list.value) workspace.slideRailScrollTop = list.value.scrollTop; }
</script>
<template>
  <aside data-slide-rail class="flex h-full min-h-0 flex-col border-r border-[var(--ppt-border)] bg-[var(--ppt-surface)]">
    <header class="flex h-14 shrink-0 items-center justify-between border-b border-[var(--ppt-border)] px-3">
      <strong class="text-sm text-[var(--ppt-text)]">幻灯片</strong>
      <span class="text-xs text-[var(--ppt-text-muted)]">{{ railSummary }}</span>
    </header>
    <div ref="list" class="min-h-0 flex-1 space-y-3 overflow-y-auto p-3" @scroll.passive="saveScroll">
      <template v-if="displaySlides.length">
        <div v-for="(slide, index) in displaySlides" :key="slide.id" class="group/thumb relative">
          <SlideThumbnail :slide="slide" :selected="editor.selectedSlideId === slide.id" @select="selectSlide(slide.id)" />
          <div class="absolute right-2 top-2 z-10 hidden gap-1 rounded-md bg-[var(--ppt-surface)]/95 p-0.5 shadow-[var(--ppt-shadow-sm)] group-hover/thumb:flex">
            <button type="button" class="ppt-thumb-reorder" :disabled="index === 0" :aria-label="`上移第 ${index + 1} 页`" @click="reorder(index, -1)">
              <ArrowUp class="h-3.5 w-3.5" />
            </button>
            <button type="button" class="ppt-thumb-reorder" :disabled="index === displaySlides.length - 1" :aria-label="`下移第 ${index + 1} 页`" @click="reorder(index, 1)">
              <ArrowDown class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </template>
      <template v-else-if="slides.length">
        <SlideThumbnail v-for="slide in slides" :key="slide.id" :slide="slide" :selected="workspace.selectedSlideId === slide.id" @select="selectSlide(slide.id)" />
      </template>
      <template v-else-if="!incremental">
        <div v-if="legacyArtifactReady" data-legacy-file-ready>PPTX 文件已生成，当前 Legacy 模式不提供逐页预览</div>
        <div v-else data-legacy-generation-placeholder>
          <p>后端正在一次性生成</p>
          <div v-for="index in legacySkeletonCount" :key="index" data-legacy-slide-skeleton>{{ index }} · 文件页占位</div>
        </div>
      </template>
      <template v-else>
        <div v-for="index in skeletonCount" :key="index" data-slide-skeleton class="rounded-xl border border-[var(--ppt-border)] bg-[var(--ppt-surface)] p-2">
          <div class="mb-2 text-[11px] text-[var(--ppt-text-muted)]">{{ index }} · 等待生成</div>
          <div class="aspect-video animate-pulse rounded-lg bg-[var(--ppt-surface-2)]" />
        </div>
      </template>
    </div>
  </aside>
</template>
