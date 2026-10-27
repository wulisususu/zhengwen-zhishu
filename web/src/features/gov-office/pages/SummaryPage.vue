<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import GovLayout from "../components/layout/GovLayout.vue";
import GovPageHeader from "../components/layout/GovPageHeader.vue";
import { getGovOfficeAdapter, GovOfficeError } from "../adapters";
import { useGovSessionStore } from "../stores/govSession";
import type { Material, SummaryMode, SummaryResult, SummarySource } from "../types";

const MODES: { id: SummaryMode; label: string; hint: string }[] = [
  { id: "material", label: "单材料提炼", hint: "摘要、关键数据、重要结论、待确认事项" },
  { id: "meeting", label: "会议纪要提炼", hint: "会议决议、工作任务、责任部门、时间要求" },
];
const ACCEPT = ".txt,.md,.docx,.pdf";

const session = useGovSessionStore();
const adapter = getGovOfficeAdapter();
const library = ref<Material[]>([]);
const materialId = ref("");
const mode = ref<SummaryMode>("material");
const result = ref<SummaryResult | null>(null);
const selected = ref("");
const running = ref(false);
const uploading = ref(false);
const error = ref("");

const summarizable = computed(() => library.value.filter((m) => /\.(txt|md|docx|pdf)$/i.test(m.name)));
const selectedSource = computed<SummarySource | null>(() => (result.value && result.value.sources[selected.value]) || null);
const isDemo = computed(() => result.value?.origin === "demo" || session.isDemo);

function message(e: unknown) {
  return e instanceof GovOfficeError || e instanceof Error ? e.message : "操作失败，请重试";
}

async function loadLibrary() {
  try {
    library.value = await adapter.listMaterialLibrary();
    if (!materialId.value && summarizable.value.length) materialId.value = summarizable.value[0].id;
  } catch (e) {
    error.value = message(e);
  }
}

onMounted(async () => {
  await session.load();
  await loadLibrary();
});

async function upload(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file || !adapter.uploadMaterial) return;
  if (file.size > 20 * 1024 * 1024) { error.value = "材料不能超过20MiB"; return; }
  uploading.value = true;
  error.value = "";
  try {
    const material = await adapter.uploadMaterial(file);
    await loadLibrary();
    materialId.value = material.id;
  } catch (e) {
    error.value = message(e);
  } finally {
    uploading.value = false;
  }
}

async function run() {
  if (!materialId.value || running.value || !adapter.summarizeMaterial) return;
  running.value = true;
  error.value = "";
  result.value = null;
  selected.value = "";
  try {
    result.value = await adapter.summarizeMaterial(materialId.value, mode.value);
  } catch (e) {
    error.value = message(e);
  } finally {
    running.value = false;
  }
}

function location(s: SummarySource) {
  return `${s.page ? `第${s.page}页 ` : ""}第${s.paragraph}段`;
}
</script>

