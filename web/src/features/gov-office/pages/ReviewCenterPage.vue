<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import GovLayout from "../components/layout/GovLayout.vue";
import GovPageHeader from "../components/layout/GovPageHeader.vue";
import StatusTag from "../components/common/StatusTag.vue";
import StoreMessages from "../components/common/StoreMessages.vue";
import BaseDialog from "../components/common/BaseDialog.vue";
import ReasonDialog from "../components/common/ReasonDialog.vue";
import A4Preview from "../components/document/A4Preview.vue";
import OfficialDocumentView from "../components/document/OfficialDocumentView.vue";
import DocumentFilterBar from "../components/review/DocumentFilterBar.vue";
import DocumentTable from "../components/review/DocumentTable.vue";
import IssueCard from "../components/review/IssueCard.vue";
import ReviewTimeline from "../components/review/ReviewTimeline.vue";
import { docTypeConfig, SEVERITY_LABELS, STATUS_LABELS, STATUS_TONES } from "../domain/docTypes";
import { documentGates, issueActions, summarizeIssues } from "../domain/issueRules";
import type { IssueAction, IssueEvaluation } from "../domain/issueRules";
import { COMPACT_BELOW } from "../composables/useViewport";
import { useDocumentFilter } from "../composables/useDocumentFilter";
import { useIssueMarks } from "../composables/useIssueMarks";
import { useGovDocumentsStore } from "../stores/govDocuments";
import { useGovSessionStore } from "../stores/govSession";

const store = useGovDocumentsStore();
const session = useGovSessionStore();

const docs = computed(() => store.list);
const { filter, filtered, counts, reset } = useDocumentFilter(docs, { status: "pending" });
const selectedId = ref("");
const doc = computed(() => store.byId[selectedId.value]);
const actor = computed(() => session.actor);
const { summary, marks } = useIssueMarks(doc);
const gates = computed(() => (doc.value && actor.value ? documentGates(doc.value, actor.value) : null));

const tab = ref<"review" | "preview" | "records">("review");
const opinion = ref("");
const opinionError = ref("");
const focusAnchor = ref("");
const dialog = ref<"" | "approve">("");
const reasonFor = ref<{ action: IssueAction; evaluation: IssueEvaluation } | null>(null);
const preview = ref<InstanceType<typeof A4Preview> | null>(null);

onMounted(async () => {
  await session.load();
  if (!store.order.length) await store.loadList();
});
// Auto-select only when nothing is selected. A document that leaves the
// current filter because the reviewer just returned or approved it stays
// open, so the reviewer can see the record that was written.
watch(
  filtered,
  (list) => {
    if (list.length && !store.byId[selectedId.value]) select(list[0].id);
  },
  { immediate: true },
);
watch(
  () => filter.value.status,
  () => {
    if (filtered.value.length && !filtered.value.some((d) => d.id === selectedId.value)) select(filtered.value[0].id);
  },
);

function select(id: string) {
  selectedId.value = id;
  opinion.value = "";
  opinionError.value = "";
  focusAnchor.value = "";
  tab.value = "review";
}

async function locate(anchor: string) {
  focusAnchor.value = anchor;
  tab.value = "preview";
  await preview.value?.scrollToAnchor(anchor);
}

function onIssueAction(evaluation: IssueEvaluation, action: IssueAction) {
  if (action === "locate") {
    locate(evaluation.issue.anchor);
    return;
  }
  if (action === "ai_confirm" && doc.value && actor.value) {
    store.resolveIssue(doc.value.id, evaluation.issue.id, { kind: "ai_confirmed", by: actor.value.name, at: new Date().toISOString() }, "已确认该 AI 问题成立，需退回起草人修复。");
    return;
  }
  if (action === "approve_exception" || action === "ai_dismiss") reasonFor.value = { action, evaluation };
}

/** The review center only exposes reviewer decisions; editing actions stay with the drafter. */
function reviewerActions(evaluation: IssueEvaluation): IssueAction[] {
  if (!doc.value || !actor.value) return [];
  return issueActions(evaluation.issue, doc.value, actor.value).filter((a) => ["locate", "approve_exception", "ai_confirm", "ai_dismiss"].includes(a));
}

async function confirmReason(reason: string) {
  const current = reasonFor.value;
  if (!current || !doc.value || !actor.value) return;
  const base = { by: actor.value.name, reason, at: new Date().toISOString() };
  if (current.action === "approve_exception") await store.resolveIssue(doc.value.id, current.evaluation.issue.id, { kind: "exception_approved", ...base }, "已批准例外并记录。");
  else await store.resolveIssue(doc.value.id, current.evaluation.issue.id, { kind: "ai_dismissed", ...base }, "已记录人工复核结论。");
  reasonFor.value = null;
}

async function doReturn() {
  if (!doc.value) return;
  if (!opinion.value.trim()) {
    opinionError.value = "退回修改时请填写审核意见。";
    return;
  }
  const updated = await store.returnForRevision(doc.value.id, opinion.value);
  if (updated) {
    opinion.value = "";
    tab.value = "records";
  }
}

