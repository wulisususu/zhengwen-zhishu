<script setup lang="ts">
import { ref } from 'vue';
import { Upload } from 'lucide-vue-next';
import GovLayout from '../components/layout/GovLayout.vue';
import GovPageHeader from '../components/layout/GovPageHeader.vue';
import PolicyLibraryPanel from '../components/policy/PolicyLibraryPanel.vue';

const panel = ref<InstanceType<typeof PolicyLibraryPanel> | null>(null);
const canImport = ref(false);
</script>

<template>
  <GovLayout :auto-collapse-below="900">
    <GovPageHeader title="政策库" subtitle="检索政策文件、查看原文条款，管理来源、版本与人工核验状态">
      <template v-if="canImport" #actions>
        <span class="gov-muted policy-page__hint">导入后为待核实，核验后才可作为现行依据</span>
        <button type="button" class="gov-btn gov-btn--primary policy-page__import" @click="panel?.openImport()"><Upload :size="16" aria-hidden="true" />导入政策</button>
      </template>
    </GovPageHeader>
    <PolicyLibraryPanel ref="panel" @import-available="canImport = $event" />
  </GovLayout>
</template>

<style scoped>
.policy-page__hint { font-size: var(--gov-fs-xs); }
.policy-page__import { height: 38px; padding: 0 16px; font-weight: 600; }
@media (max-width: 1100px) { .policy-page__hint { display: none; } }
</style>
