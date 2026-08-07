<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { usePptProjectStore } from "../../stores/pptProject";
import { usePptGenerationStore } from "../../stores/pptGeneration";
const { project } = storeToRefs(usePptProjectStore());
const generation = usePptGenerationStore();
const brief = computed(() => project.value?.brief);
const pending = computed(() => !brief.value?.goal && generation.status === "running");
</script>
<template>
  <section class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
    <div class="flex items-center justify-between"><h2 class="text-sm font-semibold text-slate-800">需求分析</h2><span class="text-xs" :class="pending ? 'text-blue-600' : 'text-slate-400'">{{ pending ? '分析中' : brief?.goal ? '已整理' : '等待开始' }}</span></div>
    <div v-if="pending" data-brief-skeleton aria-busy="true" class="mt-4 space-y-2.5"><div class="h-3 w-11/12 animate-pulse rounded bg-slate-200" /><div class="h-3 w-4/5 animate-pulse rounded bg-slate-100" /><div class="h-3 w-2/3 animate-pulse rounded bg-slate-100" /></div>
    <div v-else-if="brief?.goal" class="mt-4 grid gap-3 text-sm"><div><span class="text-xs text-slate-400">目标</span><p class="mt-1 leading-6 text-slate-700">{{ brief.goal }}</p></div><div class="grid grid-cols-2 gap-3"><div class="rounded-xl bg-slate-50 p-3"><span class="text-xs text-slate-400">受众</span><p class="mt-1 text-slate-700">{{ brief.audience || '待确认' }}</p></div><div class="rounded-xl bg-slate-50 p-3"><span class="text-xs text-slate-400">页数</span><p class="mt-1 text-slate-700">{{ brief.slideCount || '待确认' }}</p></div></div></div>
    <div v-else-if="generation.status === 'failed'" data-generation-error class="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{{ generation.error?.message || '需求分析未完成，请重新提交。' }}</div>
    <p v-else class="mt-3 text-sm text-slate-400">提交需求后会在这里逐步整理目标、受众和页数。</p>
  </section>
</template>
