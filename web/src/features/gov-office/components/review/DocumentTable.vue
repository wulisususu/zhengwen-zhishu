<script setup lang="ts">
import StatusTag from "../common/StatusTag.vue";
import { docTypeConfig, SEVERITY_LABELS, SEVERITY_TONES, STATUS_LABELS, STATUS_TONES } from "../../domain/docTypes";
import { summarizeIssues } from "../../domain/issueRules";
import type { OfficialDocument } from "../../types";

withDefaults(defineProps<{ docs: OfficialDocument[]; selectedId: string; variant?: "table" | "compact" }>(), { variant: "table" });
const emit = defineEmits<{ (e: "select", id: string): void; (e: "reset"): void }>();

function issueChips(doc: OfficialDocument) {
  const { open } = summarizeIssues(doc);
  return (["critical", "warning", "hint"] as const)
    .filter((k) => open[k] > 0)
    .map((k) => ({ key: k, label: `${SEVERITY_LABELS[k]} ${open[k]}`, tone: SEVERITY_TONES[k] }));
}
</script>

<template>
  <div v-if="variant === 'compact'" class="gov-list" aria-label="文稿列表">
    <button
      v-for="doc in docs"
      :key="doc.id"
      type="button"
      class="gov-list__item"
      :class="{ 'is-selected': doc.id === selectedId }"
      :aria-pressed="doc.id === selectedId"
      @click="emit('select', doc.id)"
    >
      <span class="gov-table__title">{{ doc.title }}</span>
      <span class="gov-muted">{{ docTypeConfig(doc.docType).label }} · {{ doc.author }} · {{ doc.createdAt }}</span>
      <span class="gov-table__chips">
        <StatusTag :tone="STATUS_TONES[doc.status]" :label="STATUS_LABELS[doc.status]" />
        <StatusTag v-for="c in issueChips(doc)" :key="c.key" :tone="c.tone" :label="c.label" />
      </span>
    </button>
    <div v-if="!docs.length" class="gov-table__empty">
      <span>没有符合条件的文稿</span>
      <button type="button" class="gov-btn gov-btn--sm" @click="emit('reset')">清除筛选</button>
    </div>
  </div>
  <div v-else class="gov-table" role="table" aria-label="文稿列表">
    <div class="gov-table__row gov-table__row--head" role="row">
      <span role="columnheader">文稿名称 / 创建人 · 创建时间</span>
      <span role="columnheader">文种</span>
      <span role="columnheader">未处理问题</span>
      <span role="columnheader">状态</span>
    </div>
    <div class="gov-table__body">
      <button
        v-for="doc in docs"
        :key="doc.id"
        type="button"
        role="row"
        class="gov-table__row"
        :class="{ 'is-selected': doc.id === selectedId }"
        :aria-pressed="doc.id === selectedId"
        @click="emit('select', doc.id)"
      >
        <span class="gov-table__name" role="cell">
          <span class="gov-table__title">{{ doc.title }}</span>
          <span class="gov-muted">{{ doc.author }}（{{ doc.department }}） · {{ doc.createdAt }}</span>
        </span>
        <span role="cell" class="gov-table__type">{{ docTypeConfig(doc.docType).label }}</span>
        <span role="cell" class="gov-table__chips">
          <StatusTag v-for="c in issueChips(doc)" :key="c.key" :tone="c.tone" :label="c.label" />
          <span v-if="!issueChips(doc).length" class="gov-muted">{{ doc.checkStatus === 'not_run' ? '未检查' : '无' }}</span>
        </span>
        <span role="cell"><StatusTag :tone="STATUS_TONES[doc.status]" :label="STATUS_LABELS[doc.status]" /></span>
      </button>
      <div v-if="!docs.length" class="gov-table__empty">
        <span>没有符合条件的文稿</span>
        <button type="button" class="gov-btn gov-btn--sm" @click="emit('reset')">清除筛选</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gov-table { display: flex; flex-direction: column; min-height: 0; height: 100%; overflow-x: auto; }
.gov-table__row {
  display: grid; grid-template-columns: minmax(200px, 1fr) 72px 136px 84px; gap: 12px; align-items: center;
  width: 100%; min-width: 540px; text-align: left; padding: 12px 16px; border: 0; border-bottom: 1px solid var(--gov-border);
  background: var(--gov-surface); font-size: 13px; cursor: pointer;
}
.gov-table__row:hover:not(.gov-table__row--head) { background: var(--gov-surface-2); }
.gov-table__row--head { cursor: default; padding-top: 10px; padding-bottom: 10px; background: var(--gov-surface-2); color: var(--gov-text-3); font-size: 12px; }
.gov-table__row.is-selected { background: var(--gov-primary-50); box-shadow: inset 3px 0 0 var(--gov-primary); }
.gov-table__body { flex: 1 1 auto; overflow-y: auto; min-width: 540px; }
.gov-table__name { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.gov-table__title { font-size: 14px; font-weight: 500; line-height: 20px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gov-table__type { color: var(--gov-text-2); }
.gov-table__chips { display: flex; gap: 4px; flex-wrap: wrap; }
.gov-list { height: 100%; overflow-y: auto; display: flex; flex-direction: column; }
.gov-list__item {
  display: flex; flex-direction: column; gap: 4px; width: 100%; text-align: left; padding: 12px 16px; border: 0;
  border-bottom: 1px solid var(--gov-border); background: var(--gov-surface); cursor: pointer;
}
.gov-list__item:hover { background: var(--gov-surface-2); }
.gov-list__item.is-selected { background: var(--gov-primary-50); box-shadow: inset 3px 0 0 var(--gov-primary); }
.gov-list__item .gov-table__title { white-space: normal; }
.gov-table__empty { padding: 40px 16px; display: flex; flex-direction: column; align-items: center; gap: 8px; color: var(--gov-text-2); }
</style>
