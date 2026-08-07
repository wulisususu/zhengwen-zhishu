<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { usePptProjectStore } from "../../stores/pptProject";
const { validation, slides } = storeToRefs(usePptProjectStore());
const warnings = computed(() => validation.value?.issues.filter((issue) => issue.severity === "warning") ?? []);
const blocking = computed(() => validation.value?.issues.filter((issue) => issue.blocking) ?? []);
const errors = computed(() => validation.value?.issues.filter((issue) => issue.severity === "error" && !issue.blocking) ?? []);
const infos = computed(() => validation.value?.issues.filter((issue) => issue.severity === "info") ?? []);
const passedChecks = computed(() => {
  if (!validation.value) return [];
  const checks = [{ id: "validation-finished", label: "版式与内容检查已完成" }];
  if (slides.value.length > 0) checks.push({ id: "slides-present", label: `${slides.value.length} 页幻灯片内容已生成` });
  if (slides.value.length > 0 && slides.value.every((slide) => slide.status === "ready")) checks.push({ id: "slides-ready", label: "所有幻灯片均已完成生成" });
  if (errors.value.length === 0 && blocking.value.length === 0) checks.push({ id: "no-errors", label: "未发现阻塞性错误" });
  return checks;
});
</script>
<template>
  <section class="min-h-0 flex-1 overflow-auto bg-slate-50 p-6">
    <div class="mx-auto max-w-4xl"><h2 class="text-xl font-semibold text-slate-900">质量检查</h2><p class="mt-1 text-sm text-slate-500">版式、内容完整性与可读性检查结果</p>
      <div v-if="!validation" class="mt-6 rounded-2xl border border-slate-200 bg-white p-6" aria-busy="true"><div class="h-4 w-1/3 animate-pulse rounded bg-slate-200" /><p class="mt-4 text-sm text-slate-400">检查结果生成后会在这里按严重程度展示。</p></div>
      <div v-else class="mt-6 grid gap-4">
        <article data-validation-group class="rounded-2xl border p-5" :class="blocking.length || errors.length ? 'border-rose-200 bg-rose-50' : warnings.length ? 'border-amber-200 bg-amber-50' : 'border-emerald-200 bg-emerald-50'"><div class="text-sm font-semibold text-slate-800">整体评分 {{ validation.score }}</div><p class="mt-1 text-sm text-slate-700">{{ blocking.length ? '检查发现阻断项，当前结果不可作为有效导出。' : errors.length || warnings.length ? '已完成检查，请处理下列事项。' : '未发现阻塞性问题，可以继续预览或导出。' }}</p></article>
        <article v-if="passedChecks.length" data-validation-group data-validation-passed class="rounded-2xl border border-slate-200 bg-white p-5"><h3 class="font-semibold text-slate-900">通过 {{ passedChecks.length }}</h3><ul class="mt-3 grid gap-2 text-sm text-slate-600 sm:grid-cols-2"><li v-for="item in passedChecks" :key="item.id" class="flex items-center gap-2"><span class="inline-block h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />{{ item.label }}</li></ul></article>
        <article v-if="blocking.length" data-validation-group data-validation-blocking class="rounded-2xl border border-rose-300 bg-rose-100 p-5"><h3 class="font-semibold text-rose-900">阻断项 {{ blocking.length }}</h3><ul class="mt-3 space-y-2 text-sm text-rose-800"><li v-for="item in blocking" :key="item.id">{{ item.message }}</li></ul></article>
        <article v-if="errors.length" data-validation-group data-validation-errors class="rounded-2xl border border-rose-200 bg-rose-50 p-5"><h3 class="font-semibold text-rose-800">错误 {{ errors.length }}</h3><ul class="mt-3 space-y-2 text-sm text-rose-700"><li v-for="item in errors" :key="item.id">{{ item.message }}</li></ul></article>
        <article v-if="warnings.length" data-validation-group data-validation-warnings class="rounded-2xl border border-amber-200 bg-amber-50 p-5"><h3 class="font-semibold text-amber-800">警告 {{ warnings.length }}</h3><ul class="mt-3 space-y-2 text-sm text-amber-700"><li v-for="item in warnings" :key="item.id">{{ item.message }}</li></ul></article>
        <article v-if="infos.length" data-validation-group class="rounded-2xl border border-blue-200 bg-blue-50 p-5"><h3 class="font-semibold text-blue-800">建议 {{ infos.length }}</h3><ul class="mt-3 space-y-2 text-sm text-blue-700"><li v-for="item in infos" :key="item.id">{{ item.message }}</li></ul></article>
      </div>
    </div>
  </section>
</template>
