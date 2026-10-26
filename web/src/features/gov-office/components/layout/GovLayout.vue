<script setup lang="ts">
import { computed, onMounted } from "vue";
import "../../gov-office.css";
import GovSidebar from "./GovSidebar.vue";
import { useGovSessionStore } from "../../stores/govSession";
import { useGovDocumentsStore } from "../../stores/govDocuments";
import { useViewport } from "../../composables/useViewport";
import { useAuthStore } from "../../../../stores/auth.js";
import { useRouter } from "vue-router";
const auth = useAuthStore();
const router = useRouter();
function logout() { auth.clearSession(); router.push('/login'); }

/** Collapse the navigation automatically when the viewport is narrower than this. */
const props = withDefaults(defineProps<{ autoCollapseBelow?: number }>(), { autoCollapseBelow: 0 });

const session = useGovSessionStore();
const documents = useGovDocumentsStore();
const { width } = useViewport();

const collapsed = computed(() => session.navCollapsedPref ?? width.value < props.autoCollapseBelow);
// Badge = tasks waiting for the current reviewer (never their own documents).
const pendingCount = computed(() => {
  const actor = session.actor;
  if (!actor?.roles.includes("reviewer")) return 0;
  return documents.list.filter((d) => d.status === "pending" && d.authorAccount !== actor.account).length;
});

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
        :actor="session.actor"
        :demo-actors="session.isDemo ? session.demoActors : []"
        @toggle="session.setNavCollapsed(!collapsed)"
        @switch-actor="session.switchDemoActor"
      />
    </aside>
    <main class="gov-shell__main">
      <div v-if="!session.isDemo" class="gov-banner gov-banner--info" style="display:flex;gap:12px;align-items:center;padding:6px 16px;font-size:12px;flex-wrap:wrap">
        <span>{{ session.actor?.name || '读取真实身份中…' }} · 政策库已接入，自动审校尚未接入</span>
        <RouterLink to="/welcome">旧版功能入口</RouterLink>
        <button type="button" class="gov-btn gov-btn--text gov-btn--sm" @click="logout">退出登录</button>
      </div>
      <div v-if="session.error" class="gov-banner gov-banner--danger" role="alert">{{ session.error }}</div>
      <slot />
    </main>
  </div>
</template>

<style scoped>
.gov-shell { display: flex; width: 100%; height: 100vh; min-height: 640px; overflow: hidden; }
.gov-shell__nav { flex: 0 0 auto; height: 100%; }
.gov-shell__main { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
</style>
