<script setup lang="ts">
import { ref } from "vue";
import { usePptNativeEnhanceStore } from "../../stores/pptNativeEnhance";
import api from "../../../../api.js";

type FieldConfig = { enabled: boolean; text: string; fontSizePt: number; color: string; position: "bottom_left" | "bottom_center" | "bottom_right"; applicationScope: "all" | "selected"; slideIds: string };
const emit = defineEmits<{ close: [] }>();
const store = usePptNativeEnhanceStore();
const sourceFileId = ref("");
const sourceInput = ref<HTMLInputElement | null>(null);
const transitionType = ref("keep");
const durationMs = ref(500);
const advanceOnClick = ref(true);
const autoAdvanceMs = ref<number | null>(null);
const applicationScope = ref("all");
const selectedSlideIds = ref("");
const removeExternalRelationships = ref(false);
const pageNumber = ref<FieldConfig>({ enabled: false, text: "{page}", fontSizePt: 9, color: "64748B", position: "bottom_right", applicationScope: "all", slideIds: "" });
const footer = ref<FieldConfig>({ enabled: false, text: "", fontSizePt: 9, color: "64748B", position: "bottom_center", applicationScope: "all", slideIds: "" });
const date = ref<FieldConfig>({ enabled: false, text: new Date().toLocaleDateString("zh-CN"), fontSizePt: 9, color: "64748B", position: "bottom_left", applicationScope: "all", slideIds: "" });
const documentProperties = ref({ title: "", subject: "", author: "", keywords: "", comments: "", company: "" });

function slideIds(value: string) { return value.split(",").map((item) => Number(item.trim())).filter((item) => Number.isInteger(item) && item > 0); }
function fieldPayload(field: FieldConfig) { return { enabled: field.enabled, text: field.text || undefined, font_size_pt: field.fontSizePt, color: field.color, position: field.position, application_scope: field.applicationScope, slide_ids: slideIds(field.slideIds) }; }
function propertiesPayload() { return Object.fromEntries(Object.entries(documentProperties.value).filter(([, value]) => value.trim())); }

async function uploadSource(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0]; input.value = "";
  if (!file || !file.name.toLowerCase().endsWith(".pptx")) { store.error = "仅支持 .pptx 文件"; return; }
  try { const body = new FormData(); body.append("file", file); const response = await api.post("/files/upload", body); const id = Number(response.data?.data?.id); if (!id) throw new Error("PPT 上传失败"); sourceFileId.value = String(id); await store.analyze(id); }
  catch (cause) { store.error = cause instanceof Error ? cause.message : "PPT 上传失败"; }
}
async function analyze() { const id = Number(sourceFileId.value); if (Number.isInteger(id) && id > 0) await store.analyze(id); }
async function submit() {
  await store.createTask({
    transition_type: transitionType.value, duration_ms: durationMs.value, advance_on_click: advanceOnClick.value,
    auto_advance_ms: autoAdvanceMs.value || undefined, application_scope: applicationScope.value, slide_ids: slideIds(selectedSlideIds.value),
    page_number: fieldPayload(pageNumber.value), footer: fieldPayload(footer.value), date: fieldPayload(date.value),
    document_properties: propertiesPayload(), remove_external_relationships: removeExternalRelationships.value,
  });
}
</script>

