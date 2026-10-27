<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute, useRouter, onBeforeRouteLeave } from "vue-router";
import { Download, Lock, PanelLeftClose, PanelLeftOpen, PanelRightOpen, Save, Send } from "lucide-vue-next";
import GovLayout from "../components/layout/GovLayout.vue";
import GovPageHeader from "../components/layout/GovPageHeader.vue";
import StatusTag from "../components/common/StatusTag.vue";
import StoreMessages from "../components/common/StoreMessages.vue";
import A4Preview from "../components/document/A4Preview.vue";
import OfficialDocumentView from "../components/document/OfficialDocumentView.vue";
import DocumentOutline from "../components/document/DocumentOutline.vue";
import IssuePanel from "../components/review/IssuePanel.vue";
import DraftFieldsForm from "../components/draft/DraftFieldsForm.vue";
import NoticeMetadataForm from "../components/draft/NoticeMetadataForm.vue";
import MaterialList from "../components/draft/MaterialList.vue";
import PolicyRefList from "../components/draft/PolicyRefList.vue";
import PolicyLibraryPanel from "../components/policy/PolicyLibraryPanel.vue";
import AddMaterialDialog from "../components/draft/AddMaterialDialog.vue";
import ExportDialog from "../components/draft/ExportDialog.vue";
import SubmitDialog from "../components/draft/SubmitDialog.vue";
import { DOC_TYPES, docTypeConfig, STATUS_LABELS, STATUS_TONES } from "../domain/docTypes";
import { documentGates } from "../domain/issueRules";
import { COMPACT_BELOW, useViewport } from "../composables/useViewport";
import { useIssueMarks } from "../composables/useIssueMarks";
import { useGovDocumentsStore } from "../stores/govDocuments";
import { useGovSessionStore } from "../stores/govSession";
import type { FieldKey, NoticeMetadata, OfficialDocument } from "../types";
import { getGovOfficeAdapter } from "../adapters";

const DEFAULT_DOC_ID = "demo-d1";
const route = useRoute();
const router = useRouter();
const store = useGovDocumentsStore();
const session = useGovSessionStore();
const { width } = useViewport();

const docId = computed(() => (route.params.id as string) || (session.isDemo ? DEFAULT_DOC_ID : ""));
const doc = computed(() => store.byId[docId.value]);
const actor = computed(() => session.actor);
const typeConfig = computed(() => (doc.value ? docTypeConfig(doc.value.docType) : DOC_TYPES[0]));

// Real documents open in the editor; the demo has no inline editor, so it opens on the preview.
const view = ref<"edit" | "preview" | "outline">(session.isDemo ? "preview" : "edit");
const zoom = ref<"fit" | number>("fit");
const leftOpen = ref(true);
const rightOpen = ref(true);
const focusAnchor = ref("");
const dialog = ref<"" | "material" | "export" | "submit" | "policy">("");
const policyFocus = ref<number>();
const preview = ref<InstanceType<typeof A4Preview> | null>(null);
const fieldsForm = ref<InstanceType<typeof DraftFieldsForm> | null>(null);
const newTitle = ref("");
const editTitle = ref("");
const editBody = ref("");
const editDate = ref("");
const editFields = ref({ recipient: "", issuer: "", undertaker: "" });
const editMetadata = ref<NoticeMetadata>({ docNumber: "", printer: "", printDate: "", copyTo: "", note: "", titleLines: "", tables: [] });
const dirty = ref(false);
const busy = ref(false);
const generationPrompt = ref("");
const loadFailure = ref("");
async function loadDocument(id: string) {
  loadFailure.value = "";
  const loaded = await store.load(id);
  if (docId.value !== id) return;
  if (!loaded) loadFailure.value = store.error || "文稿读取失败，请刷新后重试";
  else await store.loadMaterialLibrary();
}
function acceptSavedDocument(value: OfficialDocument) {
  editTitle.value = value.title; editBody.value = value.body ?? ""; editDate.value = value.signDate;
  editFields.value = { ...value.fields }; dirty.value = false;
  editMetadata.value = { docNumber: value.docNumber.text, printer: value.banji?.printer ?? "", printDate: value.banji?.printDate ?? "", copyTo: value.banji?.copyTo?.join('\n') ?? "", note: value.note ?? "", titleLines: value.titleLines?.join('\n') ?? "", tables: value.tables ?? [] };
}
watch(doc, (value, previous) => {
  if (!value) return;
  // A refresh started on navigation can finish after the user begins typing.
  if (dirty.value && previous?.id === value.id) return;
  acceptSavedDocument(value);
}, { immediate: true });
onBeforeRouteLeave(() => !dirty.value || window.confirm("修改尚未保存，确定离开？"));

