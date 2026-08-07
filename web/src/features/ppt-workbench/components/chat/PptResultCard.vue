<script setup lang="ts">
import { computed } from "vue";
import type { ValidationIssue } from "../../types/presentation";

const props = withDefaults(defineProps<{
  title: string;
  completed: boolean;
  failed?: boolean;
  readySlides: number;
  pageCount?: number;
  incrementalSlides?: boolean;
  temporaryTitle?: boolean;
  downloadAvailable: boolean;
  warnings: string[];
  validationIssues?: ValidationIssue[];
  downloadMessage?: string;
}>(), {
  failed: false,
  incrementalSlides: true,
  temporaryTitle: false,
  validationIssues: () => [],
});
defineEmits<{ open: []; download: [] }>();

const noPageData = computed(() => !props.incrementalSlides && props.readySlides === 0);
const blocking = computed(() => props.validationIssues.filter((issue) => issue.blocking));
const errors = computed(() => props.validationIssues.filter((issue) => issue.severity === "error" && !issue.blocking));
const warningMessages = computed(() => Array.from(new Set([
  ...props.warnings,
  ...props.validationIssues.filter((issue) => issue.severity === "warning").map((issue) => issue.message),
])));
const resultLabel = computed(() => props.failed
  ? "生成结果未通过检查"
  : props.completed ? "演示文稿已完成" : "演示文稿可继续编辑");
const warningLabel = computed(() => props.completed && !props.failed ? "生成完成但有警告" : "警告");
</script>

<template>
  <article class="rounded-2xl border border-blue-100 bg-gradient-to-br from-white to-blue-50 p-4 shadow-sm">
    <div class="flex items-start justify-between gap-4">
      <div>
        <span class="text-xs font-medium" :class="failed ? 'text-rose-600' : 'text-blue-600'">{{ resultLabel }}</span>
        <h3 class="mt-1 text-base font-semibold text-slate-900">{{ title }}</h3>
        <span v-if="temporaryTitle" class="mt-1 inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">前端临时标题</span>
        <p v-if="noPageData && completed && downloadAvailable" class="mt-2 text-xs leading-5 text-slate-600">PPTX 已生成，当前 Legacy 模式暂不提供在线逐页预览</p>
        <p v-else-if="noPageData" class="mt-2 text-xs leading-5 text-slate-600">当前 Legacy 模式仅提供最终文件，不提供在线逐页数据。</p>
        <p v-else class="mt-1 text-xs text-slate-500">{{ pageCount ?? readySlides }}页内容已生成，打开后恢复上次编辑位置。</p>
        <p v-if="blocking.length" data-result-blocking class="mt-2 text-xs font-medium text-rose-800">阻断项：{{ blocking.map((item) => item.message).join("；") }}</p>
        <p v-if="errors.length" data-result-errors class="mt-2 text-xs font-medium text-rose-700">错误：{{ errors.map((item) => item.message).join("；") }}</p>
        <p v-if="warningMessages.length" data-result-warnings class="mt-2 text-xs font-medium text-amber-700">{{ warningLabel }}：{{ warningMessages.join("；") }}</p>
        <p v-if="downloadMessage" class="mt-2 text-xs text-slate-600">{{ downloadMessage }}</p>
      </div>
      <div class="flex shrink-0 flex-col gap-2">
        <button v-if="downloadAvailable" type="button" aria-label="下载 PPTX" class="rounded-xl bg-blue-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-blue-700" @click="$emit('download')">下载 PPTX</button>
        <button
          v-if="noPageData"
          type="button"
          aria-label="等待逐页数据"
          disabled
          class="cursor-not-allowed rounded-xl border border-slate-200 bg-slate-100 px-3.5 py-2 text-sm font-medium text-slate-400"
        >等待逐页数据</button>
        <button v-else type="button" aria-label="打开 PPT 编辑器" class="rounded-xl border border-blue-200 bg-white px-3.5 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50" @click="$emit('open')">打开编辑器</button>
      </div>
    </div>
  </article>
</template>
