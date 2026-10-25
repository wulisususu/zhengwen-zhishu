<script setup lang="ts">
import { computed } from "vue";
import { Crosshair } from "lucide-vue-next";
import StatusTag from "../common/StatusTag.vue";
import { SEVERITY_LABELS, SEVERITY_TONES, SOURCE_LABELS } from "../../domain/docTypes";
import type { IssueAction, IssueEvaluation } from "../../domain/issueRules";

const props = defineProps<{ evaluation: IssueEvaluation; actions: IssueAction[]; focused: boolean; editable: boolean }>();
const emit = defineEmits<{ (e: "action", action: IssueAction): void }>();

const ACTION_LABELS: Record<IssueAction, string> = {
  locate: "定位",
  apply_suggestion: "采纳建议",
  fill_field: "去填写",
  ignore_hint: "忽略提示",
  ai_confirm: "确认是问题",
  ai_dismiss: "判定不成立…",
  request_exception: "申请例外…",
  approve_exception: "批准例外…",
  undo: "撤销",
};
/** Actions that change the document text or fields need an editable document. */
const EDIT_ACTIONS: IssueAction[] = ["apply_suggestion", "fill_field"];

const issue = computed(() => props.evaluation.issue);
const stateTag = computed(() => {
  switch (props.evaluation.state) {
    case "needs_human_review":
      return { label: "待人工复核", tone: "warning" as const };
    case "confirmed_open":
      return { label: "已确认，待修复", tone: "danger" as const };
    case "exception_pending":
      return { label: "例外待审核人批准", tone: "warning" as const };
    default:
      return null;
  }
});
const sourceLabel = computed(() => (issue.value.source === "ai" ? `${SOURCE_LABELS.ai} · 需人工判断` : SOURCE_LABELS.rule));
const secondary = computed(() => props.actions.filter((a) => a !== "locate"));
const primaryAction = computed(() => secondary.value.find((a) => ["apply_suggestion", "fill_field", "ai_confirm", "approve_exception"].includes(a)));
const exceptionReason = computed(() => {
  const r = props.evaluation.resolution;
  return r && r.kind === "exception_requested" ? `${r.by}：${r.reason}` : "";
});
</script>

<template>
  <article class="gov-issue" :class="{ 'is-focused': focused }">
    <div class="gov-issue__tags">
      <StatusTag :tone="SEVERITY_TONES[issue.severity]" :label="SEVERITY_LABELS[issue.severity]" />
      <StatusTag :tone="issue.source === 'ai' ? 'outline' : 'neutral'" :label="sourceLabel" />
      <StatusTag v-if="stateTag" :tone="stateTag.tone" :label="stateTag.label" />
      <span class="gov-issue__loc">{{ issue.locationLabel }}</span>
    </div>
    <h3 class="gov-issue__title">{{ issue.title }}</h3>
    <p class="gov-issue__desc">{{ issue.description }}</p>
    <p v-if="issue.suggestion" class="gov-issue__suggest">建议：{{ issue.suggestion.text }}</p>
    <p v-if="exceptionReason" class="gov-issue__suggest">例外申请 · {{ exceptionReason }}</p>
    <div class="gov-issue__actions">
      <button type="button" class="gov-btn gov-btn--sm" @click="emit('action', 'locate')">
        <Crosshair :size="13" aria-hidden="true" />定位
      </button>
      <button
        v-for="action in secondary"
        :key="action"
        type="button"
        class="gov-btn gov-btn--sm"
        :class="action === primaryAction ? 'gov-btn--primary' : action === 'ignore_hint' || action === 'undo' ? 'gov-btn--text' : ''"
        :disabled="!editable && EDIT_ACTIONS.includes(action)"
        @click="emit('action', action)"
      >
        {{ ACTION_LABELS[action] }}
      </button>
    </div>
  </article>
</template>

<style scoped>
.gov-issue {
  display: flex; flex-direction: column; gap: 8px; padding: 12px;
  border: 1px solid var(--gov-border); border-radius: var(--gov-r-md); background: var(--gov-surface);
}
.gov-issue.is-focused { border: 1.5px solid var(--gov-primary); background: #f4f7fc; }
.gov-issue__tags { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.gov-issue__loc { margin-left: auto; font-size: 12px; color: var(--gov-text-3); }
.gov-issue__title { margin: 0; font-size: 14px; font-weight: 500; line-height: 20px; }
.gov-issue__desc { margin: 0; font-size: 13px; line-height: 20px; color: var(--gov-text-2); }
.gov-issue__suggest {
  margin: 0; font-size: 13px; line-height: 20px; padding: 8px 10px; border-radius: var(--gov-r-sm);
  background: var(--gov-surface-2); border: 1px solid var(--gov-border);
}
.gov-issue__actions { display: flex; gap: 6px; flex-wrap: wrap; }
</style>