async function doApprove() {
  if (!doc.value) return;
  const updated = await store.approve(doc.value.id, opinion.value);
  dialog.value = "";
  if (updated) {
    opinion.value = "";
    tab.value = "records";
  }
}

const lockedText = computed(() => {
  if (!doc.value) return "";
  return {
    draft: "该文稿尚未提交审核，暂不能执行审核操作。",
    returned: "该文稿已退回修改，等待起草人修改后重新提交。",
    approved: "该文稿已审核通过。如需修改，请由起草人发起新版本。",
    pending: "",
  }[doc.value.status];
});
</script>

<template>
  <GovLayout :auto-collapse-below="COMPACT_BELOW">
    <GovPageHeader title="审核中心" subtitle="待审核任务、审核通过与退回、例外批准及审核记录">
      <template #actions>
        <RouterLink to="/gov/proofread" class="gov-btn">前往文稿审校</RouterLink>
      </template>
    </GovPageHeader>
    <DocumentFilterBar v-model="filter" :counts="counts" :statuses="['pending', 'returned', 'approved', 'all']" :result-count="filtered.length" />
    <div v-if="session.loaded && !session.isReviewer" class="gov-banner gov-banner--warning gov-rc__role" role="status">
      当前身份（{{ session.actor?.account }}）没有审核权限，只能查看。<template v-if="session.isDemo">演示审批流程请在左下角切换为审核人 demo_reviewer。</template>
    </div>
    <StoreMessages />

    <div class="gov-rc">
      <section class="gov-rc__list gov-card" aria-label="审核任务">
        <DocumentTable :docs="filtered" :selected-id="selectedId" @select="select" @reset="reset" />
      </section>

      <section v-if="doc && actor && gates && summary" class="gov-rc__detail gov-card" aria-label="审核详情">
        <div class="gov-rc__head">
          <h2 class="gov-section-title">{{ doc.title }}</h2>
          <div class="gov-rc__tags">
            <StatusTag tone="neutral" :label="docTypeConfig(doc.docType).label" />
            <StatusTag :tone="STATUS_TONES[doc.status]" :label="STATUS_LABELS[doc.status]" />
            <span class="gov-muted">{{ doc.author }}（{{ doc.department }}） · {{ doc.createdAt }} · 第 {{ doc.version }} 版</span>
          </div>
        </div>
        <div class="gov-rc__tabs" role="tablist" aria-label="详情分区">
          <button type="button" role="tab" :aria-selected="tab === 'review'" :class="{ 'is-active': tab === 'review' }" @click="tab = 'review'">审核要点</button>
          <button type="button" role="tab" :aria-selected="tab === 'preview'" :class="{ 'is-active': tab === 'preview' }" @click="tab = 'preview'">文稿预览</button>
          <button type="button" role="tab" :aria-selected="tab === 'records'" :class="{ 'is-active': tab === 'records' }" @click="tab = 'records'">审核记录（{{ doc.history.length }}）</button>
        </div>

        <div v-show="tab === 'review'" class="gov-rc__body">
          <div class="gov-rc__summary">
            <span>未处理：</span>
            <span class="gov-tag gov-tag--danger">{{ SEVERITY_LABELS.critical }} {{ summary.open.critical }}</span>
            <span class="gov-tag gov-tag--warning">{{ SEVERITY_LABELS.warning }} {{ summary.open.warning }}</span>
            <span class="gov-tag gov-tag--info">{{ SEVERITY_LABELS.hint }} {{ summary.open.hint }}</span>
          </div>

          <h3 class="gov-subtitle">阻断审批的严重问题（{{ gates.blockers.length }}）</h3>
          <IssueCard
            v-for="e in gates.blockers"
            :key="e.issue.id"
            :evaluation="e"
            :actions="reviewerActions(e)"
            :focused="focusAnchor === e.issue.anchor"
            :editable="false"
            @action="onIssueAction(e, $event)"
          />
          <div v-if="doc.checkStatus === 'not_run'" class="gov-banner gov-banner--warning">自动审校未接入，请核对全文和材料后进行人工审核。审核通过不代表自动检查通过。</div>
          <div v-else-if="!gates.blockers.length" class="gov-banner gov-banner--success">没有阻断审批的严重问题。</div>

          <template v-if="summary.humanReviewed.length">
            <h3 class="gov-subtitle">人工复核与例外记录</h3>
            <div v-for="e in summary.humanReviewed" :key="e.issue.id" class="gov-rc__reviewed">
              <span class="gov-rc__reviewed-title">{{ e.issue.title }}</span>
              <span class="gov-muted">{{ e.resolvedLabel }}<template v-if="e.resolution && 'reason' in e.resolution"> · 理由：{{ e.resolution.reason }}</template></span>
            </div>
          </template>
        </div>

        <div v-show="tab === 'preview'" class="gov-rc__preview">
          <A4Preview ref="preview" zoom="fit" :watermark="doc.status !== 'approved' ? '未审核' : ''" :corner-note="doc.origin === 'demo' ? '演示文稿 · 内容虚构' : ''">
            <OfficialDocumentView :doc="doc" :marks="marks" :focus-anchor="focusAnchor" />
          </A4Preview>
        </div>

        <div v-show="tab === 'records'" class="gov-rc__body">
          <ReviewTimeline :records="doc.history" />
        </div>

        <footer class="gov-rc__foot">
          <template v-if="doc.status === 'pending'">
            <label class="gov-label" for="gov-rc-opinion">审核意见</label>
            <textarea
              id="gov-rc-opinion"
              v-model="opinion"
              class="gov-textarea"
              rows="2"
              placeholder="退回修改时必填，例如：请补充报送截止时间"
              @input="opinionError = ''"
            />
            <span v-if="opinionError" role="alert" class="gov-rc__error">{{ opinionError }}</span>
            <span v-if="!gates.canApprove" class="gov-rc__reason">{{ gates.approveBlockedReason }}</span>
            <div class="gov-rc__actions">
              <button type="button" class="gov-btn gov-btn--danger" :disabled="!gates.canReturn" @click="doReturn">退回修改</button>
              <button type="button" class="gov-btn gov-btn--primary" :disabled="!gates.canApprove" @click="dialog = 'approve'">审核通过</button>
            </div>
          </template>
          <span v-else class="gov-muted" style="font-size: 13px">{{ lockedText }}</span>
        </footer>
      </section>
      <section v-else class="gov-rc__detail gov-card gov-rc__placeholder">
        <span class="gov-muted">{{ filtered.length ? "请选择左侧文稿" : "当前筛选下没有文稿" }}</span>
      </section>
    </div>

    <BaseDialog v-if="dialog === 'approve' && doc && summary" title="确认审核通过？" @close="dialog = ''">
      <p style="margin: 0">《{{ doc.title }}》审核通过后状态变为「审核通过」，并写入审核记录。</p>
      <p v-if="summary.open.warning + summary.open.hint" style="margin: 0">仍有 {{ summary.open.warning + summary.open.hint }} 项警告或提示，不影响审批。</p>
      <p v-if="summary.humanReviewed.length" style="margin: 0">其中 {{ summary.humanReviewed.length }} 项严重问题经人工复核或例外批准放行，详见审核要点。</p>
      <template #footer>
        <button type="button" class="gov-btn" data-dialog-close @click="dialog = ''">取消</button>
        <button type="button" class="gov-btn gov-btn--primary" @click="doApprove">确认通过</button>
      </template>
    </BaseDialog>

    <ReasonDialog
      v-if="reasonFor && actor"
      :title="reasonFor.action === 'approve_exception' ? '批准例外' : '人工复核：判定 AI 问题不成立'"
      :description="reasonFor.action === 'approve_exception'
        ? '批准后该严重问题不再阻断审批与正式导出。审核人与理由将记入审核记录，且不能撤销。'
        : '该严重问题由 AI 判断。判定不成立后不再阻断审批，理由与复核人将记入审核记录。'"
      :confirm-label="reasonFor.action === 'approve_exception' ? '批准例外' : '确认不成立'"
      :actor-name="actor.name"
      @close="reasonFor = null"
      @confirm="confirmReason"
    />
  </GovLayout>
