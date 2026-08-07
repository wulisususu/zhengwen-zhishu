<script setup lang="ts">
import { computed, onBeforeUnmount } from "vue";
import WorkbenchShell from "../components/shell/WorkbenchShell.vue";
import { MockPptWorkflowAdapter } from "../adapters/MockPptWorkflowAdapter";
import type { PptWorkflowAdapter } from "../adapters/PptWorkflowAdapter";
import { usePptWorkflow } from "../composables/usePptWorkflow";

const props = defineProps<{ projectId?: string; adapter?: PptWorkflowAdapter }>();
const projectId = computed(() => props.projectId ?? "local-demo-project");
const adapter: PptWorkflowAdapter = props.adapter ?? new MockPptWorkflowAdapter();
const workflow = usePptWorkflow(adapter);

onBeforeUnmount(() => adapter.dispose?.());
</script>

<template><WorkbenchShell :project-id="projectId" :workflow="workflow" class="h-full min-h-0" /></template>


