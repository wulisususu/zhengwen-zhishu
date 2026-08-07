<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { usePptProjectStore } from "../../stores/pptProject";
import { usePptWorkspaceStore } from "../../stores/pptWorkspace";
withDefaults(defineProps<{ incremental?: boolean }>(), { incremental: true });
const { slides, theme, project } = storeToRefs(usePptProjectStore());
const workspace = usePptWorkspaceStore();
const slide = computed(() => slides.value.find((item) => item.id === workspace.selectedSlideId) ?? slides.value[0]);
</script>
<template>
  <section data-preview-panel class="min-h-0 flex-1 overflow-auto bg-slate-950 p-8">
    <div v-if="!slide && !incremental && project?.exportArtifact" data-legacy-preview-ready class="mx-auto grid aspect-video w-[min(1000px,100%)] place-items-center rounded-lg border border-slate-700 bg-slate-900 p-12 text-center"><div><div class="mx-auto grid h-14 w-14 place-items-center rounded-full bg-emerald-500/15 text-2xl text-emerald-400">✓</div><h2 class="mt-5 text-xl font-semibold text-white">PPTX 文件已生成</h2><p class="mt-2 max-w-lg text-sm leading-6 text-slate-400">当前 Legacy 模式暂不提供在线逐页预览，请从左侧结果卡下载 PPTX 查看完整内容。</p></div></div>
    <div v-else-if="!slide" class="mx-auto aspect-video w-[min(1000px,100%)] animate-pulse rounded-lg bg-slate-800 p-12"><div class="h-5 w-1/2 rounded bg-slate-700" /><p class="mt-8 text-sm text-slate-500">{{ incremental ? '首张页面生成后将在这里显示。' : '当前 Legacy 模式等待最终 PPTX 文件。' }}</p></div>
    <div v-else-if="slide.status === 'error'" data-preview-slide-error class="mx-auto grid aspect-video w-[min(1000px,100%)] place-items-center rounded-lg border border-rose-500/30 bg-slate-900 p-12 text-center"><div><div class="mx-auto grid h-14 w-14 place-items-center rounded-full bg-rose-500/15 text-2xl text-rose-300">!</div><h2 class="mt-5 text-xl font-semibold text-white">{{ slide.title }}</h2><p class="mt-2 max-w-lg text-sm leading-6 text-slate-400">该页面生成失败，当前仍可继续查看其他已完成页面。</p></div></div>
    <div v-else class="mx-auto aspect-video w-[min(1000px,100%)] rounded-lg p-[8%] shadow-2xl" :style="{ backgroundColor: theme?.backgroundColor ?? '#fff', fontFamily: theme?.fontFamily ?? 'inherit' }">
      <img
        v-if="slide.previewUrl"
        :src="slide.previewUrl"
        :alt="`${slide.title} 预览`"
        data-preview-image
        class="h-full w-full rounded-lg bg-white object-contain"
      >
      <template v-else>
        <span class="text-xs text-slate-400">演示预览 · 第 {{ slide.index }} 页</span><h2 class="mt-[14%] text-center text-4xl font-semibold text-slate-900">{{ slide.title }}</h2>
      </template>
    </div>
  </section>
</template>


