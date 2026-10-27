<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { FilePen, ShieldCheck } from "lucide-vue-next";
import "../gov-office.css";
import { useAuthStore } from "../../../stores/auth.js";
import { currentEntryRole, enterRole, fetchEntryOptions, ROLE_HOME, ROLE_LABEL, type EntryOptions, type EntryRole } from "../roleEntry";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const options = ref<EntryOptions | null>(null);
const loadError = ref("");
const error = ref("");
const entering = ref<EntryRole | null>(null);
const current = ref(currentEntryRole());
const expired = computed(() => route.query.expired === "1");

const ICONS = { drafter: FilePen, reviewer: ShieldCheck } as const;
const CUE = { drafter: "进入起草流程", reviewer: "进入审核流程" } as const;

onMounted(async () => {
  try {
    options.value = await fetchEntryOptions();
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : "读取角色入口失败";
  }
});

async function choose(role: EntryRole) {
  if (entering.value) return;
  entering.value = role;
  error.value = "";
  try {
    auth.setSession(await enterRole(role));
    await router.replace(ROLE_HOME[role]);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "进入失败，请重试";
  } finally {
    entering.value = null;
  }
}
</script>

<template>
  <div class="gov-app role-entry">
    <main class="role-entry__panel" aria-labelledby="role-entry-title">
      <header class="role-entry__head">
        <span class="role-entry__mark" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="M8 13h8" /><path d="M8 17h5" />
          </svg>
        </span>
        <div>
          <h1 id="role-entry-title" class="role-entry__title">政文智枢</h1>
          <p class="role-entry__subtitle">请选择本次使用的角色</p>
        </div>
      </header>

      <p v-if="expired" class="gov-banner gov-banner--warning" role="status">会话已失效，请重新选择角色。</p>
      <p v-if="loadError" class="gov-banner gov-banner--danger" role="alert">{{ loadError }}</p>
      <p v-else-if="options && !options.enabled" class="gov-banner gov-banner--warning" role="status">角色入口未开启，请联系系统维护人员。</p>
      <p v-if="error" class="gov-banner gov-banner--danger" role="alert">{{ error }}</p>

      <div class="role-entry__choices">
        <button
          v-for="opt in options?.roles ?? []"
          :key="opt.role"
          type="button"
          class="role-entry__choice"
          :class="`role-entry__choice--${opt.role}`"
          :data-role="opt.role"
          :disabled="!options?.enabled || !!entering"
          :aria-busy="entering === opt.role"
          @click="choose(opt.role)"
        >
          <span class="role-entry__icon" aria-hidden="true"><component :is="ICONS[opt.role]" :size="22" /></span>
          <span class="role-entry__label">{{ opt.label }}</span>
          <span class="role-entry__desc">{{ opt.description }}</span>
          <span class="role-entry__cue">{{ entering === opt.role ? "进入中…" : CUE[opt.role] + " →" }}</span>
        </button>
      </div>

      <p v-if="current" class="role-entry__current">当前角色为「{{ ROLE_LABEL[current] }}」，重新选择将切换角色。</p>

      <section class="role-entry__note" aria-label="使用说明">
        <p>本系统不设登录。角色只用于区分起草与审核的业务权限，不是身份认证。</p>
        <p>选择同一角色的使用者共用该角色的文稿；审核人只能审核他人送审的文稿，不能起草。</p>
      </section>
    </main>
  </div>
</template>

<style scoped>
.role-entry {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  box-sizing: border-box;
}
.role-entry__panel {
  width: 100%;
  max-width: 760px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.role-entry__head {
  display: flex;
  align-items: center;
  gap: 14px;
}
.role-entry__mark {
  width: 44px;
  height: 44px;
  border-radius: var(--gov-r-lg);
  background: var(--gov-navy);
  display: grid;
  place-items: center;
  flex: none;
}
.role-entry__title {
  margin: 0;
  font-size: var(--gov-fs-display);
  line-height: 1.2;
  color: var(--gov-text-1);
}
.role-entry__subtitle {
  margin: 4px 0 0;
  color: var(--gov-text-3);
}
.role-entry__choices {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.role-entry__choice {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 24px;
  text-align: left;
  font: inherit;
  color: inherit;
  background: var(--gov-surface);
  border: 1px solid var(--gov-border);
  border-radius: var(--gov-r-lg);
  box-shadow: var(--gov-sh-1);
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.role-entry__choice:hover:not(:disabled) {
  border-color: var(--gov-primary);
  box-shadow: var(--gov-sh-page);
}
.role-entry__choice:focus-visible {
  outline: 2px solid var(--gov-primary);
  outline-offset: 2px;
}
.role-entry__choice:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.role-entry__icon {
  width: 44px;
  height: 44px;
  border-radius: var(--gov-r-md);
  display: grid;
  place-items: center;
  color: var(--gov-primary);
  background: var(--gov-primary-50);
}
.role-entry__choice--reviewer .role-entry__icon {
  color: var(--gov-ok);
  background: var(--gov-ok-50);
}
.role-entry__label {
  font-size: 20px;
  font-weight: 600;
  color: var(--gov-text-1);
}
.role-entry__desc {
  color: var(--gov-text-2);
  line-height: 1.6;
  flex: 1;
}
.role-entry__cue {
  margin-top: 4px;
  color: var(--gov-primary);
  font-weight: 600;
}
.role-entry__current {
  margin: 0;
  color: var(--gov-text-2);
  font-size: var(--gov-fs-sm);
}
.role-entry__note {
  padding: 12px 16px;
  border-radius: var(--gov-r-md);
  background: var(--gov-surface-2);
  border: 1px solid var(--gov-border);
  color: var(--gov-text-3);
  font-size: var(--gov-fs-sm);
  line-height: 1.7;
}
.role-entry__note p {
  margin: 0;
}
@media (max-width: 640px) {
  .role-entry__choices {
    grid-template-columns: 1fr;
  }
}
</style>
