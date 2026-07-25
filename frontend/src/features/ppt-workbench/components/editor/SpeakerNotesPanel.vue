<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { ChevronDown, ChevronUp, FileText } from "lucide-vue-next";
import { usePptProjectStore } from "../../stores/pptProject";
import { usePptWorkspaceStore } from "../../stores/pptWorkspace";

const { slides } = storeToRefs(usePptProjectStore());
const workspace = usePptWorkspaceStore();
const slide = computed(() => slides.value.find((item) => item.id === workspace.selectedSlideId) ?? slides.value[0]);
// Collapse state lives in the persisted workspace store so it survives reloads
// and is restored by useWorkspacePersistence (acceptance: panel-collapse persistence).
const collapsed = computed({
  get: () => workspace.speakerNotesCollapsed,
  set: (value: boolean) => { workspace.speakerNotesCollapsed = value; },
});
const summary = computed(() => (slide.value?.speakerNotes || "").trim().split("\n")[0].slice(0, 60));
</script>

<template>
  <section data-speaker-notes class="shrink-0 border-t border-[var(--ppt-border)] bg-[var(--ppt-surface)]">
    <button
      type="button"
      class="flex w-full items-center gap-2 px-4 py-2 text-left"
      :aria-expanded="!collapsed"
      aria-controls="speaker-notes-body"
      @click="collapsed = !collapsed"
    >
      <FileText class="h-4 w-4 text-[var(--ppt-text-muted)]" />
      <span class="text-sm font-medium text-[var(--ppt-text)]">演讲稿</span>
      <span v-if="collapsed && summary" class="min-w-0 flex-1 truncate text-xs text-[var(--ppt-text-muted)]">{{ summary }}</span>
      <span v-else-if="collapsed" class="min-w-0 flex-1 truncate text-xs text-[var(--ppt-text-muted)]">随当前页面切换</span>
      <span v-if="!collapsed" class="min-w-0 flex-1 truncate text-xs text-[var(--ppt-text-muted)]">随当前页面切换</span>
      <ChevronDown v-if="collapsed" class="h-4 w-4 text-[var(--ppt-text-muted)]" />
      <ChevronUp v-else class="h-4 w-4 text-[var(--ppt-text-muted)]" />
    </button>
    <div
      id="speaker-notes-body"
      class="overflow-hidden transition-[max-height] duration-200"
      :style="{ maxHeight: collapsed ? '0px' : '240px' }"
    >
      <p class="max-h-56 overflow-y-auto whitespace-pre-wrap px-4 pb-4 text-sm leading-6 text-[var(--ppt-text-sub)]">
        {{ slide?.speakerNotes || '当前页面暂无演讲稿，生成后会在这里显示。' }}
      </p>
    </div>
  </section>
</template>
