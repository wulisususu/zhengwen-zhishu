<script setup lang="ts">
import type { PolicyStatus } from "../../types";

defineProps<{ label: string; status: PolicyStatus; selected: boolean }>();
const emit = defineEmits<{ (e: "open"): void }>();
</script>

<template>
  <button
    type="button"
    class="gov-cite"
    :class="[`gov-cite--${status}`, { 'is-selected': selected }]"
    :aria-label="`查看依据 ${label} 原文`"
    :aria-pressed="selected"
    @click="emit('open')"
  >
    {{ label }}
  </button>
</template>

<style scoped>
.gov-cite {
  display: inline-flex; align-items: center; height: 22px; padding: 0 6px; margin: 0 3px; vertical-align: 1px;
  border-radius: var(--gov-r-sm); border: 1px solid currentColor; background: var(--gov-surface);
  font-size: 12px; font-weight: 500; cursor: pointer; text-indent: 0;
}
.gov-cite--current { color: var(--gov-primary); }
.gov-cite--unverified { color: var(--gov-warn); }
.gov-cite--abolished { color: var(--gov-red); }
.gov-cite.is-selected { color: #fff; }
.gov-cite--current.is-selected { background: var(--gov-primary); border-color: var(--gov-primary); }
.gov-cite--unverified.is-selected { background: var(--gov-warn); border-color: var(--gov-warn); }
.gov-cite--abolished.is-selected { background: var(--gov-red); border-color: var(--gov-red); }
</style>
