<script setup lang="ts">
import { Search } from "lucide-vue-next";
import { DOC_TYPES, STATUS_LABELS } from "../../domain/docTypes";
import type { DocStatus, DocumentFilter } from "../../types";

const props = defineProps<{ modelValue: DocumentFilter; counts: Record<DocStatus | "all", number>; statuses: (DocStatus | "all")[]; resultCount: number }>();
const emit = defineEmits<{ (e: "update:modelValue", value: DocumentFilter): void }>();

function patch(change: Partial<DocumentFilter>) {
  emit("update:modelValue", { ...props.modelValue, ...change });
}
function statusLabel(s: DocStatus | "all") {
  return s === "all" ? "全部" : STATUS_LABELS[s];
}
</script>

<template>
  <div class="gov-filter">
    <label class="gov-filter__search">
      <span class="gov-visually-hidden">搜索文稿名称或创建人</span>
      <Search :size="16" class="gov-filter__icon" aria-hidden="true" />
      <input
        class="gov-input"
        type="search"
        placeholder="搜索文稿名称或创建人"
        :value="modelValue.keyword"
        @input="patch({ keyword: ($event.target as HTMLInputElement).value })"
      />
    </label>
    <label>
      <span class="gov-visually-hidden">文种筛选</span>
      <select class="gov-select" :value="modelValue.docType" @change="patch({ docType: ($event.target as HTMLSelectElement).value as DocumentFilter['docType'] })">
        <option value="all">全部文种</option>
        <option v-for="t in DOC_TYPES" :key="t.id" :value="t.id">{{ t.label }}</option>
      </select>
    </label>
    <div class="gov-filter__chips" role="group" aria-label="状态筛选">
      <button
        v-for="s in statuses"
        :key="s"
        type="button"
        class="gov-filter__chip"
        :class="{ 'is-active': modelValue.status === s }"
        :aria-pressed="modelValue.status === s"
        @click="patch({ status: s })"
      >
        {{ statusLabel(s) }} {{ counts[s] }}
      </button>
    </div>
    <label class="gov-filter__check">
      <input type="checkbox" :checked="modelValue.criticalOnly" @change="patch({ criticalOnly: ($event.target as HTMLInputElement).checked })" />
      仅看含严重问题
    </label>
    <span class="gov-filter__count">共 {{ resultCount }} 份</span>
  </div>
</template>

<style scoped>
.gov-filter { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; padding: 12px 24px; background: var(--gov-surface); border-bottom: 1px solid var(--gov-border); }
.gov-filter__search { position: relative; flex: 0 1 260px; min-width: 180px; }
.gov-filter__search .gov-input { padding-left: 32px; }
.gov-filter__icon { position: absolute; left: 10px; top: 9px; color: var(--gov-text-3); }
.gov-filter__chips { display: flex; gap: 4px; flex-wrap: wrap; }
.gov-filter__chip {
  height: 30px; padding: 0 10px; border-radius: 15px; border: 1px solid var(--gov-border-strong);
  background: var(--gov-surface); color: var(--gov-text-2); font-size: 12px; white-space: nowrap; cursor: pointer;
}
.gov-filter__chip.is-active { border-color: var(--gov-primary); background: var(--gov-primary); color: #fff; }
.gov-filter__check { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--gov-text-2); white-space: nowrap; }
.gov-filter__count { margin-left: auto; font-size: 13px; color: var(--gov-text-3); white-space: nowrap; }
</style>
