<script setup lang="ts">
import { RouterLink } from "vue-router";
import StatusTag from "../common/StatusTag.vue";
import { POLICY_STATUS_LABELS, POLICY_STATUS_TONES } from "../../domain/docTypes";
import type { PolicyRef } from "../../types";

defineProps<{ refs: PolicyRef[] }>();
</script>

<template>
  <section class="gov-refs" aria-label="政策依据">
    <div class="gov-refs__head">
      <h2 class="gov-subtitle">政策依据</h2>
      <RouterLink to="/gov/policy-qa" class="gov-btn gov-btn--text gov-btn--sm">从政策问答添加</RouterLink>
    </div>
    <div v-for="p in refs" :key="p.id" class="gov-refs__item" :class="{ 'is-bad': p.status !== 'current' }">
      <span class="gov-refs__title">《{{ p.title }}》</span>
      <span class="gov-refs__tags">
        <StatusTag tone="outline" :label="p.clause" />
        <StatusTag :tone="POLICY_STATUS_TONES[p.status]" :label="POLICY_STATUS_LABELS[p.status]" />
      </span>
      <span v-if="p.status === 'abolished'" class="gov-muted">已废止，见右侧审校问题</span>
    </div>
    <div v-if="!refs.length" class="gov-empty">暂未选择政策依据</div>
  </section>
</template>

<style scoped>
.gov-refs { display: flex; flex-direction: column; gap: 8px; }
.gov-refs__head { display: flex; align-items: center; justify-content: space-between; }
.gov-refs__item { display: flex; flex-direction: column; gap: 6px; padding: 10px; border: 1px solid var(--gov-border); border-radius: var(--gov-r-md); }
.gov-refs__item.is-bad { border-color: var(--gov-red-200); background: #fffbfa; }
.gov-refs__title { font-size: 13px; font-weight: 500; line-height: 19px; }
.gov-refs__tags { display: flex; gap: 6px; flex-wrap: wrap; }
</style>
