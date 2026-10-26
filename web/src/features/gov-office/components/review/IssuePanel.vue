<script setup lang="ts">
import { computed, ref } from "vue";
import { PanelRightClose } from "lucide-vue-next";
import IssueCard from "./IssueCard.vue";
import ReasonDialog from "../common/ReasonDialog.vue";
import { issueActions, summarizeIssues } from "../../domain/issueRules";
import type { IssueAction, IssueEvaluation } from "../../domain/issueRules";
import { useGovDocumentsStore } from "../../stores/govDocuments";
import type { Actor, FieldKey, IssueResolution, OfficialDocument } from "../../types";

const props = withDefaults(
  defineProps<{ doc: OfficialDocument; actor: Actor; focusAnchor: string; editable: boolean; collapsible?: boolean; rerunLabel?: string }>(),
  { collapsible: false, rerunLabel: "" },
);
const emit = defineEmits<{
  (e: "locate", anchor: string): void;
  (e: "fill-field", field: FieldKey): void;
  (e: "collapse"): void;
}>();

const store = useGovDocumentsStore();
const filter = ref<"all" | "rule" | "ai">("all");
const showResolved = ref(false);
const dialog = ref<{ kind: "ai_dismiss" | "request_exception" | "approve_exception"; evaluation: IssueEvaluation } | null>(null);

const summary = computed(() => summarizeIssues(props.doc));
const visible = computed(() => summary.value.unresolved.filter((e) => filter.value === "all" || e.issue.source === filter.value));
const filters = [
  { key: "all" as const, label: "全部" },
  { key: "rule" as const, label: "规则检查" },
  { key: "ai" as const, label: "AI 语义审查" },
];

function now() {
  return new Date().toISOString();
}

async function resolve(evaluation: IssueEvaluation, resolution: IssueResolution, notice: string) {
  await store.resolveIssue(props.doc.id, evaluation.issue.id, resolution, notice);
}

function onAction(evaluation: IssueEvaluation, action: IssueAction) {
  const issue = evaluation.issue;
  const by = props.actor.name;
  switch (action) {
    case "locate":
      emit("locate", issue.anchor);
      return;
    case "fill_field":
      if (issue.requiredField) emit("fill-field", issue.requiredField);
      return;
    case "apply_suggestion":
      store.applySuggestion(props.doc.id, issue.id);
      emit("locate", issue.anchor);
      return;
    case "ignore_hint":
      resolve(evaluation, { kind: "hint_ignored", by, at: now() }, "已忽略该提示。");
      return;
    case "ai_confirm":
      resolve(evaluation, { kind: "ai_confirmed", by, at: now() }, "已确认该 AI 问题成立，请修复后再提交正式审批。");
      return;
    case "undo":
      store.clearResolution(props.doc.id, issue.id);
      return;
    default:
      dialog.value = { kind: action, evaluation };
  }
}

const dialogCopy = computed(() => {
  switch (dialog.value?.kind) {
    case "ai_dismiss":
      return {
        title: "人工复核：判定 AI 问题不成立",
        description: "该严重问题由 AI 判断。判定不成立后不再阻断审批，理由与复核人将记入审核记录。",
        confirm: "确认不成立",
      };
    case "request_exception":
      return {
        title: "申请例外处理",
        description: "确定性规则检查发现的严重问题原则上必须修复。申请例外后仍会阻断审批，需审核人批准并记录理由。",
        confirm: "提交例外申请",
      };
    case "approve_exception":
      return {
        title: "批准例外",
        description: "批准后该严重问题不再阻断审批与正式导出。审核人与理由将记入审核记录，且不能撤销。",
        confirm: "批准例外",
      };
    default:
      return { title: "", description: "", confirm: "" };
  }
});

async function confirmDialog(reason: string) {
  const current = dialog.value;
  if (!current) return;
  const base = { by: props.actor.name, reason, at: now() };
  if (current.kind === "ai_dismiss") await resolve(current.evaluation, { kind: "ai_dismissed", ...base }, "已记录人工复核结论。");
  if (current.kind === "request_exception") await resolve(current.evaluation, { kind: "exception_requested", ...base }, "已提交例外申请，等待审核人批准。");
  if (current.kind === "approve_exception") await resolve(current.evaluation, { kind: "exception_approved", ...base }, "已批准例外并记录。");
  dialog.value = null;
}
</script>

