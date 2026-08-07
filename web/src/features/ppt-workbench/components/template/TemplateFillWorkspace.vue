<script setup lang="ts">
import { computed, ref } from "vue";
import api from "../../../../api.js";
import PptSourceAttachments from "../chat/PptSourceAttachments.vue";
import { usePptSourcesStore } from "../../stores/pptSources";
import { usePptTemplateFillStore } from "../../stores/pptTemplateFill";

type Slot = Record<string, any>;
const emit = defineEmits<{ close: [] }>();
const store = usePptTemplateFillStore();
const sources = usePptSourcesStore();
const templateInput = ref<HTMLInputElement | null>(null);
const imageInput = ref<HTMLInputElement | null>(null);
const selected = ref<number[]>([]);
const canApply = computed(() => store.plan?.status === "confirmed" && store.state !== "applying");
const imageSources = computed(() => sources.items.filter((item) => item.kind === "file" && typeof item.fileId === "number" && /\.(png|jpe?g)$/i.test(item.filename)));

async function uploadTemplate(event: Event) {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0]; target.value = "";
  if (!file || !file.name.toLowerCase().endsWith(".pptx")) { store.error = "仅支持 .pptx 模板"; return; }
  try {
    const body = new FormData(); body.append("file", file);
    const response = await api.post("/files/upload", body);
    const id = Number(response.data?.data?.id);
    if (!id) throw new Error("模板上传失败");
    const template = await store.register(id, file.name.replace(/\.pptx$/i, ""));
    if (template) { await store.analyze(String(template.template_id)); selected.value = store.slides.map((slide) => Number(slide.slide_index)); }
  } catch (cause) { store.state = "failed"; store.error = cause instanceof Error ? cause.message : "模板上传失败"; }
}

async function uploadImage(event: Event) {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0]; target.value = "";
  if (!file || !/\.(png|jpe?g)$/i.test(file.name)) { store.error = "图片仅支持 PNG、JPG 或 JPEG"; return; }
  try {
    const body = new FormData(); body.append("file", file);
    const response = await api.post("/files/upload", body);
    const fileId = Number(response.data?.data?.id);
    if (!fileId) throw new Error("图片上传失败");
    sources.upsert({ kind: "file", fileId, filename: file.name, fileType: file.name.split(".").pop() || "image", size: file.size, status: "done", progress: 100 });
  } catch (cause) { store.error = cause instanceof Error ? cause.message : "图片上传失败"; }
}

function toggle(index: number) { selected.value = selected.value.includes(index) ? selected.value.filter((value) => value !== index) : [...selected.value, index]; }
function normalizeOrders() {
  if (!store.plan) return;
  store.plan.plan.selected_slides.forEach((slide: any, index: number) => { slide.output_order = index + 1; });
}
function move(index: number, direction: number) {
  const current = selected.value.indexOf(index); const target = current + direction;
  if (current < 0 || target < 0 || target >= selected.value.length) return;
  [selected.value[current], selected.value[target]] = [selected.value[target], selected.value[current]];
  const slides = store.plan?.plan.selected_slides as any[] | undefined;
  if (slides) {
    const from = slides.findIndex((slide) => Number(slide.template_slide_index) === index);
    const to = slides.findIndex((slide) => Number(slide.template_slide_index) === selected.value[current]);
    if (from >= 0 && to >= 0) { [slides[from], slides[to]] = [slides[to], slides[from]]; normalizeOrders(); }
  }
}
async function createPlan() { await store.createPlan(selected.value, sources.attachmentFileIds); }
function setAction(slot: Slot, event: Event) { slot.action = (event.target as HTMLSelectElement).value; }
function editText(slot: Slot, event: Event) { slot.action = "replace"; slot.value = (event.target as HTMLInputElement).value; }
function setImageSource(slot: Slot, event: Event) { const id = Number((event.target as HTMLSelectElement).value); slot.source_refs = id ? [{ file_id: id }] : []; if (id) slot.action = "replace"; }
function tableCsv(slot: Slot) {
  const rows = Array.isArray(slot.value) ? slot.value : [];
  return rows.map((row: any) => (Array.isArray(row?.cells) ? row.cells : [row]).sort((a: any, b: any) => Number(a.col || 0) - Number(b.col || 0)).map((cell: any) => String(cell?.text ?? "")).join(",")).join("\n");
}
function editTable(slot: Slot, event: Event) {
  const text = (event.target as HTMLTextAreaElement).value;
  slot.value = text.split(/\r?\n/).map((line, row) => line.split(",").map((cell, col) => ({ row, col, text: cell.trim() })));
  slot.action = "replace";
}
function chartCsv(slot: Slot) {
  const chart = slot.value || {}; const series = Array.isArray(chart.series) ? chart.series : [];
  const header = ["分类", ...series.map((item: any) => item.name || "系列")];
  const categories = Array.isArray(chart.categories) ? chart.categories : [];
  return [header, ...categories.map((category: string, row: number) => [category, ...series.map((item: any) => item.values?.[row] ?? "")])].map((row) => row.join(",")).join("\n");
}
function editChart(slot: Slot, event: Event) {
  const rows = (event.target as HTMLTextAreaElement).value.split(/\r?\n/).filter(Boolean).map((line) => line.split(",").map((value) => value.trim()));
  if (rows.length < 2 || rows[0].length < 2) { store.error = "图表数据需要表头和至少一行分类数据"; return; }
  const categories = rows.slice(1).map((row) => row[0]);
  const series = rows[0].slice(1).map((name, column) => ({ name, values: rows.slice(1).map((row) => Number(row[column + 1])) }));
  if (series.some((item) => item.values.some((value) => !Number.isFinite(value)))) { store.error = "图表数值必须是有限数字"; return; }
  slot.value = { categories, series }; slot.action = "replace";
}
function slotLabel(slot: Slot) { return ({ text: "文字", image: "图片", table: "表格", chart: "图表" } as Record<string, string>)[slot.slot_type] || "内容"; }
</script>

