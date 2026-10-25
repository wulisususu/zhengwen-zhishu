<script setup lang="ts">
import { FileText, Plus, X } from "lucide-vue-next";
import type { Material } from "../../types";

defineProps<{ materials: Material[]; editable: boolean }>();
const emit = defineEmits<{ (e: "add"): void; (e: "remove", id: string): void }>();
</script>

<template>
  <section class="gov-materials" aria-label="材料">
    <div class="gov-materials__head">
      <h2 class="gov-subtitle">材料 <span class="gov-muted">{{ materials.length }}</span></h2>
      <button type="button" class="gov-btn gov-btn--text gov-btn--sm" :disabled="!editable" @click="emit('add')">
        <Plus :size="14" aria-hidden="true" />添加材料
      </button>
    </div>
    <div v-for="m in materials" :key="m.id" class="gov-materials__item">
      <FileText :size="16" class="gov-materials__icon" aria-hidden="true" />
      <div class="gov-materials__text">
        <span class="gov-materials__name">{{ m.name }}</span>
        <span class="gov-muted">{{ m.meta }}</span>
      </div>
      <button
        type="button"
        class="gov-btn gov-btn--text gov-btn--icon gov-btn--sm"
        :aria-label="`移除材料 ${m.name}`"
        :disabled="!editable"
        @click="emit('remove', m.id)"
      >
        <X :size="14" aria-hidden="true" />
      </button>
    </div>
    <div v-if="!materials.length" class="gov-empty">暂无材料。无材料时，正文中的事实性内容将标记为待补充。</div>
  </section>
</template>

<style scoped>
.gov-materials { display: flex; flex-direction: column; gap: 8px; }
.gov-materials__head { display: flex; align-items: center; justify-content: space-between; }
.gov-materials__item { display: flex; gap: 8px; align-items: flex-start; padding: 10px; border: 1px solid var(--gov-border); border-radius: var(--gov-r-md); }
.gov-materials__icon { flex: 0 0 16px; margin-top: 2px; color: var(--gov-text-3); }
.gov-materials__text { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1 1 auto; }
.gov-materials__name { font-size: 13px; font-weight: 500; line-height: 18px; word-break: break-all; }
</style>
