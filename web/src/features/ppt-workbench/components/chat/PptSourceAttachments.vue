<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import { Cloud, FileText, Plus, RotateCw, Upload, X } from "lucide-vue-next";
import api from "../../../../api.js";
import KnowledgeFilePicker from "../../../../components/KnowledgeFilePicker.vue";
import { type PptSourceAttachment, usePptSourcesStore } from "../../stores/pptSources";

const props = withDefaults(defineProps<{ showCards?: boolean; showTrigger?: boolean }>(), { showCards: true, showTrigger: true });
const sources = usePptSourcesStore();
const fileInput = ref<HTMLInputElement | null>(null);
const menuOpen = ref(false);
const pickerOpen = ref(false);
const timers = new Map<number, number>();
const selectedDocIds = computed(() => sources.knowledgeDocIds);

function formatSize(size: number) {
  if (!size) return "";
  return size < 1024 * 1024 ? `${Math.max(1, Math.round(size / 1024))}KB` : `${(size / 1024 / 1024).toFixed(1)}MB`;
}
function label(item: PptSourceAttachment) {
  if (item.kind === "knowledge") return "知识库";
  if (item.status === "done") return "已解析";
  if (item.status === "error") return item.error || "解析失败";
  return item.progress ? `${item.status} ${item.progress}%` : "等待解析";
}
function chooseUpload() { menuOpen.value = false; fileInput.value?.click(); }
async function upload(event: Event) {
  const files = Array.from((event.target as HTMLInputElement).files || []);
  (event.target as HTMLInputElement).value = "";
  for (const file of files) {
    const body = new FormData(); body.append("file", file);
    try {
      const { data } = await api.post("/files/upload", body);
      if (data.code !== 0 || !data.data?.id) continue;
      const fileId = Number(data.data.id);
      sources.upsert({ kind: "file", fileId, filename: data.data.filename || file.name, fileType: data.data.type || file.type || "", size: data.data.size || file.size, status: "queued", progress: 0 });
      const parse = data.data.parse_task || (await api.post(`/files/${fileId}/parse`, {})).data?.data?.task;
      if (parse) applyTask(fileId, parse);
    } catch {
      sources.upsert({ kind: "file", fileId: -Date.now(), filename: file.name, fileType: file.type, size: file.size, status: "error", progress: 100, error: "上传失败" });
    }
  }
}
function applyTask(fileId: number, task: Record<string, unknown>) {
  const status = String(task.status || "queued") as PptSourceAttachment["status"];
  const current = sources.items.find((item) => item.kind === "file" && item.fileId === fileId);
  if (!current) return;
  sources.upsert({ ...current, status, progress: Number(task.progress || 0), error: task.error ? String(task.error) : undefined, parseTaskId: String(task.task_id || ""), parsedFileId: Number((task.parsed_file as Record<string, unknown> | undefined)?.id || 0) || undefined });
  if (!["done", "error"].includes(status) && task.task_id) poll(fileId, String(task.task_id));
  else stopPoll(fileId);
}
function poll(fileId: number, taskId: string) {
  if (timers.has(fileId)) return;
  const tick = async () => {
    try { const { data } = await api.get(`/files/${fileId}/parse-tasks/${taskId}`); if (data.code === 0) applyTask(fileId, data.data); } catch { /* the card retains its last observable status */ }
  };
  void tick(); timers.set(fileId, window.setInterval(tick, 1800));
}
function stopPoll(fileId: number) { const timer = timers.get(fileId); if (timer) window.clearInterval(timer); timers.delete(fileId); }
async function retry(item: PptSourceAttachment) {
  if (!item.fileId || item.fileId < 0) return;
  const { data } = await api.post(`/files/${item.fileId}/parse`, { force: true });
  if (data.code === 0 && data.data?.task) applyTask(item.fileId, data.data.task);
}
function onKnowledgeConfirm(docs: Array<Record<string, unknown>>) {
  for (const doc of docs) {
    const docId = Number(doc.doc_id); if (!docId) continue;
    sources.upsert({ kind: "knowledge", docId, filename: String(doc.filename || "知识库文件"), fileType: String(doc.file_type || ""), size: Number(doc.file_size || 0), status: "done", progress: 100 });
  }
  pickerOpen.value = false;
}
onBeforeUnmount(() => { timers.forEach((timer) => window.clearInterval(timer)); timers.clear(); });
</script>

<template>
  <div class="ppt-sources">
    <input ref="fileInput" class="hidden" type="file" multiple @change="upload" />
    <div v-if="props.showCards && sources.items.length" class="mb-3 flex flex-wrap gap-2">
      <div v-for="item in sources.items" :key="`${item.kind}-${item.fileId ?? item.docId}`" class="flex max-w-full items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600">
        <Cloud v-if="item.kind === 'knowledge'" class="size-3.5 text-indigo-500" /><FileText v-else class="size-3.5 text-blue-500" />
        <span class="max-w-40 truncate font-medium text-slate-700">{{ item.filename }}</span><span>{{ item.fileType || formatSize(item.size) }}</span><span :class="item.status === 'error' ? 'text-rose-600' : 'text-slate-400'">{{ label(item) }}</span>
        <button v-if="item.status === 'error' && item.fileId && item.fileId > 0" type="button" class="text-blue-600" @click="retry(item)"><RotateCw class="size-3.5" /></button>
        <button type="button" class="text-slate-400 hover:text-slate-700" @click="sources.remove(item.kind, item.fileId ?? item.docId!)"><X class="size-3.5" /></button>
      </div>
    </div>
    <div v-if="props.showTrigger" class="relative inline-flex">
      <button type="button" aria-label="添加 PPT 来源" class="inline-flex size-7 items-center justify-center rounded-full border border-slate-200 text-slate-600 hover:border-blue-300 hover:text-blue-600" @click="menuOpen = !menuOpen"><Plus class="size-4" /></button>
      <div v-if="menuOpen" class="absolute bottom-9 left-0 z-20 w-44 rounded-xl border border-slate-200 bg-white p-1 shadow-lg">
        <button type="button" class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs hover:bg-slate-50" @click="chooseUpload"><Upload class="size-4" />上传文件或图片</button>
        <button type="button" class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs hover:bg-slate-50" @click="menuOpen = false; pickerOpen = true"><Cloud class="size-4" />选择知识库文件</button>
      </div>
    </div>
    <KnowledgeFilePicker :visible="pickerOpen" :selected-doc-ids="selectedDocIds" @close="pickerOpen = false" @confirm="onKnowledgeConfirm" />
  </div>
</template>
