<script setup lang="ts">
import DemoBadge from "../common/DemoBadge.vue";

defineProps<{ title: string; subtitle?: string; crumb?: string }>();
</script>

<template>
  <header class="gov-header">
    <div class="gov-header__titles">
      <span v-if="crumb" class="gov-header__crumb">{{ crumb }}</span>
      <div class="gov-header__title-row">
        <h1 class="gov-header__title">{{ title }}</h1>
        <slot name="meta" />
      </div>
      <span v-if="subtitle" class="gov-header__subtitle">{{ subtitle }}</span>
    </div>
    <div class="gov-header__actions">
      <DemoBadge />
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.gov-header {
  flex: 0 0 auto;
  min-height: 60px;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 24px;
  background: var(--gov-surface);
  border-bottom: 1px solid var(--gov-border);
}
.gov-header__titles { display: flex; flex-direction: column; min-width: 0; flex: 1 1 auto; }
.gov-header__crumb { font-size: var(--gov-fs-xs); color: var(--gov-text-3); }
.gov-header__title-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.gov-header__title {
  margin: 0; font-size: var(--gov-fs-h1); font-weight: 700; line-height: 26px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0;
}
.gov-header__subtitle { font-size: var(--gov-fs-xs); color: var(--gov-text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.gov-header__actions { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
</style>
