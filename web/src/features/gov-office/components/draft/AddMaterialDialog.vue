<script setup lang="ts">
import { computed, ref } from "vue";
import BaseDialog from "../common/BaseDialog.vue";
import type { Material } from "../../types";

const props = defineProps<{ library: Material[]; existingIds: string[] }>();
const emit = defineEmits<{ (e: "close"): void; (e: "confirm", ids: string[]): void }>();

const picked = ref<string[]>([]);
const available = computed(() => props.library.filter((m) => !props.existingIds.includes(m.id)));
</script>

<template>
  <BaseDialog title="添加材料" :width="520" @close="emit('close')">
    <span class="gov-tag gov-tag--warning" style="align-self: flex-start">演示材料库 · 不读取本机文件</span>
    <label v-for="m in available" :key="m.id" class="gov-pick">
      <input v-model="picked" type="checkbox" :value="m.id" />
      <span class="gov-pick__text">
        <span class="gov-pick__name">{{ m.name }}</span>
        <span class="gov-muted">{{ m.meta }}</span>
      </span>
    </label>
    <div v-if="!available.length" class="gov-empty">材料库中的文件均已添加。</div>
    <template #footer>
      <button type="button" class="gov-btn" data-dialog-close @click="emit('close')">取消</button>
      <button type="button" class="gov-btn gov-btn--primary" :disabled="!picked.length" @click="emit('confirm', picked)">添加所选（{{ picked.length }}）</button>
    </template>
  </BaseDialog>
</template>

<style scoped>
.gov-pick { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--gov-border); border-radius: var(--gov-r-md); cursor: pointer; }
.gov-pick input { width: 16px; height: 16px; margin: 0; }
.gov-pick__text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.gov-pick__name { font-size: 13px; font-weight: 500; color: var(--gov-text-1); }
</style>
