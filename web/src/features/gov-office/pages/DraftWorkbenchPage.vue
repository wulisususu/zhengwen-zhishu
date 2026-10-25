<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
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
import MaterialList from "../components/draft/MaterialList.vue";
import PolicyRefList from "../components/draft/PolicyRefList.vue";
import AddMaterialDialog from "../components/draft/AddMaterialDialog.vue";
import ExportDialog from "../components/draft/ExportDialog.vue";
import SubmitDialog from "../components/draft/SubmitDialog.vue";
import { DOC_TYPES, docTypeConfig, STATUS_LABELS, STATUS_TONES } from "../domain/docTypes";
import { documentGates } from "../domain/issueRules";
import { COMPACT_BELOW, useViewport } from "../composables/useViewport";
import { useIssueMarks } from "../composables/useIssueMarks";
import { useGovDocumentsStore } from "../stores/govDocuments";
import { useGovSessionStore } from "../stores/govSession";
import type { FieldKey } from "../types";

const DEFAULT_DOC_ID = "demo-d1";
const route = useRoute();
const store = useGovDocumentsStore();
const session = useGovSessionStore();
const { width } = useViewport();

const docId = computed(() => (route.params.id as string) || DEFAULT_DOC_ID);
const doc = computed(() => store.byId[docId.value]);
const actor = computed(() => session.actorAs("drafter"));
const typeConfig = computed(() => (doc.value ? docTypeConfig(doc.value.docType) : DOC_TYPES[0]));

const view = ref<"body" | "outline">("body");
const zoom = ref<"fit" | number>("fit");
const leftOpen = ref(true);
const rightOpen = ref(true);
const focusAnchor = ref("");
const dialog = ref<"" | "material" | "export" | "submit">("");
const preview = ref<InstanceType<typeof A4Preview> | null>(null);
const fieldsForm = ref<InstanceType<typeof DraftFieldsForm> | null>(null);

const { summary, marks } = useIssueMarks(doc);
const gates = computed(() => (doc.value && actor.value ? documentGates(doc.value, actor.value) : null));
const editable = computed(() => !!gates.value?.canEdit && typeConfig.value.supported);
const compact = computed(() => width.value < COMPACT_BELOW);

const lockText = computed(() => {
  if (!doc.value) return "";
  if (!typeConfig.value.supported) return `「${typeConfig.value.label}」起草模板待支持，当前仅可预览。`;
  if (doc.value.status === "pending") return "文稿审核中，编辑已锁定；审核人退回后可继续修改。";
  if (doc.value.status === "approved") return "文稿已审核通过，编辑已锁定。";
  return "";
});
const watermark = computed(() => (doc.value && doc.value.status !== "approved" ? "未审核" : ""));

onMounted(async () => {
  leftOpen.value = width.value >= 1400;
  await session.load();
  await store.load(docId.value);
  store.loadMaterialLibrary();
});
watch(docId, (id) => store.load(id));

async function locate(anchor: string) {
  focusAnchor.value = anchor;
  if (view.value !== "body") view.value = "body";
  await preview.value?.scrollToAnchor(anchor);
}

async function fillField(field: FieldKey) {
  leftOpen.value = true;
  // The materials panel may have just been mounted; wait for the form ref.
  await nextTick();
  fieldsForm.value?.focusField(field);
}

function updateField(field: FieldKey, value: string) {
  if (doc.value) store.updateFields(doc.value.id, { [field]: value });
}

async function addMaterials(ids: string[]) {
  dialog.value = "";
  if (doc.value) await store.addMaterials(doc.value.id, ids);
}

async function submit() {
  dialog.value = "";
  if (doc.value) await store.submitForReview(doc.value.id);
}

function save() {
  if (doc.value) store.saveDraft(doc.value.id, "草稿已保存。");
}

function rerun() {
  if (doc.value) store.rerunReview(doc.value.id, "已重新运行审校。");
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
          <button type="button" class="gov-btn" :disabled="!editable" @click="save"><Save :size="15" aria-hidden="true" />保存草稿</button>
          <button type="button" class="gov-btn" @click="dialog = 'export'"><Download :size="15" aria-hidden="true" />导出</button>
          <button type="button" class="gov-btn gov-btn--primary" :disabled="!gates.canSubmit || !typeConfig.supported" @click="dialog = 'submit'">
            <Send :size="15" aria-hidden="true" />提交审核
          </button>
        </template>
      </GovPageHeader>

      <div class="gov-draft__toolbar">
        <button type="button" class="gov-btn" :aria-pressed="leftOpen" @click="leftOpen = !leftOpen">
          <PanelLeftClose v-if="leftOpen" :size="16" aria-hidden="true" />
          <PanelLeftOpen v-else :size="16" aria-hidden="true" />
          {{ leftOpen ? "收起材料栏" : "材料与依据" }}
        </button>
        <label class="gov-draft__inline">
          文种
          <select class="gov-select" :value="doc.docType" aria-describedby="gov-doctype-note">
            <option v-for="t in DOC_TYPES" :key="t.id" :value="t.id" :disabled="!t.supported">{{ t.label }}{{ t.supported ? "" : "（待支持）" }}</option>
          </select>
        </label>
        <span id="gov-doctype-note" class="gov-muted">模板：{{ typeConfig.template }}</span>
        <div class="gov-seg" role="group" aria-label="视图切换">
          <button type="button" :class="{ 'is-active': view === 'outline' }" :aria-pressed="view === 'outline'" @click="view = 'outline'">提纲</button>
          <button type="button" :class="{ 'is-active': view === 'body' }" :aria-pressed="view === 'body'" @click="view = 'body'">正文</button>
        </div>
        <label v-if="view === 'body'" class="gov-draft__inline">
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

      <div v-if="lockText" class="gov-draft__lockbar gov-banner gov-banner--info">{{ lockText }}</div>
      <StoreMessages />

      <div class="gov-draft__work">
        <aside v-if="leftOpen" class="gov-draft__left" aria-label="材料与政策依据">
          <DraftFieldsForm ref="fieldsForm" :doc="doc" :editable="editable" @update="updateField" />
          <MaterialList :materials="doc.materials" :editable="editable" @add="dialog = 'material'" @remove="(id) => store.removeMaterial(doc!.id, id)" />
          <PolicyRefList :refs="doc.policyRefs" />
        </aside>

        <section class="gov-draft__center" aria-label="公文预览">
          <A4Preview v-if="view === 'body'" ref="preview" :zoom="zoom" :watermark="watermark" :corner-note="doc.origin === 'demo' ? '演示文稿 · 内容虚构' : ''">
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
            rerun-label="演示环境：未重新执行检查"
            @locate="locate"
            @fill-field="fillField"
            @collapse="rightOpen = false"
          >
            <template #footer>
              <button type="button" class="gov-btn gov-btn--sm" @click="rerun">重新审校</button>
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
      <SubmitDialog v-if="dialog === 'submit'" :blockers="summary.blockers" @close="dialog = ''" @confirm="submit" />
    </template>
    <div v-else class="gov-draft__loading">
      <StoreMessages />
      <span v-if="!store.error" class="gov-muted">正在加载文稿…</span>
    </div>
  </GovLayout>
</template>

<style scoped>
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