const { summary, marks } = useIssueMarks(doc);
const gates = computed(() => (doc.value && actor.value ? documentGates(doc.value, actor.value) : null));
const editable = computed(() => !!gates.value?.canEdit && typeConfig.value.supported);
const compact = computed(() => width.value < COMPACT_BELOW);

const lockText = computed(() => {
  if (!doc.value) return "";
  if (!typeConfig.value.supported) return `「${typeConfig.value.label}」起草模板待支持，当前仅可预览。`;
  if (!session.isDrafter) return "当前身份没有起草权限，仅可查看。";
  if (doc.value.status === "pending") return "文稿审核中，编辑已锁定；审核人退回后可继续修改。";
  if (doc.value.status === "approved") return "文稿已审核通过，编辑已锁定。";
  return "";
});
/** Latest review decision, so the drafter sees the outcome and the reviewer's opinion. */
const reviewResult = computed(() => {
  if (!doc.value || (doc.value.status !== "returned" && doc.value.status !== "approved")) return null;
  const record = [...doc.value.history].reverse().find((r) => r.action === "退回修改" || r.action === "审核通过");
  if (!record) return null;
  return { tone: record.action === "退回修改" ? "danger" : "success", text: `${record.action} · ${record.actor} · ${record.at}${record.note ? `：${record.note}` : ""}` };
});
const watermark = computed(() => (doc.value && doc.value.status !== "approved" ? "未审核" : ""));

onMounted(async () => {
  leftOpen.value = width.value >= 1400;
  await session.load();
  if (docId.value) await loadDocument(docId.value);
});
watch(docId, (id) => { if (id) loadDocument(id); });

async function createDraft() {
  busy.value = true;
  const created = await store.create({ title: newTitle.value.trim(), docType: "notice" });
  busy.value = false;
  if (created) await router.replace(`/gov/draft/${created.id}`);
}

/**
 * Preview and outline render the backend's doc.blocks, not the editor text, so unsaved edits are
 * saved first; if saving fails the editor stays open with the edits intact.
 */
async function showView(next: "edit" | "preview" | "outline") {
  if (next !== "edit" && dirty.value && !(await save())) return false;
  view.value = next;
  return true;
}

async function locate(anchor: string) {
  focusAnchor.value = anchor;
  if (view.value !== "preview" && !(await showView("preview"))) return;
  // The preview may have just been mounted by the view switch.
  await nextTick();
  await preview.value?.scrollToAnchor(anchor);
}

async function fillField(field: FieldKey) {
  leftOpen.value = true;
  // The materials panel may have just been mounted; wait for the form ref.
  await nextTick();
  fieldsForm.value?.focusField(field);
}

function updateField(field: FieldKey, value: string) {
  if (session.isDemo && doc.value) store.updateFields(doc.value.id, { [field]: value });
  else { editFields.value[field] = value; dirty.value = true; }
}

async function addMaterials(ids: string[]) {
  dialog.value = "";
  if (dirty.value && !(await save())) return;
  if (doc.value) await store.addMaterials(doc.value.id, ids);
}

async function submit() {
  dialog.value = "";
  if (dirty.value && !(await save())) return;
  if (doc.value) await store.submitForReview(doc.value.id);
}

async function save() {
  if (!doc.value || busy.value) return;
  busy.value = true;
  const metadata = editMetadata.value;
  const saved = await store.saveDraft(doc.value.id, "草稿已保存。", session.isDemo ? undefined : { title: editTitle.value, body: editBody.value, fields: editFields.value, signDate: editDate.value,
    docNumber: { text: metadata.docNumber }, banji: { printer: metadata.printer, printDate: metadata.printDate, copyTo: metadata.copyTo.split('\n').map(s => s.trim()).filter(Boolean) },
    note: metadata.note, titleLines: metadata.titleLines.split('\n').filter(Boolean), tables: metadata.tables });
  if (saved && docId.value === saved.id) acceptSavedDocument(saved);
  busy.value = false;
  return saved;
}

async function openExport() {
  if (dirty.value && !(await save())) return;
  dialog.value = "export";
}

async function removeMaterial(id: string) {
  if (dirty.value && !(await save())) return;
  if (doc.value) await store.removeMaterial(doc.value.id, id);
}

