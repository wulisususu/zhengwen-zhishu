<script setup lang="ts">
import { computed } from "vue";
import { ChevronLeft, PanelRightClose } from "lucide-vue-next";
import StatusTag from "../common/StatusTag.vue";
import { POLICY_STATUS_LABELS, POLICY_STATUS_TONES } from "../../domain/docTypes";
import type { Citation } from "../../types";

const props = defineProps<{ citationIds: string[]; citations: Record<string, Citation>; selectedId: string }>();
const emit = defineEmits<{ (e: "select", id: string): void; (e: "back"): void; (e: "collapse"): void }>();

const list = computed(() => props.citationIds.map((id, i) => ({ idx: i + 1, c: props.citations[id] })).filter((x) => !!x.c));
const detail = computed(() => {
  const c = props.citations[props.selectedId];
  if (!c) return null;
  return { c, idx: props.citationIds.indexOf(c.id) + 1 };
});
</script>

<template>
  <section class="gov-evidence" aria-label="政策依据面板">
    <template v-if="!detail">
      <div class="gov-evidence__head">
        <h2 class="gov-section-title">本次回答的引用依据</h2>
        <span class="gov-muted">{{ list.length }} 条</span>
        <button type="button" class="gov-btn gov-btn--text gov-btn--icon" aria-label="收起依据栏" @click="emit('collapse')">
          <PanelRightClose :size="18" aria-hidden="true" />
        </button>
      </div>
      <div class="gov-evidence__body">
        <button v-for="item in list" :key="item.c.id" type="button" class="gov-evidence__card" @click="emit('select', item.c.id)">
          <span class="gov-evidence__row">
            <span class="gov-evidence__idx">[{{ item.idx }}]</span>
            <StatusTag :tone="POLICY_STATUS_TONES[item.c.status]" :label="POLICY_STATUS_LABELS[item.c.status]" />
            <span class="gov-muted gov-evidence__clause">{{ item.c.clause }}</span>
          </span>
          <span class="gov-evidence__title">《{{ item.c.policyTitle }}》</span>
          <span class="gov-muted">{{ item.c.docNumber }} · {{ item.c.issuer }}</span>
          <span class="gov-evidence__excerpt">{{ item.c.excerpt }}</span>
        </button>
        <div v-if="!list.length" class="gov-empty">
          <strong style="display: block; color: var(--gov-text-2); margin-bottom: 4px">本次回答无引用依据</strong>
          未检索到达到可信阈值的条款，系统未生成结论。
        </div>
      </div>
    </template>

    <template v-else>
      <div class="gov-evidence__head">
        <button type="button" class="gov-btn gov-btn--text" @click="emit('back')"><ChevronLeft :size="16" aria-hidden="true" />返回依据列表</button>
        <span class="gov-muted" style="margin-left: auto">原文详情</span>
      </div>
      <div class="gov-evidence__body">
        <span class="gov-evidence__row">
          <span class="gov-evidence__idx">[{{ detail.idx }}]</span>
          <StatusTag :tone="POLICY_STATUS_TONES[detail.c.status]" :label="POLICY_STATUS_LABELS[detail.c.status]" />
        </span>
        <h3 class="gov-evidence__detail-title">《{{ detail.c.policyTitle }}》</h3>
        <dl class="gov-evidence__meta">
          <dt>文号</dt><dd>{{ detail.c.docNumber }}</dd>
          <dt>发布机关</dt><dd>{{ detail.c.issuer }}</dd>
          <dt>发布日期</dt><dd>{{ detail.c.issuedOn }}</dd>
          <dt>生效日期</dt><dd>{{ detail.c.effectiveOn }}</dd>
          <dt>失效日期</dt><dd>{{ detail.c.expiresOn }}</dd>
        </dl>
        <div v-if="detail.c.statusNote" class="gov-banner" :class="detail.c.status === 'abolished' ? 'gov-banner--danger' : 'gov-banner--warning'">{{ detail.c.statusNote }}</div>
        <div class="gov-evidence__block">
          <span class="gov-evidence__label">条款原文 · {{ detail.c.clause }}</span>
          <p class="gov-evidence__clause-text">{{ detail.c.text.before }}<mark>{{ detail.c.text.highlight }}</mark>{{ detail.c.text.after }}</p>
        </div>
        <div class="gov-evidence__block">
          <span class="gov-evidence__label">上下文</span>
          <span v-if="detail.c.previousClause" class="gov-evidence__ctx">上一条：{{ detail.c.previousClause }}</span>
          <span v-if="detail.c.nextClause" class="gov-evidence__ctx">下一条：{{ detail.c.nextClause }}</span>
        </div>
        <button type="button" class="gov-btn gov-btn--sm" style="align-self: flex-start" disabled title="政策全文查看待接入政策库">查看全文（待接入）</button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.gov-evidence { height: 100%; display: flex; flex-direction: column; min-height: 0; background: var(--gov-surface); }
.gov-evidence__head { display: flex; align-items: center; gap: 8px; padding: 12px 16px 12px 20px; border-bottom: 1px solid var(--gov-border); min-height: 56px; }
.gov-evidence__head .gov-section-title { flex: 1 1 auto; }
.gov-evidence__body { flex: 1 1 auto; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.gov-evidence__card {
  text-align: left; width: 100%; padding: 14px; border: 1px solid var(--gov-border); border-radius: var(--gov-r-md);
  background: var(--gov-surface); display: flex; flex-direction: column; gap: 6px; cursor: pointer;
}
.gov-evidence__card:hover { border-color: var(--gov-primary); }
.gov-evidence__row { display: flex; align-items: center; gap: 8px; }
.gov-evidence__idx { font-size: 13px; font-weight: 700; color: var(--gov-primary); }
.gov-evidence__clause { margin-left: auto; }
.gov-evidence__title { font-size: 14px; font-weight: 500; line-height: 20px; }
.gov-evidence__excerpt { font-size: 13px; line-height: 20px; color: var(--gov-text-2); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.gov-evidence__detail-title { margin: 0; font-size: 16px; font-weight: 700; line-height: 24px; }
.gov-evidence__meta { margin: 0; display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 8px; font-size: 13px; }
.gov-evidence__meta dt { color: var(--gov-text-3); }
.gov-evidence__meta dd { margin: 0; }
.gov-evidence__block { display: flex; flex-direction: column; gap: 6px; }
.gov-evidence__label { font-size: 13px; font-weight: 700; color: var(--gov-text-2); }
.gov-evidence__clause-text {
  margin: 0; padding: 14px 16px; border-radius: var(--gov-r-md); background: var(--gov-surface-2); border: 1px solid var(--gov-border);
  font-family: var(--gov-font-doc-body); font-size: 15px; line-height: 26px;
}
.gov-evidence__clause-text mark { background: #fde9b8; color: inherit; padding: 0 2px; }
.gov-evidence__ctx { font-size: 13px; line-height: 20px; color: var(--gov-text-3); }
</style>
