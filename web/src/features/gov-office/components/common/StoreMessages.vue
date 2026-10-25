<script setup lang="ts">
import { X } from "lucide-vue-next";
import { useGovDocumentsStore } from "../../stores/govDocuments";

const store = useGovDocumentsStore();
</script>

<template>
  <div v-if="store.error || store.notice" class="gov-messages">
    <div v-if="store.error" class="gov-banner gov-banner--danger" role="alert">
      <span style="flex: 1 1 auto">{{ store.error }}</span>
      <button type="button" class="gov-btn gov-btn--text gov-btn--icon gov-btn--sm" aria-label="关闭提示" @click="store.clearMessages()"><X :size="16" aria-hidden="true" /></button>
    </div>
    <div v-else class="gov-banner gov-banner--info" role="status">
      <span style="flex: 1 1 auto">{{ store.notice }}<template v-if="store.list.some((d) => d.origin === 'demo')">（演示环境，仅保存在本页内存中）</template></span>
      <button type="button" class="gov-btn gov-btn--text gov-btn--icon gov-btn--sm" aria-label="关闭提示" @click="store.clearMessages()"><X :size="16" aria-hidden="true" /></button>
    </div>
  </div>
</template>

<style scoped>
.gov-messages { flex: 0 0 auto; padding: 8px 24px 0; }
.gov-messages .gov-banner { align-items: center; padding-top: 4px; padding-bottom: 4px; }
</style>
