<script setup lang="ts">
import { computed, ref } from "vue";
import BaseDialog from "./BaseDialog.vue";

const props = defineProps<{ title: string; description: string; confirmLabel: string; actorName: string; placeholder?: string }>();
const emit = defineEmits<{ (e: "close"): void; (e: "confirm", reason: string): void }>();

const reason = ref("");
const touched = ref(false);
const missing = computed(() => !reason.value.trim());

function confirm() {
  touched.value = true;
  if (missing.value) return;
  emit("confirm", reason.value.trim());
}
</script>

<template>
  <BaseDialog :title="props.title" @close="emit('close')">
    <p style="margin: 0">{{ props.description }}</p>
    <label class="gov-label">
      处理理由（必填）
      <textarea
        v-model="reason"
        class="gov-textarea"
        rows="3"
        :placeholder="props.placeholder ?? '请写明依据或例外原因，将记入审核记录'"
        :aria-invalid="touched && missing"
      />
    </label>
    <span v-if="touched && missing" role="alert" style="color: var(--gov-red); font-size: 12px">请填写处理理由。</span>
    <span class="gov-muted">记录人：{{ props.actorName }}</span>
    <template #footer>
      <button type="button" class="gov-btn" data-dialog-close @click="emit('close')">取消</button>
      <button type="button" class="gov-btn gov-btn--primary" @click="confirm">{{ props.confirmLabel }}</button>
    </template>
  </BaseDialog>
</template>