<template>
  <section data-template-fill-workspace class="h-full overflow-y-auto bg-slate-50 p-6">
    <div class="mx-auto max-w-6xl">
      <header class="mb-6 flex items-center justify-between">
        <div><p class="text-xs font-medium text-indigo-600">原生 PPTX 模板填充</p><h1 class="text-2xl font-semibold">使用我的 PPT 模板</h1><p class="mt-1 text-sm text-slate-500">直接保留母版、版式、主题、图片、原生表格和图表。</p></div>
        <button class="rounded border px-3 py-2 text-sm" @click="$emit('close')">返回</button>
      </header>
      <div v-if="!store.template" class="rounded-2xl border border-dashed bg-white p-10 text-center"><input ref="templateInput" type="file" accept=".pptx" class="hidden" @change="uploadTemplate"><p>上传一个 .pptx 模板后开始分析。</p><button class="mt-4 rounded bg-indigo-600 px-4 py-2 text-white" @click="templateInput?.click()">上传 PPTX 模板</button></div>
      <div v-else>
        <p v-if="store.state === 'analyzing'" class="rounded bg-blue-50 p-3 text-sm text-blue-700">正在分析模板并生成受控缩略图…</p>
        <p v-if="store.state === 'saving'" class="rounded bg-blue-50 p-3 text-sm text-blue-700">正在保存填充计划…</p>
        <p v-if="store.state === 'confirming'" class="rounded bg-blue-50 p-3 text-sm text-blue-700">正在确认填充计划…</p>
        <p v-if="store.state === 'applying'" class="rounded bg-blue-50 p-3 text-sm text-blue-700">正在生成原生 PPTX…</p>
        <p v-if="store.error" role="alert" class="rounded bg-rose-50 p-3 text-sm text-rose-700">{{ store.state === 'conflict' ? '计划版本冲突，请重新创建计划。' : store.error }} <button class="underline" @click="store.analyze(String(store.template?.template_id))">重新分析</button></p>
        <div class="mt-4 grid gap-4 md:grid-cols-3"><article v-for="slide in store.slides" :key="slide.slide_index" class="rounded-xl border bg-white p-3"><img v-if="slide.download_url" :src="slide.download_url" :alt="`模板第 ${slide.slide_index} 页预览`" class="aspect-video w-full rounded bg-slate-100 object-cover"><label class="mt-2 block font-medium"><input type="checkbox" :checked="selected.includes(Number(slide.slide_index))" @change="toggle(Number(slide.slide_index))"> 使用第 {{ slide.slide_index }} 页</label><p class="mt-1 text-xs text-slate-500">{{ slide.placeholders?.length || 0 }} 个占位符 · {{ slide.images?.length || 0 }} 张图片 · {{ slide.tables?.length || 0 }} 个表格 · {{ slide.charts?.length || 0 }} 个图表</p></article></div>
        <section class="mt-6 rounded-xl border bg-white p-4"><h2 class="font-semibold">内容与填充计划</h2><PptSourceAttachments class="mt-3"/><input ref="imageInput" type="file" accept=".png,.jpg,.jpeg" class="hidden" @change="uploadImage"><button class="mt-3 rounded border px-3 py-2 text-sm" @click="imageInput?.click()">上传替换图片</button><div class="mt-3 flex gap-2"><button class="rounded bg-slate-900 px-3 py-2 text-sm text-white" :disabled="!selected.length || store.state === 'saving'" @click="createPlan">创建计划</button><span class="text-xs text-slate-500">输出顺序：{{ selected.join(' → ') || '未选择' }}</span></div>
          <div v-if="store.plan" class="mt-4 space-y-3"><article v-for="slide in store.plan.plan.selected_slides" :key="slide.template_slide_index" class="rounded border p-3"><div class="flex justify-between"><strong>模板第 {{ slide.template_slide_index }} 页</strong><span><button :disabled="store.plan.status === 'confirmed'" @click="move(slide.template_slide_index, -1)">↑</button> <button :disabled="store.plan.status === 'confirmed'" @click="move(slide.template_slide_index, 1)">↓</button></span></div>
            <div v-for="slot in slide.slot_values" :key="`${slot.slot_type}-${slot.shape_id}`" class="mt-3 rounded bg-slate-50 p-3"><div class="flex items-center gap-2"><label class="text-sm font-medium">{{ slotLabel(slot) }}</label><select class="rounded border px-2 py-1 text-sm" :disabled="store.plan.status === 'confirmed'" :value="slot.action" @change="setAction(slot, $event)"><option value="keep">保留</option><option value="replace">替换</option><option value="clear">清空</option></select></div>
              <input v-if="slot.slot_type === 'text'" class="mt-2 w-full rounded border px-2 py-1" :disabled="store.plan.status === 'confirmed' || slot.action === 'keep'" :value="slot.value" @input="editText(slot, $event)">
              <select v-else-if="slot.slot_type === 'image'" class="mt-2 w-full rounded border px-2 py-1" :disabled="store.plan.status === 'confirmed' || slot.action === 'keep'" :value="slot.source_refs?.[0]?.file_id || ''" @change="setImageSource(slot, $event)"><option value="">选择已上传图片</option><option v-for="image in imageSources" :key="image.fileId" :value="image.fileId">{{ image.filename }}</option></select>
              <textarea v-else-if="slot.slot_type === 'table'" class="mt-2 min-h-20 w-full rounded border px-2 py-1 font-mono text-xs" :disabled="store.plan.status === 'confirmed' || slot.action === 'keep'" :value="tableCsv(slot)" @input="editTable(slot, $event)"/><p v-if="slot.slot_type === 'table'" class="mt-1 text-xs text-slate-500">每行一条记录，单元格以逗号分隔；格式会沿用模板。</p>
              <textarea v-else-if="slot.slot_type === 'chart'" class="mt-2 min-h-20 w-full rounded border px-2 py-1 font-mono text-xs" :disabled="store.plan.status === 'confirmed' || slot.action === 'keep'" :value="chartCsv(slot)" @input="editChart(slot, $event)"/><p v-if="slot.slot_type === 'chart'" class="mt-1 text-xs text-slate-500">首列是分类，后续列为系列数值；图表样式会沿用模板。</p>
            </div></article>
            <div class="flex gap-2"><button :disabled="store.plan.status !== 'draft' || store.state === 'saving'" class="rounded border px-3 py-2 text-sm" @click="store.savePlan()">保存计划</button><button :disabled="store.plan.status !== 'draft'" class="rounded bg-indigo-600 px-3 py-2 text-sm text-white" @click="store.confirm()">确认计划</button><button :disabled="!canApply" class="rounded bg-emerald-600 px-3 py-2 text-sm text-white disabled:opacity-40" @click="store.apply()">生成原生 PPTX</button></div>
          </div>
        </section>
        <a v-if="store.task?.output_file_id" class="mt-5 inline-block rounded bg-blue-600 px-4 py-2 text-white" :href="`/api/v1/files/${store.task.output_file_id}/download`">下载生成结果</a>
      </div>
    </div>
  </section>
</template>
