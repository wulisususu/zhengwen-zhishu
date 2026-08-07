<script setup lang="ts">
import { computed } from "vue";
import { usePptWorkspaceStore, type PptActiveView } from "../../stores/pptWorkspace";
import { usePptProjectStore } from "../../stores/pptProject";
import { usePptEditorStore } from "../../stores/pptEditor";
import EditorToolbar from "./EditorToolbar.vue";
import SlideEditor from "./SlideEditor.vue";
import SpeakerNotesPanel from "./SpeakerNotesPanel.vue";
import AnimationPanel from "../animation/AnimationPanel.vue";
import PreviewPanel from "../preview/PreviewPanel.vue";
import ValidationPanel from "../validation/ValidationPanel.vue";

withDefaults(defineProps<{ incremental?: boolean; projectId?: string }>(), { incremental: true, projectId: "" });
defineEmits<{ close: [] }>();
const workspace = usePptWorkspaceStore();
const project = usePptProjectStore();
const editor = usePptEditorStore();
const hasSpeakerNotes = computed(() => Boolean((project.slides.find((item) => item.id === workspace.selectedSlideId) ?? project.slides[0])?.speakerNotes?.trim()));
const historicalProject = computed(() => project.project?.isHistorical === true);
const currentView = computed(() => historicalProject.value ? "preview" : ["editor", "preview", "validation"].includes(workspace.activeView) ? workspace.activeView : "editor");
function selectView(view: PptActiveView) { workspace.selectView(historicalProject.value && view === "editor" ? "preview" : view); }
if (historicalProject.value && workspace.activeView === "editor") workspace.selectView("preview");
const structuredInfo = computed(() => {
  const slide = editor.document?.slides.find((item) => item.slide_id === editor.selectedSlideId) ?? editor.document?.slides[0];
  const structure = slide?.pptx_structure as { mode?: string; master_name?: string; layout_name?: string } | undefined;
  if (!structure || structure.mode !== "structured") return null;
  return structure;
});
</script>

<template>
  <section data-editor-workspace class="flex h-full min-h-0 min-w-0 flex-col bg-slate-100">
    <EditorToolbar :active-view="currentView" @select-view="selectView" @close="$emit('close')" />
    <div v-if="structuredInfo" class="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-xs text-amber-800">
      <span class="rounded-full bg-amber-100 px-2 py-0.5 font-medium">结构化</span>
      <span>母版：{{ structuredInfo.master_name || '—' }} · 版式：{{ structuredInfo.layout_name || '—' }}</span>
      <span class="ml-auto text-amber-600">占位符文本可编辑，母版/版式已锁定</span>
    </div>
    <div v-if="editor.exportState === 'failed'" class="flex items-center gap-2 border-b border-rose-200 bg-rose-50 px-4 py-1.5 text-xs text-rose-800">
      <span class="rounded-full bg-rose-100 px-2 py-0.5 font-medium">导出失败</span>
      <span>{{ editor.exportError || '结构化映射校验未通过，请检查占位符是否完整' }}</span>
    </div>
    <template v-if="currentView === 'editor'"><SlideEditor :project-id="projectId" :incremental="incremental" /><SpeakerNotesPanel v-if="incremental && hasSpeakerNotes" />
      <AnimationPanel v-if="incremental && editor.selectedElementIds.length > 0" /></template>
    <PreviewPanel v-else-if="currentView === 'preview'" :incremental="incremental" />
    <ValidationPanel v-else />
  </section>
</template>