</template>

<style scoped>
.gov-rc__role { margin: 8px 24px 0; flex: 0 0 auto; }
.gov-rc { flex: 1 1 auto; min-height: 0; display: flex; gap: 16px; padding: 12px 24px 16px; }
.gov-rc__list { flex: 1 1 0; min-width: 0; min-height: 0; overflow: hidden; }
.gov-rc__detail { flex: 0 0 460px; width: 460px; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.gov-rc__placeholder { align-items: center; justify-content: center; }
.gov-rc__head { padding: 16px 20px 12px; border-bottom: 1px solid var(--gov-border); display: flex; flex-direction: column; gap: 8px; }
.gov-rc__tags { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.gov-rc__tabs { display: flex; gap: 20px; padding: 0 20px; border-bottom: 1px solid var(--gov-border); }
.gov-rc__tabs button { height: 40px; padding: 0; border: 0; background: transparent; color: var(--gov-text-3); font-size: 13px; cursor: pointer; }
.gov-rc__tabs button.is-active { color: var(--gov-primary); font-weight: 700; box-shadow: inset 0 -2px 0 var(--gov-primary); }
.gov-rc__body { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 10px; }
.gov-rc__preview { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.gov-rc__preview > * { flex: 1 1 auto; min-height: 0; }
.gov-rc__summary { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 13px; color: var(--gov-text-2); }
.gov-rc__reviewed { display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; border-radius: var(--gov-r-md); background: var(--gov-surface-2); border: 1px solid var(--gov-border); }
.gov-rc__reviewed-title { font-size: 13px; font-weight: 500; }
.gov-rc__foot { flex: 0 0 auto; padding: 12px 20px 16px; border-top: 1px solid var(--gov-border); display: flex; flex-direction: column; gap: 8px; }
.gov-rc__error { font-size: 12px; color: var(--gov-red); }
.gov-rc__reason { font-size: 12px; line-height: 18px; color: var(--gov-warn); }
.gov-rc__actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