<template>
  <GovLayout>
    <GovPageHeader title="提炼总结" subtitle="单份材料提炼与会议纪要提炼；每条结论都标注原文出处" />
    <div class="gov-sum">
      <section class="gov-card gov-sum__controls" aria-label="提炼设置">
        <h2 class="gov-section-title">1. 选择材料</h2>
        <label v-if="adapter.uploadMaterial && !session.isDemo" class="gov-label">
          上传材料（TXT、Markdown、DOCX、PDF，最多20MiB）
          <input type="file" aria-label="上传材料" :accept="ACCEPT" :disabled="uploading || running" @change="upload" />
        </label>
        <span v-else class="gov-tag gov-tag--warning" style="align-self: flex-start">演示材料库 · 不读取本机文件</span>
        <div class="gov-sum__materials" role="radiogroup" aria-label="材料">
          <label v-for="m in summarizable" :key="m.id" class="gov-sum__pick" :class="{ 'is-on': m.id === materialId }">
            <input v-model="materialId" type="radio" name="summary-material" :value="m.id" :disabled="running" />
            <span class="gov-sum__pick-text">
              <span class="gov-sum__pick-name">{{ m.name }}</span>
              <span class="gov-muted">{{ m.meta }}</span>
            </span>
          </label>
          <div v-if="!summarizable.length" class="gov-empty">还没有可提炼的材料，请先上传。</div>
        </div>

        <h2 class="gov-section-title">2. 提炼方式</h2>
        <div class="gov-sum__modes" role="radiogroup" aria-label="提炼方式">
          <label v-for="m in MODES" :key="m.id" class="gov-sum__pick" :class="{ 'is-on': m.id === mode }">
            <input v-model="mode" type="radio" name="summary-mode" :value="m.id" :disabled="running" />
            <span class="gov-sum__pick-text">
              <span class="gov-sum__pick-name">{{ m.label }}</span>
              <span class="gov-muted">{{ m.hint }}</span>
            </span>
          </label>
        </div>
        <p class="gov-muted gov-sum__scope">本期一次提炼一份材料；多材料综合尚未支持。扫描件不做文字识别。</p>
        <button type="button" class="gov-btn gov-btn--primary gov-sum__run" :disabled="!materialId || running || uploading" @click="run">
          {{ running ? "正在提炼…" : "开始提炼" }}
        </button>
      </section>

      <section class="gov-sum__results" aria-label="提炼结果" aria-live="polite">
        <div v-if="error" class="gov-banner gov-banner--danger" role="alert">{{ error }}</div>
        <div v-if="running" class="gov-card gov-empty">正在读取材料并调用模型，较长材料可能需要一两分钟…</div>
        <div v-else-if="!result && !error" class="gov-card gov-empty">选择材料和提炼方式后，点击「开始提炼」。每条结论都会附上所依据的原文段落。</div>
        <template v-if="result">
          <div class="gov-banner" :class="isDemo ? 'gov-banner--warning' : 'gov-banner--info'">
            <template v-if="isDemo">演示数据：材料与提炼结果均为虚构，未调用模型。</template>
            <template v-else>由云端模型生成，后端已逐条校验出处；内容仍需人工核实，不作为正式结论。</template>
            材料《{{ result.materials[0]?.fileName }}》，共切分 {{ result.materials[0]?.segments }} 段。
          </div>

          <section v-for="section in result.sections" :key="section.key" class="gov-card gov-sum__section" :aria-label="section.label">
            <h2 class="gov-section-title">{{ section.label }} <span class="gov-muted">{{ section.items.length }} 条</span></h2>
            <div v-if="!section.items.length" class="gov-muted">原文中没有提炼出此类内容。</div>
            <table v-else-if="section.key === 'tasks'" class="gov-sum__table">
              <thead><tr><th scope="col">工作任务</th><th scope="col">责任部门</th><th scope="col">时间要求</th><th scope="col">出处</th></tr></thead>
              <tbody>
                <tr v-for="(item, i) in section.items" :key="i">
                  <td>
                    {{ item.text }}
                    <span v-for="note in item.notes" :key="note" class="gov-sum__note">{{ note }}</span>
                  </td>
                  <td><span v-if="item.owner">{{ item.owner }}</span><span v-else class="gov-muted">原文未写明</span></td>
                  <td><span v-if="item.deadline">{{ item.deadline }}</span><span v-else class="gov-muted">原文未写明</span></td>
                  <td>
                    <span class="gov-sum__chips">
                      <button v-for="id in item.sources" :key="id" type="button" class="gov-sum__chip" :aria-pressed="selected === id" @click="selected = id">{{ id }}</button>
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
            <ul v-else class="gov-sum__items">
              <li v-for="(item, i) in section.items" :key="i">
                <span>{{ item.text }}</span>
                <span class="gov-sum__chips">
                  <button v-for="id in item.sources" :key="id" type="button" class="gov-sum__chip" :aria-pressed="selected === id" @click="selected = id">{{ id }}</button>
                </span>
              </li>
            </ul>
          </section>

          <details v-if="result.dropped.length" class="gov-card gov-sum__dropped">
            <summary>有 {{ result.dropped.length }} 条模型输出未通过出处校验，已剔除</summary>
            <ul>
              <li v-for="(d, i) in result.dropped" :key="i"><span class="gov-muted">{{ d.section }}</span> {{ d.text }} —— {{ d.reason }}</li>
            </ul>
          </details>
        </template>
      </section>

      <aside class="gov-card gov-sum__source" aria-label="原文出处">
        <h2 class="gov-section-title">原文出处</h2>
        <template v-if="selectedSource">
          <span class="gov-tag gov-tag--info" style="align-self: flex-start">{{ selectedSource.id }} · {{ location(selectedSource) }}</span>
          <span class="gov-muted">{{ selectedSource.fileName }}</span>
          <blockquote class="gov-sum__quote">{{ selectedSource.text }}</blockquote>
        </template>
        <p v-else class="gov-muted">点击结论后的编号（如 S3），在这里查看对应的原文段落。</p>
      </aside>
    </div>
  </GovLayout>
