<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { usePptProjectStore } from "../../stores/pptProject";
import { usePptWorkspaceStore } from "../../stores/pptWorkspace";
import { usePptGenerationStore } from "../../stores/pptGeneration";
import { usePptEditorStore } from "../../stores/pptEditor";
import api from "../../../../api";
import ObjectToolbar from "./ObjectToolbar.vue";
const props = defineProps<{ projectId: string; incremental: boolean }>();
const { slides, theme, project } = storeToRefs(usePptProjectStore()); const { status, error } = storeToRefs(usePptGenerationStore()); const workspace = usePptWorkspaceStore(); const editor = usePptEditorStore();
const oldSlide = computed(() => slides.value.find((item) => item.id === workspace.selectedSlideId) ?? slides.value[0]); const draftSlide = computed(() => editor.document?.slides.find((item) => item.slide_id === editor.selectedSlideId) ?? editor.document?.slides[0]); const editing = ref(""); const text = ref(""); const drag = ref<any>(null);
const mediaAssets = ref<any[]>([]);
const legacyFileReady = computed(() => !props.incremental && Boolean(project.value?.exportArtifact?.valid));
const legacyMessage = computed(() => status.value === "failed" ? (["LEGACY_VALIDATION_FAILED", "LEGACY_EXPORT_INVALID"].includes(error.value?.code ?? "") ? "本次 PPTX 未通过检查" : "本次 PPTX 未生成") : status.value === "running" ? "PPTX 正在一次性生成" : "当前没有在线逐页数据");
function select(id: string) { editor.selectedElementIds = [id]; } function edit(item: any) { if (item.type === "text" && !item.locked) { editing.value = item.id; text.value = item.content?.text ?? ""; } } function done() { if (editing.value) { editor.setText(editing.value, text.value); editor.scheduleSave(); } editing.value = ""; }
function add(type: "text" | "rect" | "ellipse" | "line") { if (!draftSlide.value) return; editor.snapshot(); draftSlide.value.elements.push({ id: `local:${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`, type, x: 180, y: 180, width: type === "line" ? 240 : 220, height: type === "line" ? 0 : 80, rotation: 0, z_index: draftSlide.value.elements.length + 1, locked: false, style: type === "text" ? { font_size: 28, color: "#111827" } : { fill: "#dbeafe", stroke: "#2563eb" }, content: type === "text" ? { text: "新文本" } : {} }); editor.changeSequence += 1; editor.savingState = "dirty"; editor.scheduleSave(); }
async function chooseImage(replaceId = "") {
  if (!editor.projectId) return;
  const input = document.createElement("input"); input.type = "file"; input.accept = "image/png,image/jpeg,image/webp";
  input.onchange = async () => { const file = input.files?.[0]; if (!file) return; try {
    const form = new FormData(); form.append("file", file);
    const uploaded = (await api.post("/files/upload", form)).data?.data;
    if (!uploaded?.id) throw new Error("upload");
    const media = (await api.post(`/ppt-master/projects/${encodeURIComponent(editor.projectId)}/media`, { file_id: uploaded.id, source_type: "uploaded" })).data?.data;
    if (!media?.asset_id) throw new Error("media");
    if (replaceId) editor.replaceImage(replaceId, media); else editor.addImage(media);
    editor.scheduleSave();
  } catch { editor.error = "图片上传或注册失败"; editor.savingState = "failed"; } };
  input.click();
}
async function refreshMedia() { if (!editor.projectId) return; try { mediaAssets.value = (await api.get(`/ppt-master/projects/${encodeURIComponent(editor.projectId)}/media`)).data?.data?.assets ?? []; } catch { mediaAssets.value = []; } }
async function extractDocumentImages() { const raw = window.prompt("输入已上传 DOCX、PPTX 或 PDF 的文件 ID"); const fileId = Number(raw); if (!Number.isInteger(fileId) || fileId <= 0 || !editor.projectId) return; try { await api.post(`/ppt-master/projects/${encodeURIComponent(editor.projectId)}/media/extract`, { source_file_id: fileId }); await refreshMedia(); } catch { editor.error = "文档图片提取失败"; editor.savingState = "failed"; } }
function addChart(kind: "column" | "bar" | "line" | "pie") { editor.addChart(kind); editor.scheduleSave(); }
function addTable() { editor.addTable(); editor.scheduleSave(); }
async function importNativeData(kind: "chart" | "table") { const raw = window.prompt("输入已上传 CSV、TSV 或 XLSX 的文件 ID"); const fileId = Number(raw); if (!Number.isInteger(fileId) || fileId <= 0 || !editor.projectId) return; const chartType = kind === "chart" ? (window.prompt("图表类型：column / bar / line / pie", "column") || "column") : "column"; try { const data = (await api.post(`/ppt-master/projects/${encodeURIComponent(editor.projectId)}/native-data/import`, { file_id: fileId, kind, chart_type: chartType })).data?.data; if (!data) throw new Error("native-data"); if (kind === "chart") editor.addChart(chartType as any, data); else editor.addTable(data); editor.scheduleSave(); } catch { editor.error = "数据导入失败：请检查文件、数值与授权"; editor.savingState = "failed"; } }
function editChart(item: any) { const title = window.prompt("图表标题", item.content?.title ?? ""); if (title === null) return; const type = window.prompt("类型：column / bar / line / pie", item.content?.chart_type ?? "column"); if (!type || !["column", "bar", "line", "pie"].includes(type)) return; const categories = window.prompt("分类（逗号分隔）", (item.content?.categories ?? []).join(",")); const seriesText = window.prompt("系列（格式：名称:数值,数值；名称:数值,数值）", (item.content?.series ?? []).map((s: any) => `${s.name}:${s.values.join(",")}`).join(";")); if (categories === null || seriesText === null) return; const cats = categories.split(",").map((v) => v.trim()).filter(Boolean); const series = seriesText.split(";").map((part) => { const [name, values] = part.split(":"); return { name: name?.trim(), values: (values ?? "").split(",").map((v) => Number(v.trim())) }; }).filter((s) => s.name && s.values.length); if (!cats.length || !series.length || series.some((s) => s.values.length !== cats.length || s.values.some((v) => !Number.isFinite(v))) || (type === "pie" && series.length !== 1)) return; editor.updateNative(item.id, { ...item.content, title, chart_type: type, categories: cats, series }); editor.scheduleSave(); }
function editTable(item: any) { const columns = window.prompt("列名（逗号分隔）", (item.content?.columns ?? []).join(",")); if (columns === null) return; const rows = window.prompt("行数据（每行用 ; 分隔，列用 , 分隔）", (item.content?.rows ?? []).map((r: string[]) => r.join(",")).join(";")); if (rows === null) return; const cols = columns.split(",").map((v) => v.trim()).filter(Boolean); const data = rows ? rows.split(";").map((row) => row.split(",").map((v) => v.trim())) : []; if (!cols.length || data.some((row) => row.length !== cols.length)) return; editor.updateNative(item.id, { ...item.content, columns: cols, rows: data }); editor.scheduleSave(); }
function point(event: PointerEvent) { const box = (event.currentTarget as SVGSVGElement).getBoundingClientRect(); return { x: (event.clientX - box.left) * 1280 / box.width, y: (event.clientY - box.top) * 720 / box.height }; }
function startMove(event: PointerEvent, item: any) { if (item.locked || item.bounds_locked) return; select(item.id); const p = point(event); drag.value = { item, x: p.x, y: p.y, left: item.x, top: item.y, width: item.width, height: item.height, resize: false }; (event.currentTarget as Element).setPointerCapture?.(event.pointerId); }
function startResize(event: PointerEvent, item: any, handle: string) { if (item.locked || item.bounds_locked) return; const p = point(event); drag.value = { item, x: p.x, y: p.y, left: item.x, top: item.y, width: item.width, height: item.height, resize: handle }; event.stopPropagation(); }
function move(event: PointerEvent) { if (!drag.value) return; const p = point(event); const d = drag.value; const dx = p.x - d.x; const dy = p.y - d.y; if (!d.resize) editor.moveElement(d.item.id, d.left + dx, d.top + dy); else { const h = d.resize; editor.resizeElement(d.item.id, h.includes('w') ? d.left + dx : d.left, h.includes('n') ? d.top + dy : d.top, h.includes('w') ? d.width - dx : h.includes('e') ? d.width + dx : d.width, h.includes('n') ? d.height - dy : h.includes('s') ? d.height + dy : d.height); } }
function endMove() { if (drag.value) editor.scheduleSave(); drag.value = null; }
async function downloadEditedPpt() { const result = await editor.exportPpt(); if (!result) return; const anchor = document.createElement('a'); anchor.href = result.download_url; anchor.download = ''; document.body.appendChild(anchor); anchor.click(); anchor.remove(); }
function keydown(event: KeyboardEvent) { if (event.key === 'Delete') { editor.deleteSelected(); editor.scheduleSave(); } if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); event.shiftKey ? editor.redo() : editor.undo(); editor.scheduleSave(); } if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') { event.preventDefault(); editor.redo(); editor.scheduleSave(); } }
onMounted(() => { window.addEventListener('keydown', keydown); void refreshMedia(); }); onBeforeUnmount(() => window.removeEventListener('keydown', keydown));

