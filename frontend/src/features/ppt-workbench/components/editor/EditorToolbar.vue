<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { ChevronLeft, Download, MoreHorizontal, ZoomIn, ZoomOut, Maximize } from "lucide-vue-next";
import type { PptActiveView } from "../../stores/pptWorkspace";
import { usePptWorkspaceStore } from "../../stores/pptWorkspace";
import { usePptProjectStore } from "../../stores/pptProject";
import { usePptEditorStore } from "../../stores/pptEditor";

defineProps<{ activeView: PptActiveView }>();
defineEmits<{ "select-view": [view: PptActiveView]; close: [] }>();

const project = usePptProjectStore();
const editor = usePptEditorStore();
const workspace = usePptWorkspaceStore();
const { savingState, exportState } = storeToRefs(editor);
const { editorZoom } = storeToRefs(workspace);

const tabs: Array<{ view: PptActiveView; label: string; aria: string }> = [
  { view: "editor", label: "编辑", aria: "编辑幻灯片" },
  { view: "preview", label: "预览", aria: "预览演示文稿" },
  { view: "validation", label: "检查", aria: "检查演示文稿" },
];

const fileName = computed(() => project.project?.title?.trim() || "未命名 PPT");

const saveLabel = computed(() => {
  if (exportState.value === "exporting") return "导出中";
  if (exportState.value === "saving") return "正在保存";
  if (savingState.value === "saving") return "保存中";
  if (savingState.value === "saved") return "已保存";
  if (savingState.value === "failed") return "保存失败";
  if (savingState.value === "conflict") return "版本冲突";
  if (savingState.value === "dirty") return "未保存";
  return "已保存";
});
const saveTone = computed<"ok" | "busy" | "danger" | "muted">(() => {
  if (savingState.value === "failed" || savingState.value === "conflict") return "danger";
  if (exportState.value === "exporting" || savingState.value === "saving") return "busy";
  if (savingState.value === "idle" || savingState.value === "saved") return "ok";
  return "muted";
});

const canDownload = computed(() => exportState.value !== "saving" && exportState.value !== "exporting");

async function downloadPpt() {
  await editor.exportPpt();
}
function zoomIn() { workspace.setEditorZoom(editorZoom.value + 0.1); }
function zoomOut() { workspace.setEditorZoom(editorZoom.value - 0.1); }
function zoomReset() { workspace.setEditorZoom(1); }
</script>

<template>
  <header
    data-editor-topbar
    class="flex h-14 shrink-0 items-center gap-3 border-b border-[var(--ppt-border)] bg-[var(--ppt-surface)] px-3"
  >
    <button type="button" class="ppt-tool-btn" aria-label="关闭编辑工作台" @click="$emit('close')">
      <ChevronLeft class="ppt-tool-ico" />
      <span>退出</span>
    </button>

    <div class="flex min-w-0 items-center gap-2">
      <span class="max-w-[200px] truncate text-sm font-medium text-[var(--ppt-text)]" :title="fileName">{{ fileName }}</span>
      <span class="ppt-status" :class="`ppt-status-${saveTone}`" role="status" aria-live="polite" :data-save-state="savingState" :data-export-state="exportState">
        <span class="ppt-status-dot" :class="`ppt-status-${saveTone}`" />
        <span class="text-xs">{{ saveLabel }}</span>
      </span>
    </div>

    <nav class="mx-auto flex items-center gap-1" aria-label="编辑器视图">
      <button
        v-for="tab in tabs"
        :key="tab.view"
        type="button"
        class="ppt-tool-btn"
        :class="activeView === tab.view ? 'is-active' : ''"
        :aria-label="tab.aria"
        :aria-pressed="activeView === tab.view"
        @click="$emit('select-view', tab.view)"
      >{{ tab.label }}</button>
    </nav>

    <button type="button" class="ppt-tool-btn" :disabled="!canDownload" aria-label="下载 PPT" @click="downloadPpt">
      <Download class="ppt-tool-ico" />
      <span>下载</span>
    </button>

    <details class="ppt-more relative">
      <summary class="ppt-tool-btn" aria-label="更多操作">
        <MoreHorizontal class="ppt-tool-ico" />
        <span>更多</span>
      </summary>
      <div class="ppt-pop absolute right-0 z-40 mt-1 w-44 p-1">
        <button type="button" class="ppt-menu-item" @click="zoomIn">
          <ZoomIn class="ppt-menu-ico" /> 放大
        </button>
        <button type="button" class="ppt-menu-item" @click="zoomOut">
          <ZoomOut class="ppt-menu-ico" /> 缩小
        </button>
        <button type="button" class="ppt-menu-item" @click="zoomReset">
          <Maximize class="ppt-menu-ico" /> 重置缩放
        </button>
        <div class="ppt-tool-sep my-1" />
        <button type="button" class="ppt-menu-item" @click="$emit('close')">退出编辑</button>
      </div>
    </details>
  </header>
</template>
