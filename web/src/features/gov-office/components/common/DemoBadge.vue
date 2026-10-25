<script setup lang="ts">
import { useGovSessionStore } from "../../stores/govSession";

const session = useGovSessionStore();
</script>

<template>
  <span v-if="session.isDemo" class="gov-tag gov-tag--warning" title="当前数据来自前端演示适配器，不是后端处理结果">演示数据 · 未接入后端</span>
</template>