<template>
  <section data-native-enhance-workspace class="mx-auto flex min-h-full w-full max-w-3xl flex-col gap-5 px-6 py-10">
    <header class="flex items-center justify-between"><div><h1 class="text-xl font-semibold">增强已有 PPT</h1><p class="mt-1 text-sm text-slate-500">仅进行可控的 OOXML 增量修改，不重绘原有页面。</p></div><button type="button" class="text-sm text-slate-500" @click="emit('close')">返回</button></header>
    <input ref="sourceInput" type="file" accept=".pptx" class="hidden" @change="uploadSource" />
    <div class="flex flex-wrap gap-3"><button type="button" class="w-fit rounded-lg bg-slate-900 px-4 py-2 text-sm text-white" @click="sourceInput?.click()">上传 PPTX</button><label class="grid gap-2 text-sm font-medium">已有文件 ID<input v-model="sourceFileId" inputmode="numeric" class="rounded-lg border border-slate-200 px-3 py-2" placeholder="输入当前账号的 PPT 文件 ID" /></label><button type="button" class="w-fit self-end rounded-lg border px-4 py-2 text-sm" :disabled="store.state === 'analyzing'" @click="analyze">{{ store.state === 'analyzing' ? '正在分析…' : '分析文件' }}</button></div>
    <div v-if="store.analysis" class="space-y-4 rounded-xl border border-slate-200 bg-white p-4 text-sm">
      <p>共 {{ store.analysis.slide_count }} 页 · 已锁定源文件 SHA · 可安全生成独立输出文件</p>
      <div class="grid gap-3 sm:grid-cols-2"><label class="grid gap-1">应用范围<select v-model="applicationScope" class="rounded-lg border border-slate-200 px-3 py-2"><option value="all">全部页面</option><option value="missing_only">仅无转场页面</option><option value="selected">指定页面</option></select></label><label v-if="applicationScope === 'selected'" class="grid gap-1">页码（逗号分隔）<input v-model="selectedSlideIds" class="rounded-lg border border-slate-200 px-3 py-2" placeholder="例如 1,3,5" /></label><label class="grid gap-1">转场<select v-model="transitionType" class="rounded-lg border border-slate-200 px-3 py-2"><option value="keep">保留原转场</option><option value="none">无转场</option><option value="fade">淡入淡出</option><option value="push">推进</option><option value="wipe">擦除</option><option value="split">分割</option><option value="cover">覆盖</option></select></label><label class="grid gap-1">转场时长（毫秒）<input v-model.number="durationMs" type="number" min="0" max="5000" class="rounded-lg border border-slate-200 px-3 py-2" /></label><label class="flex items-center gap-2"><input v-model="advanceOnClick" type="checkbox" />鼠标单击时换页</label><label class="grid gap-1">自动换页（毫秒，留空关闭）<input v-model.number="autoAdvanceMs" type="number" min="1" max="3600000" class="rounded-lg border border-slate-200 px-3 py-2" /></label></div>
      <details><summary class="cursor-pointer font-medium">页码、页脚与日期</summary><div class="mt-3 space-y-3"><div v-for="field in [{ key: 'page', label: '页码', model: pageNumber }, { key: 'footer', label: '页脚', model: footer }, { key: 'date', label: '日期', model: date }]" :key="field.key" class="rounded-lg border p-3"><label class="flex gap-2"><input v-model="field.model.enabled" type="checkbox" />启用{{ field.label }}</label><div v-if="field.model.enabled" class="mt-2 grid gap-2 sm:grid-cols-2"><label class="grid gap-1">文本<input v-model="field.model.text" class="rounded border px-2 py-1" :placeholder="field.key === 'page' ? '支持 {page}' : ''" /></label><label class="grid gap-1">字体大小<input v-model.number="field.model.fontSizePt" type="number" min="6" max="48" class="rounded border px-2 py-1" /></label><label class="grid gap-1">颜色（HEX）<input v-model="field.model.color" maxlength="6" class="rounded border px-2 py-1" /></label><label class="grid gap-1">位置<select v-model="field.model.position" class="rounded border px-2 py-1"><option value="bottom_left">底部左侧</option><option value="bottom_center">底部居中</option><option value="bottom_right">底部右侧</option></select></label><label class="grid gap-1">范围<select v-model="field.model.applicationScope" class="rounded border px-2 py-1"><option value="all">全部页面</option><option value="selected">指定页面</option></select></label><label v-if="field.model.applicationScope === 'selected'" class="grid gap-1">页码<input v-model="field.model.slideIds" class="rounded border px-2 py-1" placeholder="1,3,5" /></label></div></div></div></details>
      <details><summary class="cursor-pointer font-medium">文档属性</summary><div class="mt-3 grid gap-2 sm:grid-cols-2"><label v-for="label in { title: '标题', subject: '主题', author: '作者', keywords: '关键词', comments: '备注', company: '公司' }" :key="label" class="grid gap-1">{{ label }}<input v-model="documentProperties[(Object.keys({ title: '标题', subject: '主题', author: '作者', keywords: '关键词', comments: '备注', company: '公司' }) as Array<keyof typeof documentProperties>)[Object.values({ title: '标题', subject: '主题', author: '作者', keywords: '关键词', comments: '备注', company: '公司' }).indexOf(label)]]" class="rounded border px-2 py-1" /></label></div></details>
      <label class="flex gap-2"><input v-model="removeExternalRelationships" type="checkbox" />移除所有外部关系（默认保留）</label>
      <button type="button" class="rounded-lg bg-indigo-600 px-4 py-2 text-white" :disabled="store.state === 'submitting'" @click="submit">{{ store.state === 'submitting' ? '正在生成…' : '创建增强文件' }}</button>
    </div>
    <a v-if="store.task?.output_file_id" :href="`/api/v1/files/${store.task.output_file_id}/download`" class="text-sm font-medium text-indigo-700">下载增强后的 PPTX</a><p v-if="store.error" role="alert" class="text-sm text-rose-700">{{ store.error }}</p>
  </section>
</template>
