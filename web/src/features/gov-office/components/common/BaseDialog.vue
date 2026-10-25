<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";

const props = withDefaults(defineProps<{ title: string; width?: number }>(), { width: 480 });
const emit = defineEmits<{ (e: "close"): void }>();
const panel = ref<HTMLElement | null>(null);
let previouslyFocused: HTMLElement | null = null;

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") emit("close");
}

onMounted(async () => {
  previouslyFocused = document.activeElement as HTMLElement | null;
  await nextTick();
  const first = panel.value?.querySelector<HTMLElement>("textarea, input, select, button:not([data-dialog-close])");
  (first ?? panel.value)?.focus();
});

onBeforeUnmount(() => previouslyFocused?.focus?.());
</script>

<template>
  <Teleport to="body">
    <div class="gov-app gov-dialog" @keydown="onKeydown" @click.self="emit('close')">
      <section
        ref="panel"
        class="gov-dialog__panel"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        tabindex="-1"
        :style="{ width: `${props.width}px` }"
      >
        <header class="gov-dialog__header">
          <h2 class="gov-section-title">{{ title }}</h2>
        </header>
        <div class="gov-dialog__body">
          <slot />
        </div>
        <footer class="gov-dialog__footer">
          <slot name="footer">
            <button type="button" class="gov-btn" data-dialog-close @click="emit('close')">关闭</button>
          </slot>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.gov-dialog {
  position: fixed; inset: 0; z-index: 1000; background: rgba(16, 36, 63, 0.45);
  display: flex; align-items: center; justify-content: center; padding: 24px;
}
.gov-dialog__panel {
  max-width: 100%; max-height: 100%; display: flex; flex-direction: column;
  background: var(--gov-surface); border-radius: var(--gov-r-lg); box-shadow: var(--gov-sh-3); outline: none;
}
.gov-dialog__header { padding: 16px 20px; border-bottom: 1px solid var(--gov-border); }
.gov-dialog__body { padding: 16px 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; font-size: var(--gov-fs-sm); line-height: 21px; color: var(--gov-text-2); }
.gov-dialog__footer { padding: 12px 20px; border-top: 1px solid var(--gov-border); display: flex; justify-content: flex-end; gap: 8px; }
</style>
