<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { PanelLeftClose, PanelLeftOpen, PanelRightOpen } from "lucide-vue-next";
import GovLayout from "../components/layout/GovLayout.vue";
import GovPageHeader from "../components/layout/GovPageHeader.vue";
import StatusTag from "../components/common/StatusTag.vue";
import StoreMessages from "../components/common/StoreMessages.vue";
import A4Preview from "../components/document/A4Preview.vue";
import OfficialDocumentView from "../components/document/OfficialDocumentView.vue";
import DocumentFilterBar from "../components/review/DocumentFilterBar.vue";
import DocumentTable from "../components/review/DocumentTable.vue";
import IssuePanel from "../components/review/IssuePanel.vue";
import ReviewTimeline from "../components/review/ReviewTimeline.vue";
import BaseDialog from "../components/common/BaseDialog.vue";
import { docTypeConfig, STATUS_LABELS, STATUS_TONES } from "../domain/docTypes";
import { documentGates } from "../domain/issueRules";
import { COMPACT_BELOW, useViewport } from "../composables/useViewport";
import { useDocumentFilter } from "../composables/useDocumentFilter";
import { useIssueMarks } from "../composables/useIssueMarks";
import { useGovDocumentsStore } from "../stores/govDocuments";
import { useGovSessionStore } from "../stores/govSession";

const store = useGovDocumentsStore();
const session = useGovSessionStore();
const { width } = useViewport();
const compact = computed(() => width.value < COMPACT_BELOW);

const docs = computed(() => store.list);
const { filter, filtered, counts, reset } = useDocumentFilter(docs);
const selectedId = ref("");
const doc = computed(() => store.byId[selectedId.value]);
const actor = computed(() => session.actor);
const { marks } = useIssueMarks(doc);
const focusAnchor = ref("");
const listOpen = ref(true);
const issuesOpen = ref(true);
const preview = ref<InstanceType<typeof A4Preview> | null>(null);
const showRecords = ref(false);
const reviewing = ref(false);
async function rerun() {
  if (!doc.value || reviewing.value) return;
  reviewing.value = true;
  await store.rerunReview(doc.value.id, "双层审校已完成，请逐项查看。");
  reviewing.value = false;
}

const typeConfig = computed(() => (doc.value ? docTypeConfig(doc.value.docType) : null));
const editable = computed(() => !!doc.value && !!actor.value && documentGates(doc.value, actor.value).canEdit && !!typeConfig.value?.supported);

onMounted(async () => {
  await session.load();
  if (!store.order.length) await store.loadList();
  if (!selectedId.value && store.order.length) selectedId.value = store.order[0];
});
watch(filtered, (list) => {
  if (list.length && !list.some((d) => d.id === selectedId.value)) selectedId.value = list[0].id;
});

function select(id: string) {
  selectedId.value = id;
  focusAnchor.value = "";
}

async function locate(anchor: string) {
  focusAnchor.value = anchor;
  await preview.value?.scrollToAnchor(anchor);
}
</script>

