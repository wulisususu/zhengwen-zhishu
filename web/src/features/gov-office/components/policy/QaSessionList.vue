<script setup lang="ts">
import { PanelLeftClose, Plus } from "lucide-vue-next";
import StatusTag from "../common/StatusTag.vue";
import type { QaSession } from "../../types";

defineProps<{ sessions: QaSession[]; activeId: string }>();
const emit = defineEmits<{ (e: "select", id: string): void; (e: "new"): void; (e: "collapse"): void }>();
</script>

<template>
  <section class="gov-sessions" aria-label="会话记录">
    <div class="gov-sessions__head">
      <h2 class="gov-subtitle" style="flex: 1 1 auto">会话记录</h2>
      <button type="button" class="gov-btn gov-btn--text gov-btn--icon" aria-label="收起会话记录" @click="emit('collapse')">
        <PanelLeftClose :size="18" aria-hidden="true" />
      </button>
    </div>
    <div class="gov-sessions__new">
      <button type="button" class="gov-btn gov-btn--outline" style="width: 100%" @click="emit('new')"><Plus :size="16" aria-hidden="true" />新建问答</button>
    </div>
    <div class="gov-sessions__list">
      <button
        v-for="s in sessions"
        :key="s.id"
        type="button"
        class="gov-sessions__item"
        :class="{ 'is-active': s.id === activeId }"
        :aria-current="s.id === activeId ? 'true' : undefined"
        @click="emit('select', s.id)"
      >
        <span class="gov-sessions__title">{{ s.title }}</span>
        <span class="gov-sessions__meta">
          <span class="gov-muted">{{ s.updatedAt }}</span>
          <StatusTag :tone="s.badge.tone" :label="s.badge.label" />
        </span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.gov-sessions { height: 100%; display: flex; flex-direction: column; min-height: 0; background: var(--gov-surface); }
.gov-sessions__head { display: flex; align-items: center; gap: 8px; padding: 12px 12px 8px 16px; }
.gov-sessions__new { padding: 0 16px 12px; border-bottom: 1px solid var(--gov-border); }
.gov-sessions__list { flex: 1 1 auto; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 4px; }
.gov-sessions__item {
  text-align: left; width: 100%; padding: 10px 12px; border-radius: var(--gov-r-md); border: 1px solid transparent;
  background: transparent; display: flex; flex-direction: column; gap: 4px; cursor: pointer;
}
.gov-sessions__item:hover { background: var(--gov-surface-2); }
.gov-sessions__item.is-active { background: var(--gov-primary-50); border-color: var(--gov-primary-100); }
.gov-sessions__title { font-size: 14px; font-weight: 500; line-height: 20px; color: var(--gov-text-1); }
.gov-sessions__meta { display: flex; align-items: center; gap: 8px; }
</style>