</template>

<style scoped>
.gov-sum { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 24px; display: grid; grid-template-columns: 300px minmax(0, 1fr) 320px; gap: 20px; align-items: start; }
.gov-sum__controls, .gov-sum__source { padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; position: sticky; top: 0; }
.gov-sum__controls { max-height: calc(100vh - 124px); }
.gov-sum__materials, .gov-sum__modes { display: flex; flex-direction: column; gap: 8px; }
.gov-sum__materials { flex: 1 1 auto; min-height: 120px; overflow-y: auto; }
.gov-sum__modes, .gov-sum__run, .gov-sum__scope { flex: 0 0 auto; }
.gov-sum__pick { display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; border: 1px solid var(--gov-border); border-radius: var(--gov-r-md); cursor: pointer; }
.gov-sum__pick.is-on { border-color: var(--gov-primary); background: var(--gov-primary-50); }
.gov-sum__pick input { margin: 3px 0 0; }
.gov-sum__pick-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.gov-sum__pick-name { font-size: 13px; font-weight: 500; color: var(--gov-text-1); overflow-wrap: anywhere; }
.gov-sum__scope { margin: 0; font-size: 12px; }
.gov-sum__run { align-self: stretch; }
.gov-sum__results { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.gov-sum__section { padding: 16px 20px; display: flex; flex-direction: column; gap: 10px; }
.gov-sum__items { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 8px; font-size: 14px; line-height: 22px; }
.gov-sum__chips { display: inline-flex; flex-wrap: wrap; gap: 4px; margin-left: 6px; vertical-align: middle; }
.gov-sum__chip { height: 22px; padding: 0 8px; border: 1px solid var(--gov-primary-100); border-radius: var(--gov-r-sm); background: var(--gov-primary-50); color: var(--gov-primary); font-size: 12px; cursor: pointer; }
.gov-sum__chip[aria-pressed="true"] { background: var(--gov-primary); border-color: var(--gov-primary); color: #fff; }
.gov-sum__table { width: 100%; border-collapse: collapse; font-size: 13px; }
.gov-sum__table th { text-align: left; font-weight: 500; color: var(--gov-text-3); background: var(--gov-surface-2); padding: 8px 10px; border-bottom: 1px solid var(--gov-border); }
.gov-sum__table td { padding: 10px; border-bottom: 1px solid var(--gov-border); vertical-align: top; line-height: 20px; }
.gov-sum__note { display: block; margin-top: 4px; font-size: 12px; color: var(--gov-warn); }
.gov-sum__dropped { padding: 12px 20px; font-size: 13px; color: var(--gov-text-2); }
.gov-sum__dropped summary { cursor: pointer; color: var(--gov-warn); }
.gov-sum__dropped ul { margin: 8px 0 0; padding-left: 20px; display: flex; flex-direction: column; gap: 4px; }
.gov-sum__quote { margin: 0; padding: 12px 14px; border-left: 3px solid var(--gov-primary); background: var(--gov-surface-2); font-family: var(--gov-font-doc-body); font-size: 15px; line-height: 26px; white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 1365px) {
  .gov-sum { grid-template-columns: 280px minmax(0, 1fr); }
  .gov-sum__source { grid-column: 2; position: static; }
}
</style>