async function changeCitations(id: string, remove = false) {
  if (dirty.value && !(await save())) return;
  if (!doc.value || !editable.value || busy.value) return;
  const api = getGovOfficeAdapter();
  if (!api.selectCitations) return;
  busy.value = true;
  const ids = doc.value.policyRefs.map(p => p.id);
  const result = await store.mutate(() => api.selectCitations!(doc.value!.id, remove ? ids.filter(value => value !== id) : [...new Set([...ids, id])]), remove ? "政策依据已移除。" : "政策条款已保存到文稿。");
  busy.value = false;
  if (result) dialog.value = "";
}
function showPolicy(id?: number) { policyFocus.value = id; dialog.value = "policy"; }

async function generate() {
  if (!doc.value || busy.value) return;
  if (editBody.value.trim() && !window.confirm("生成成功后将替换正文，是否继续？")) return;
  if (dirty.value && !(await save())) return;
  const adapter = getGovOfficeAdapter();
  if (!adapter.generateDraft) return;
  busy.value = true;
  await store.mutate(() => adapter.generateDraft!(doc.value!.id, generationPrompt.value.trim() || `请起草一份标题为《${doc.value!.title}》的通知，仅根据已知信息写正文，未知事实明确标注待补充。`), "模型初稿已保存，请逐项人工核实。");
  busy.value = false;
}

async function rerun() {
  if (dirty.value && !(await save())) return;
  if (!doc.value || busy.value) return;
  busy.value = true;
  await store.rerunReview(doc.value.id, "已重新运行双层审校。");
  busy.value = false;
}

function exportLocate(anchor: string) {
  dialog.value = "";
  locate(anchor);
}

const zoomOptions: { value: "fit" | number; label: string }[] = [
  { value: "fit", label: "适应宽度" },
  { value: 0.75, label: "75%" },
  { value: 1, label: "100%" },
  { value: 1.25, label: "125%" },
];
</script>