<template>
  <section class="gov-issues" aria-label="审校问题">
    <div class="gov-issues__head">
      <div class="gov-issues__title-row">
        <h2 class="gov-section-title">审校问题 <span class="gov-issues__count">{{ summary.unresolved.length }}</span></h2>
        <span class="gov-muted">已处理 {{ summary.resolved.length }}</span>
        <button v-if="collapsible" type="button" class="gov-btn gov-btn--text gov-btn--icon" aria-label="收起审校栏" @click="emit('collapse')">
          <PanelRightClose :size="18" aria-hidden="true" />
        </button>
      </div>
      <div class="gov-issues__chips">
        <span class="gov-tag gov-tag--danger">严重 {{ summary.open.critical }}</span>
        <span class="gov-tag gov-tag--warning">警告 {{ summary.open.warning }}</span>
        <span class="gov-tag gov-tag--info">提示 {{ summary.open.hint }}</span>
      </div>
      <div class="gov-issues__tabs" role="tablist" aria-label="问题来源筛选">
        <button
          v-for="f in filters"
          :key="f.key"
          type="button"
          role="tab"
          :aria-selected="filter === f.key"
          class="gov-issues__tab"
          :class="{ 'is-active': filter === f.key }"
          @click="filter = f.key"
        >
          {{ f.label }}
        </button>
      </div>
    </div>

    <div class="gov-issues__list">
      <div v-if="doc.origin === 'backend' && doc.review" class="gov-banner" :class="doc.review.formatCheck.status === 'unavailable' ? 'gov-banner--danger' : 'gov-banner--info'">
        确定性规则 + gongwen-kit 写法机检：{{ doc.review.formatCheck.status === 'unavailable' ? '格式机检未完成' : doc.review.formatCheck.status === 'hit' ? '发现格式问题' : '格式机检完成' }}。
        {{ doc.review.formatCheck.message }} {{ doc.review.gate.reasons.join('；') }}
      </div>
      <IssueCard
        v-for="e in visible"
        :key="e.issue.id"
        :evaluation="e"
        :actions="issueActions(e.issue, doc, actor)"
        :focused="focusAnchor === e.issue.anchor"
        :editable="editable"
        @action="onAction(e, $event)"
      />
      <div v-if="doc.checkStatus === 'not_run'" class="gov-banner gov-banner--warning">尚未运行当前文稿的审校；修改后须重新检查，没有问题记录不代表通过。</div>
      <div v-else-if="!visible.length" class="gov-empty">当前筛选下没有待处理问题</div>

      <button type="button" class="gov-btn gov-btn--text" style="align-self: flex-start" @click="showResolved = !showResolved">
        {{ showResolved ? "收起已处理问题" : `查看已处理问题（${summary.resolved.length}）` }}
      </button>
      <template v-if="showResolved">
        <div v-for="e in summary.resolved" :key="e.issue.id" class="gov-issues__done">
          <span class="gov-issues__done-title">{{ e.issue.title }}</span>
          <span class="gov-issues__done-how">{{ e.resolvedLabel }}</span>
          <button
            v-if="issueActions(e.issue, doc, actor).includes('undo')"
            type="button"
            class="gov-btn gov-btn--text gov-btn--sm"
            @click="onAction(e, 'undo')"
          >
            撤销
          </button>
        </div>
      </template>
    </div>

    <footer class="gov-issues__foot">
      <span class="gov-muted">{{ doc.origin === 'backend' ? '双层规则审校，未执行 AI 语义审查' : '规则检查与 AI 审查结果' }}；最近审校 {{ doc.lastReviewedAt || '未运行' }}<template v-if="rerunLabel">（{{ rerunLabel }}）</template></span>
      <slot name="footer" />
    </footer>

    <ReasonDialog
      v-if="dialog"
      :title="dialogCopy.title"
      :description="dialogCopy.description"
      :confirm-label="dialogCopy.confirm"
      :actor-name="actor.name"
      @close="dialog = null"
      @confirm="confirmDialog"
    />
  </section>
</template>

<style scoped>
.gov-issues { display: flex; flex-direction: column; min-height: 0; height: 100%; background: var(--gov-surface); }
.gov-issues__head { padding: 14px 16px 12px; border-bottom: 1px solid var(--gov-border); display: flex; flex-direction: column; gap: 10px; }
.gov-issues__title-row { display: flex; align-items: center; gap: 8px; }
.gov-issues__title-row .gov-section-title { flex: 1 1 auto; }
.gov-issues__count { font-weight: 400; color: var(--gov-text-3); }
.gov-issues__chips { display: flex; gap: 6px; flex-wrap: wrap; }
.gov-issues__tabs { display: flex; gap: 4px; background: var(--gov-bg); padding: 3px; border-radius: var(--gov-r-md); }
.gov-issues__tab { flex: 1 1 0; height: 28px; border: 0; border-radius: var(--gov-r-sm); background: transparent; color: var(--gov-text-3); font-size: 12px; cursor: pointer; white-space: nowrap; }
.gov-issues__tab.is-active { background: var(--gov-surface); color: var(--gov-text-1); font-weight: 500; box-shadow: 0 1px 2px rgba(16, 36, 63, 0.12); }
.gov-issues__list { flex: 1 1 auto; overflow-y: auto; padding: 12px 16px; display: flex; flex-direction: column; gap: 10px; }
.gov-issues__done { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: var(--gov-r-md); background: var(--gov-surface-2); font-size: 13px; color: var(--gov-text-3); }
.gov-issues__done-title { flex: 1 1 auto; text-decoration: line-through; }
.gov-issues__done-how { flex: 0 1 auto; text-align: right; }
.gov-issues__foot { padding: 10px 16px; border-top: 1px solid var(--gov-border); display: flex; align-items: center; justify-content: space-between; gap: 8px; }
</style>