// === Visual polish additions (观感优化) ===
const hasSelection = computed(() => editor.selectedElementIds.length > 0);
const selectionType = computed<"image" | "other" | "">(() => {
  const id = editor.selectedElementIds[0];
  if (!id) return "";
  const el = editor.document?.slides.flatMap((slide) => slide.elements).find((item) => item.id === id);
  return el?.type === "image" ? "image" : el ? "other" : "";
});
const exportStatusText = computed(() => {
  switch (editor.exportState) {
    case "saving": return "正在保存修改";
    case "exporting": return "正在导出…";
    case "ready": return "已导出";
    case "failed": return "导出失败";
    default: return "";
  }
});
function onToolAction(action: string) {
  const sel = editor.selectedElementIds[0];
  switch (action) {
    case "add-text": add("text"); break;
    case "add-rect": add("rect"); break;
    case "add-ellipse": add("ellipse"); break;
    case "add-line": add("line"); break;
    case "add-image": chooseImage(); break;
    case "add-chart": addChart("column"); break;
    case "add-table": addTable(); break;
    case "import-chart": importNativeData("chart"); break;
    case "import-table": importNativeData("table"); break;
    case "extract-images": extractDocumentImages(); break;
    case "fit-contain": if (sel) { editor.setImageFit(sel, "contain"); editor.scheduleSave(); } break;
    case "fit-cover": if (sel) { editor.setImageFit(sel, "cover"); editor.scheduleSave(); } break;
    case "crop": if (sel) { editor.cropImage(sel); editor.scheduleSave(); } break;
    case "delete": editor.deleteSelected(); editor.scheduleSave(); break;
    case "arrange-top": if (sel) { editor.moveLayer(sel, "top"); editor.scheduleSave(); } break;
    case "arrange-up": if (sel) { editor.moveLayer(sel, "up"); editor.scheduleSave(); } break;
    case "arrange-down": if (sel) { editor.moveLayer(sel, "down"); editor.scheduleSave(); } break;
    case "arrange-bottom": if (sel) { editor.moveLayer(sel, "bottom"); editor.scheduleSave(); } break;
    case "zoom-in": workspace.setEditorZoom(workspace.editorZoom + 0.1); break;
    case "zoom-out": workspace.setEditorZoom(workspace.editorZoom - 0.1); break;
    case "zoom-reset": workspace.setEditorZoom(1); break;
    case "download-ppt": downloadEditedPpt(); break;
  }
}
</script>
<template>
  <section class="min-h-0 flex-1 overflow-auto bg-[var(--ppt-bg)] px-6 py-6">
    <template v-if="draftSlide">
      <div class="mx-auto mb-3 flex w-[min(1280px,100%)] items-center gap-2 text-xs">
        <span v-if="editor.savingState === 'failed'" class="rounded-md bg-[var(--ppt-danger-weak)] px-2 py-1 text-[var(--ppt-danger)]">
          保存失败，<button type="button" class="underline" @click="editor.save()">点击重试</button>
        </span>
        <span v-else-if="editor.savingState === 'conflict'" class="rounded-md bg-[var(--ppt-danger-weak)] px-2 py-1 text-[var(--ppt-danger)]">
          版本冲突，<button type="button" class="underline" @click="editor.reload()">重新加载</button>
        </span>
        <span v-if="exportStatusText" class="rounded-md bg-[var(--ppt-surface-2)] px-2 py-1 text-[var(--ppt-text-sub)]">{{ exportStatusText }}</span>
        <span v-if="editor.exportState === 'failed'" class="rounded-md bg-[var(--ppt-danger-weak)] px-2 py-1 text-[var(--ppt-danger)]">
          导出失败，<button type="button" class="underline" @click="downloadEditedPpt">点击重试</button>
        </span>
        <div class="ml-auto flex items-center gap-2">
          <button type="button" data-editor-download-ppt class="rounded-md border border-[var(--ppt-border)] px-2 py-1 text-[var(--ppt-text-sub)] transition-colors hover:bg-[var(--ppt-surface-2)]" :disabled="editor.exportState === 'saving' || editor.exportState === 'exporting'" @click="downloadEditedPpt">下载 PPT</button>
          <ObjectToolbar :has-selection="hasSelection" :selection-type="selectionType" @action="onToolAction" />
        </div>
      </div>
      <div v-if="mediaAssets.length" data-editor-media-library class="mx-auto mb-2 flex w-[min(1280px,100%)] gap-1 overflow-x-auto text-xs">
        <button v-for="asset in mediaAssets" :key="asset.asset_id" class="rounded border px-2 py-1" @click="editor.addImage(asset);editor.scheduleSave()">图片 {{ asset.file_id }}</button>
      </div>
      <div class="mx-auto w-[min(1280px,100%)]" :style="{ zoom: workspace.editorZoom }">
        <svg data-editor-canvas viewBox="0 0 1280 720" class="mx-auto aspect-video w-full bg-white shadow-[var(--ppt-shadow)]" @pointermove="move" @pointerup="endMove">
          <template v-for="item in draftSlide.elements" :key="item.id">
            <rect v-if="item.type === 'rect'" :x="item.x" :y="item.y" :width="item.width" :height="item.height" :fill="item.style.fill" :stroke="item.style.stroke" @pointerdown="startMove($event,item)"/>
            <ellipse v-else-if="item.type === 'ellipse'" :cx="item.x+item.width/2" :cy="item.y+item.height/2" :rx="item.width/2" :ry="item.height/2" :fill="item.style.fill" :stroke="item.style.stroke" @pointerdown="startMove($event,item)"/>
            <line v-else-if="item.type === 'line'" :x1="item.x" :y1="item.y" :x2="item.x+item.width" :y2="item.y+item.height" :stroke="item.style.stroke" stroke-width="8" @pointerdown="startMove($event,item)"/>
            <foreignObject v-else-if="editing === item.id" :x="item.x" :y="item.y" :width="item.width" :height="item.height">
              <input v-model="text" class="h-full w-full border" @blur="done" @keyup.enter="done">
            </foreignObject>
            <text v-else-if="item.type === 'text'" :x="item.x" :y="item.y+item.height" :fill="item.style.color" :font-size="item.style.font_size" @pointerdown="startMove($event,item)" @dblclick="edit(item)">{{ item.content?.text }}<title v-if="item.placeholder_type">占位符：{{ item.placeholder_type }}</title></text>
            <g v-else-if="item.type === 'chart'" @pointerdown="startMove($event,item)" @dblclick="editChart(item)">
              <rect :x="item.x" :y="item.y" :width="item.width" :height="item.height" fill="#f8fafc" stroke="#64748b"/>
              <text :x="item.x+16" :y="item.y+28" fill="#0f172a" font-size="18">{{ item.content?.title || '数据图表' }}</text>
              <line :x1="item.x+32" :y1="item.y+item.height-28" :x2="item.x+item.width-20" :y2="item.y+item.height-28" stroke="#64748b"/>
            </g>
            <g v-else-if="item.type === 'table'" @pointerdown="startMove($event,item)" @dblclick="editTable(item)">
              <rect :x="item.x" :y="item.y" :width="item.width" :height="item.height" fill="#fff" stroke="#64748b"/>
              <rect :x="item.x" :y="item.y" :width="item.width" height="30" fill="#2563eb"/>
              <text v-for="(col,index) in item.content?.columns" :key="index" :x="item.x+12+index*(item.width/Math.max(1,item.content?.columns?.length))" :y="item.y+22" fill="#fff" font-size="14">{{ col }}</text>
            </g>
            <image v-else-if="item.type === 'image'" :href="item.content?.download_url" :x="item.x" :y="item.y" :width="item.width" :height="item.height" :preserveAspectRatio="item.fit === 'contain' ? 'xMidYMid meet' : 'xMidYMid slice'" @pointerdown="startMove($event,item)"/>
            <g v-else-if="item.type === 'lockedVector'" @click="select(item.id)">
              <g v-if="item.content?.svg" v-html="item.content.svg" />
              <template v-else>
                <rect :x="item.x" :y="item.y" :width="item.width||48" :height="item.height||48" :fill="item.placeholder_type ? '#fef3c7' : '#cbd5e1'" :stroke="item.placeholder_type ? '#f59e0b' : '#64748b'" stroke-dasharray="4 3"/>
                <title v-if="item.placeholder_type">{{ item.placeholder_type }} 占位符（锁定）</title>
                <title v-else>锁定矢量元素</title>
              </template>
            </g>
            <template v-if="editor.selectedElementIds.includes(item.id) && !item.locked && !item.bounds_locked">
              <rect :x="item.x-4" :y="item.y-4" :width="item.width+8" :height="item.height+8" fill="none" stroke="#2563eb"/>
              <rect v-for="h in ['nw','n','ne','e','se','s','sw','w']" :key="h" :x="h.includes('w')?item.x-8:h.includes('e')?item.x+item.width-2:item.x+item.width/2-5" :y="h.includes('n')?item.y-8:h.includes('s')?item.y+item.height-2:item.y+item.height/2-5" width="10" height="10" fill="#2563eb" @pointerdown="startResize($event,item,h)"/>
            </template>
          </template>
          <template v-for="ph in draftSlide.elements.filter((e:any)=>e.placeholder_type)" :key="'ph-'+ph.id">
            <rect :x="ph.x-4" :y="ph.y-4" :width="ph.width+8" :height="ph.height+8" fill="none" stroke="#f59e0b" stroke-dasharray="3 3" pointer-events="none" rx="4"/>
          </template>
        </svg>
      </div>
    </template>
    <div v-else-if="!oldSlide && legacyFileReady" data-legacy-editor-ready class="mx-auto grid aspect-video w-[min(960px,100%)] place-items-center rounded-lg bg-white shadow-[var(--ppt-shadow)]"><div>PPTX 文件已经生成<br><small>Legacy 后端不提供在线逐页画布，请从对话结果卡下载并编辑文件。</small></div></div>
    <div v-else-if="!oldSlide && !incremental" data-legacy-editor-unavailable class="mx-auto grid aspect-video w-[min(960px,100%)] place-items-center rounded-lg bg-white shadow-[var(--ppt-shadow)]"><div>{{ legacyMessage }}</div></div>
    <div v-else-if="!oldSlide" data-editor-skeleton class="mx-auto aspect-video w-[min(960px,100%)] rounded-lg bg-white shadow-[var(--ppt-shadow)]"/>
    <div v-else data-editor-canvas class="mx-auto aspect-video w-[min(960px,100%)] bg-white p-[7%] shadow-[var(--ppt-shadow)]" :style="{ backgroundColor: theme?.backgroundColor ?? '#ffffff' }">
      <img v-if="oldSlide.previewUrl" :src="oldSlide.previewUrl" class="h-full w-full object-contain" alt="当前幻灯片预览">
      <h2 v-else class="mt-[12%] text-center text-4xl">{{ oldSlide.title }}</h2>
    </div>
  </section>
</template>