<template>
  <GovLayout :auto-collapse-below="COMPACT_BELOW">
    <template v-if="doc && actor && gates && summary">
      <GovPageHeader :crumb="`公文起草 / ${typeConfig.label}`" :title="doc.title">
        <template #meta>
          <StatusTag :tone="STATUS_TONES[doc.status]" :label="STATUS_LABELS[doc.status]" />
          <Lock v-if="!editable" :size="16" class="gov-draft__lock" aria-label="编辑已锁定" />
        </template>
        <template #actions>
          <button type="button" class="gov-btn" :disabled="!editable || busy" @click="save"><Save :size="15" aria-hidden="true" />保存草稿</button>
          <button type="button" class="gov-btn" :disabled="busy" @click="openExport"><Download :size="15" aria-hidden="true" />导出</button>
          <button type="button" class="gov-btn gov-btn--primary" :disabled="!gates.canSubmit || !typeConfig.supported || busy" @click="dialog = 'submit'">
            <Send :size="15" aria-hidden="true" />提交审核
          </button>
        </template>
      </GovPageHeader>

      <div class="gov-draft__toolbar">
        <button type="button" class="gov-btn" :aria-pressed="leftOpen" @click="leftOpen = !leftOpen">
          <PanelLeftClose v-if="leftOpen" :size="16" aria-hidden="true" />
          <PanelLeftOpen v-else :size="16" aria-hidden="true" />
          {{ leftOpen ? "收起要素栏" : "要素与材料" }}
        </button>
        <label class="gov-draft__inline">
          文种
          <select class="gov-select" :value="doc.docType" disabled aria-describedby="gov-doctype-note">
            <option v-for="t in DOC_TYPES" :key="t.id" :value="t.id" :disabled="!t.supported">{{ t.label }}{{ t.supported ? "" : "（待支持）" }}</option>
          </select>
        </label>
        <span id="gov-doctype-note" class="gov-muted">模板：{{ typeConfig.template }}</span>
        <div class="gov-seg" role="group" aria-label="视图切换">
          <button v-if="!session.isDemo" type="button" :class="{ 'is-active': view === 'edit' }" :aria-pressed="view === 'edit'" @click="showView('edit')">编辑</button>
          <button type="button" :class="{ 'is-active': view === 'preview' }" :aria-pressed="view === 'preview'" :disabled="busy" @click="showView('preview')">预览</button>
          <button type="button" :class="{ 'is-active': view === 'outline' }" :aria-pressed="view === 'outline'" :disabled="busy" @click="showView('outline')">提纲</button>
        </div>
        <label v-if="view === 'preview'" class="gov-draft__inline">
          缩放
          <select v-model="zoom" class="gov-select">
            <option v-for="z in zoomOptions" :key="String(z.value)" :value="z.value">{{ z.label }}</option>
          </select>
        </label>
        <span class="gov-draft__spacer" />
        <button v-if="!rightOpen" type="button" class="gov-btn" @click="rightOpen = true">
          <PanelRightOpen :size="16" aria-hidden="true" />审校问题
          <span class="gov-tag gov-tag--danger">{{ summary.open.critical }}</span>
        </button>
      </div>

      <div v-if="reviewResult" class="gov-draft__lockbar gov-banner" :class="`gov-banner--${reviewResult.tone}`" role="status">审核结果：{{ reviewResult.text }}</div>
      <div v-if="lockText" class="gov-draft__lockbar gov-banner gov-banner--info">{{ lockText }}</div>
      <StoreMessages />

      <div class="gov-draft__work">
        <aside v-if="leftOpen" class="gov-draft__left" aria-label="起草要素与材料">
          <DraftFieldsForm ref="fieldsForm" :doc="session.isDemo ? doc : { ...doc, fields: editFields }" :editable="editable && !busy" @update="updateField">
            <fieldset v-if="!session.isDemo" :disabled="!editable || busy" class="gov-draft__meta">
              <label class="gov-label">成文日期<input v-model="editDate" class="gov-input" aria-label="成文日期" placeholder="2026年10月26日" @input="dirty = true" /></label>
              <NoticeMetadataForm v-if="doc.docType === 'notice'" v-model="editMetadata" @update:model-value="dirty = true" />
            </fieldset>
          </DraftFieldsForm>
          <MaterialList :materials="doc.materials" :editable="editable && !busy" @add="dialog = 'material'" @remove="removeMaterial" />
          <PolicyRefList :refs="doc.policyRefs" :live="!session.isDemo" :editable="editable && !busy" @add="showPolicy()" @view="showPolicy" @remove="changeCitations($event, true)" />
        </aside>

        <section class="gov-draft__center" :aria-label="view === 'edit' ? '正文编辑区' : '公文预览'">
          <fieldset v-if="view === 'edit'" :disabled="!editable || busy" class="gov-draft__editor">
            <label class="gov-label">文稿标题<input v-model="editTitle" class="gov-input" aria-label="文稿标题" maxlength="256" @input="dirty = true" /></label>
            <label class="gov-label gov-draft__body-editor">正文编辑<textarea v-model="editBody" class="gov-textarea" aria-label="正文编辑" @input="dirty = true" /></label>
            <div class="gov-draft__generate">
              <label class="gov-label">生成要求<input v-model="generationPrompt" class="gov-input" aria-label="生成要求" placeholder="可选；仅使用已知信息生成初稿" /></label>
              <button type="button" class="gov-btn" @click="generate">{{ busy ? '处理中…' : '使用模型生成初稿' }}</button>
            </div>
            <span class="gov-muted">{{ dirty ? '有修改未保存；切换到预览或提纲时先保存' : '当前内容已保存' }} · 第 {{ doc.version }} 版</span>
          </fieldset>
          <A4Preview v-else-if="view === 'preview'" ref="preview" :zoom="zoom" :watermark="watermark" :corner-note="doc.origin === 'demo' ? '演示文稿 · 内容虚构' : ''">
            <OfficialDocumentView :doc="doc" :marks="marks" :focus-anchor="focusAnchor" />
          </A4Preview>
          <div v-else class="gov-draft__outline-scroll">
            <DocumentOutline :doc="doc" :unresolved="summary.unresolved" :template="typeConfig.template" @locate="locate" />
          </div>
        </section>

        <aside v-if="rightOpen" class="gov-draft__right" :class="{ 'is-compact': compact }">
          <IssuePanel
            :doc="doc"
            :actor="actor"
            :focus-anchor="focusAnchor"
            :editable="editable"
            collapsible
            :rerun-label="session.isDemo ? '演示环境：未重新执行检查' : '保存版本由后端检查'"
            @locate="locate"
            @fill-field="fillField"
            @collapse="rightOpen = false"
          >
            <template #footer>
              <button type="button" class="gov-btn gov-btn--sm" :disabled="busy || (!session.isDemo && doc.docType !== 'notice')" @click="rerun">{{ busy ? '审校中…' : '重新审校' }}</button>
            </template>
          </IssuePanel>
        </aside>
      </div>

      <AddMaterialDialog
        v-if="dialog === 'material'"
        :library="store.materialLibrary"
        :existing-ids="doc.materials.map((m) => m.id)"
        @close="dialog = ''"
        @confirm="addMaterials"
      />
      <ExportDialog v-if="dialog === 'export'" :doc="doc" :actor="actor" @close="dialog = ''" @locate="exportLocate" />
      <SubmitDialog v-if="dialog === 'submit'" :blockers="summary.blockers" :check-status="doc.checkStatus" @close="dialog = ''" @confirm="submit" />
      <div v-if="dialog === 'policy'" class="gov-policy-overlay" @click.self="dialog = ''">
        <section class="gov-policy-dialog" role="dialog" aria-modal="true" aria-labelledby="policy-dialog-title">
          <div class="gov-policy-dialog-head"><h2 id="policy-dialog-title">选择政策依据</h2><button type="button" class="gov-btn" @click="dialog = ''">关闭政策选择</button></div>
          <PolicyLibraryPanel :document-id="doc.id" :initial-policy-id="policyFocus" :selectable="editable && !busy" @select="changeCitations($event)" />
        </section>
      </div>
    </template>
    <div v-else-if="session.loaded && !docId" class="gov-draft__loading">
      <h1>新建通知</h1>
      <label class="gov-label">文稿标题<input v-model="newTitle" class="gov-input" aria-label="新建文稿标题" maxlength="256" placeholder="请输入文稿标题" /></label>
      <p class="gov-muted">先创建并保存文稿，再编辑正文、上传材料和送交人工审核。目前支持通知内部草稿。</p>
      <button type="button" class="gov-btn gov-btn--primary" :disabled="!newTitle.trim() || busy" @click="createDraft">创建文稿</button>
      <StoreMessages />
    </div>
    <div v-else class="gov-draft__loading">
      <div v-if="loadFailure" class="gov-banner gov-banner--danger" role="alert">{{ loadFailure }}</div>
      <template v-else><StoreMessages /><span v-if="!store.error" class="gov-muted">正在加载文稿…</span></template>
    </div>
  </GovLayout>
