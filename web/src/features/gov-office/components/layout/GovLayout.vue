<script setup lang="ts">
import { computed, onMounted } from "vue";
import "../../gov-office.css";
import GovSidebar from "./GovSidebar.vue";
import { useGovSessionStore } from "../../stores/govSession";
import { useGovDocumentsStore } from "../../stores/govDocuments";
import { useViewport } from "../../composables/useViewport";

/** Collapse the navigation automatically when the viewport is narrower than this. */
const props = withDefaults(defineProps<{ autoCollapseBelow?: number }>(), { autoCollapseBelow: 0 });

const session = useGovSessionStore();
const documents = useGovDocumentsStore();
const { width } = useViewport();

const collapsed = computed(() => session.navCollapsedPref ?? width.value < props.autoCollapseBelow);
const pendingCount = computed(() => documents.list.filter((d) => d.status === "pending").length);

onMounted(() => {
  session.load();
  if (!documents.order.length) documents.loadList();
});
</script>

<template>
  <div class="gov-app gov-shell">
    <aside class="gov-shell__nav">
      <GovSidebar
        :collapsed="collapsed"
        :runtime="session.runtime"
        :pending-count="pendingCount"
        @toggle="session.setNavCollapsed(!collapsed)"
      />
    </aside>
    <main class="gov-shell__main">
      <slot />
    </main>
  </div>
</template>

<style scoped>
.gov-shell { display: flex; width: 100%; height: 100vh; min-height: 640px; overflow: hidden; }
.gov-shell__nav { flex: 0 0 auto; height: 100%; }
.gov-shell__main { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
</style>