<template>
  <GovLayout :auto-collapse-below="COMPACT_BELOW">
    <GovPageHeader title="文稿审校" :subtitle="session.isDemo ? '规则检查与 AI 语义审查结果、问题定位与修改；审批在审核中心进行' : '通知双层规则审校、问题定位与修改；审批在审核中心进行'">
      <template #actions>
        <RouterLink to="/gov/review-center" class="gov-btn">前往审核中心</RouterLink>
      </template>
    </GovPageHeader>
    <DocumentFilterBar
      v-model="filter"
      :counts="counts"
      :statuses="['all', 'draft', 'pending', 'returned', 'approved']"
      :result-count="filtered.length"
    />
    <StoreMessages />

    <div class="gov-proof">
      <aside v-if="listOpen" class="gov-proof__list" :class="{ 'is-compact': compact }">
        <div class="gov-proof__list-head">
          <span class="gov-subtitle">文稿（{{ filtered.length }}）</span>
          <button type="button" class="gov-btn gov-btn--text gov-btn--icon" aria-label="收起文稿列表" @click="listOpen = false">
            <PanelLeftClose :size="18" aria-hidden="true" />
          </button>
        </div>
        <DocumentTable variant="compact" :docs="filtered" :selected-id="selectedId" @select="select" @reset="reset" />
      </aside>

      <section class="gov-proof__center" aria-label="文稿预览">
        <div v-if="doc && typeConfig" class="gov-proof__bar">
          <button v-if="!listOpen" type="button" class="gov-btn gov-btn--sm" @click="listOpen = true">
            <PanelLeftOpen :size="14" aria-hidden="true" />文稿列表
          </button>
          <span class="gov-proof__title">{{ doc.title }}</span>
          <StatusTag :tone="STATUS_TONES[doc.status]" :label="STATUS_LABELS[doc.status]" />
          <StatusTag v-if="!typeConfig.supported" tone="neutral" :label="`${typeConfig.label}版式待支持 · 通用预览`" />
          <button type="button" class="gov-btn gov-btn--sm" @click="showRecords = true">审核记录（{{ doc.history.length }}）</button>
          <RouterLink v-if="typeConfig.supported && session.isDrafter" :to="`/gov/draft/${doc.id}`" class="gov-btn gov-btn--sm gov-btn--outline">在起草页修改</RouterLink>
          <button v-if="!issuesOpen" type="button" class="gov-btn gov-btn--sm" @click="issuesOpen = true">
            <PanelRightOpen :size="14" aria-hidden="true" />审校问题
          </button>
        </div>
        <A4Preview v-if="doc" ref="preview" zoom="fit" :watermark="doc.status !== 'approved' ? '未审核' : ''" :corner-note="doc.origin === 'demo' ? '演示文稿 · 内容虚构' : ''">
          <OfficialDocumentView :doc="doc" :marks="marks" :focus-anchor="focusAnchor" />
        </A4Preview>
        <div v-else class="gov-empty" style="margin: 24px">请选择左侧文稿</div>
      </section>

      <aside v-if="doc && actor && issuesOpen" class="gov-proof__issues" :class="{ 'is-compact': compact }">
        <IssuePanel
          :doc="doc"
          :actor="actor"
          :focus-anchor="focusAnchor"
          :editable="editable"
          collapsible
          @locate="locate"
          @fill-field="() => $router.push(`/gov/draft/${doc!.id}`)"
          @collapse="issuesOpen = false"
        ><template #footer><button type="button" class="gov-btn gov-btn--sm" :disabled="reviewing || (!session.isDemo && doc.docType !== 'notice')" @click="rerun">{{ reviewing ? '审校中…' : '重新审校' }}</button></template></IssuePanel>
      </aside>
    </div>

    <BaseDialog v-if="showRecords && doc" :title="`审核记录 · ${doc.title}`" :width="520" @close="showRecords = false">
      <ReviewTimeline :records="doc.history" />
    </BaseDialog>
  </GovLayout>
</template>

<style scoped>
.gov-proof { flex: 1 1 auto; min-height: 0; display: flex; margin-top: 8px; border-top: 1px solid var(--gov-border); }
.gov-proof__list { flex: 0 0 300px; width: 300px; min-height: 0; display: flex; flex-direction: column; border-right: 1px solid var(--gov-border); background: var(--gov-surface); }
.gov-proof__list.is-compact { flex-basis: 264px; width: 264px; }
.gov-proof__list-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 8px 10px 16px; border-bottom: 1px solid var(--gov-border); }
.gov-proof__list > :last-child { flex: 1 1 auto; min-height: 0; }
.gov-proof__center { flex: 1 1 0; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.gov-proof__center > .gov-a4-desk, .gov-proof__center > :last-child { flex: 1 1 auto; min-height: 0; }
.gov-proof__bar { flex: 0 0 auto; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 16px; background: var(--gov-surface); border-bottom: 1px solid var(--gov-border); }
.gov-proof__title { flex: 1 1 160px; min-width: 0; font-size: 14px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gov-proof__issues { flex: 0 0 336px; width: 336px; min-height: 0; border-left: 1px solid var(--gov-border); }
.gov-proof__issues.is-compact { flex-basis: 320px; width: 320px; }
</style>