</template>

<style scoped>
.gov-policy-overlay { position: fixed; inset: 0; z-index: 100; background: #10243f66; display: grid; place-items: center; padding: 20px; }
.gov-policy-dialog { width: min(1100px, 100%); height: min(860px, 90vh); display: flex; flex-direction: column; overflow: hidden; background: var(--gov-surface); border-radius: 12px; }
.gov-policy-dialog-head { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--gov-border); }
/* Editor fills the centre column; the body textarea takes all height left by the title and generation row. */
.gov-draft__editor { border: 0; margin: 0; min-width: 0; padding: 16px 24px; display: flex; flex-direction: column; gap: 12px; overflow-y: auto; background: var(--gov-surface); }
.gov-draft__body-editor { flex: 1 1 auto; min-height: 0; }
.gov-draft__body-editor textarea { flex: 1 1 auto; min-height: 240px; }
.gov-draft__generate { flex: 0 0 auto; display: flex; align-items: end; gap: 12px; }
.gov-draft__generate .gov-label { flex: 1 1 auto; }
.gov-draft__meta { border: 0; margin: 0; padding: 0; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.gov-draft__lock { color: var(--gov-text-3); flex: 0 0 auto; }
.gov-draft__toolbar {
  flex: 0 0 auto; display: flex; align-items: center; flex-wrap: wrap; gap: 10px 12px;
  padding: 8px 24px; background: var(--gov-surface); border-bottom: 1px solid var(--gov-border);
}
.gov-draft__inline { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--gov-text-2); white-space: nowrap; }
.gov-draft__spacer { flex: 1 1 auto; }
.gov-seg { display: inline-flex; border: 1px solid var(--gov-border-strong); border-radius: var(--gov-r-md); overflow: hidden; }
.gov-seg button { height: 32px; padding: 0 14px; border: 0; background: var(--gov-surface); color: var(--gov-text-2); font-size: 13px; cursor: pointer; }
.gov-seg button.is-active { background: var(--gov-primary); color: #fff; }
.gov-draft__lockbar { margin: 8px 24px 0; flex: 0 0 auto; }
.gov-draft__work { flex: 1 1 auto; min-height: 0; display: flex; margin-top: 8px; border-top: 1px solid var(--gov-border); }
.gov-draft__left {
  flex: 0 0 272px; width: 272px; overflow-y: auto; padding: 16px; background: var(--gov-surface);
  border-right: 1px solid var(--gov-border); display: flex; flex-direction: column; gap: 20px;
}
.gov-draft__center { flex: 1 1 0; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.gov-draft__center > * { flex: 1 1 auto; min-height: 0; }
.gov-draft__outline-scroll { overflow-y: auto; background: var(--gov-desk); padding: 0 24px; }
.gov-draft__right { flex: 0 0 336px; width: 336px; min-height: 0; border-left: 1px solid var(--gov-border); }
.gov-draft__right.is-compact { flex-basis: 320px; width: 320px; }
.gov-draft__loading { padding: 24px; }
</style>
