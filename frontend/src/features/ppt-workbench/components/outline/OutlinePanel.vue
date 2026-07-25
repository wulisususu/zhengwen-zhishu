<script setup lang="ts">
import { storeToRefs } from "pinia";
import { usePptProjectStore } from "../../stores/pptProject";
import { usePptGenerationStore } from "../../stores/pptGeneration";
const { outline } = storeToRefs(usePptProjectStore());
const generation = usePptGenerationStore();
</script>
<template>
  <section class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
    <div class="flex items-center justify-between"><h2 class="text-sm font-semibold text-slate-800">演示大纲</h2><span class="text-xs text-slate-400">{{ outline.length ? `${outline.length} 项` : generation.workflowStage === 'outline' ? '生成中' : '等待' }}</span></div>
    <TransitionGroup v-if="outline.length" name="outline-item" tag="ol" class="mt-3 space-y-2">
      <li v-for="(item, index) in outline" :key="item.id" data-outline-item class="rounded-xl bg-slate-50 px-3 py-2.5"><div class="flex gap-3"><span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white text-xs font-medium text-blue-600">{{ index + 1 }}</span><div><strong class="text-sm font-medium text-slate-700">{{ item.title }}</strong><p class="mt-1 text-xs leading-5 text-slate-500">{{ item.description }}</p></div></div></li>
    </TransitionGroup>
    <div v-else class="mt-3 space-y-2" aria-busy="true"><div v-for="index in 3" :key="index" class="h-10 animate-pulse rounded-xl bg-slate-100" /></div>
  </section>
</template>
