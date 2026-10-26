<script setup lang="ts">
import GovLayout from '../components/layout/GovLayout.vue';
import GovPageHeader from '../components/layout/GovPageHeader.vue';
import PolicyLibraryPanel from '../components/policy/PolicyLibraryPanel.vue';
</script>

<template>
  <GovLayout :auto-collapse-below="900">
    <GovPageHeader title="政策库" subtitle="检索政策文件、查看原文条款，管理来源、版本与人工核验状态" />
    <PolicyLibraryPanel />
  </GovLayout>
</template>
