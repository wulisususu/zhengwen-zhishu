<script setup lang="ts">
import { computed } from "vue";
import type { ReviewRecord } from "../../types";

const props = defineProps<{ records: ReviewRecord[] }>();
const ordered = computed(() => [...props.records].reverse());
const DOT: Record<ReviewRecord["tone"], string> = {
  neutral: "#8fa0b8",
  info: "#1f4e8c",
  success: "#146c43",
  warning: "#93470a",
  danger: "#b42318",
};
</script>

<template>
  <ol class="gov-timeline">
    <li v-for="r in ordered" :key="r.id" class="gov-timeline__item">
      <span class="gov-timeline__rail" aria-hidden="true">
        <span class="gov-timeline__dot" :style="{ background: DOT[r.tone] }" />
        <span class="gov-timeline__line" />
      </span>
      <div class="gov-timeline__body">
        <span class="gov-timeline__action">{{ r.action }}<span class="gov-timeline__actor"> · {{ r.actor }}</span></span>
        <span class="gov-muted">{{ r.at }}</span>
        <span v-if="r.note" class="gov-timeline__note">{{ r.note }}</span>
      </div>
    </li>
    <li v-if="!ordered.length" class="gov-empty">暂无记录</li>
  </ol>
</template>

<style scoped>
.gov-timeline { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.gov-timeline__item { display: flex; gap: 12px; }
.gov-timeline__rail { display: flex; flex-direction: column; align-items: center; flex: 0 0 12px; }
.gov-timeline__dot { width: 10px; height: 10px; border-radius: 5px; margin-top: 5px; flex: 0 0 10px; }
.gov-timeline__line { flex: 1 1 auto; width: 1px; min-height: 16px; background: var(--gov-border); }
.gov-timeline__body { display: flex; flex-direction: column; gap: 2px; padding-bottom: 16px; min-width: 0; }
.gov-timeline__action { font-size: 13px; font-weight: 500; }
.gov-timeline__actor { font-weight: 400; color: var(--gov-text-3); }
.gov-timeline__note {
  font-size: 13px; line-height: 20px; color: var(--gov-text-2); padding: 6px 10px;
  border-radius: var(--gov-r-sm); background: var(--gov-surface-2); border: 1px solid var(--gov-border);
}
</style>
