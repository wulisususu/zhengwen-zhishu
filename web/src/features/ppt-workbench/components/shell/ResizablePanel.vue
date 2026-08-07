<script setup lang="ts">
const props = withDefaults(defineProps<{
  width: number;
  min?: number;
  max?: number;
  side?: "right" | "left";
  label: string;
}>(), { min: 280, max: 640, side: "right" });

const emit = defineEmits<{
  "update:width": [width: number];
  "resize-start": [];
  "resize-end": [];
}>();

const clamp = (width: number) => Math.max(props.min, Math.min(props.max, width));

function beginResize(event: PointerEvent) {
  const startX = event.clientX;
  const startWidth = props.width;
  const direction = props.side === "right" ? 1 : -1;
  emit("resize-start");
  const onMove = (moveEvent: PointerEvent) => emit("update:width", clamp(startWidth + (moveEvent.clientX - startX) * direction));
  const onEnd = () => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onEnd);
    emit("resize-end");
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onEnd, { once: true });
}

function resizeByKeyboard(event: KeyboardEvent) {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  const direction = event.key === "ArrowRight" ? 1 : -1;
  const sideDirection = props.side === "right" ? direction : -direction;
  emit("update:width", clamp(props.width + sideDirection * 8));
}
</script>

<template>
  <div class="relative h-full min-w-0 shrink-0 overflow-hidden" :style="{ width: `${width}px` }">
    <slot />
    <div
      role="separator"
      tabindex="0"
      aria-orientation="vertical"
      :aria-label="label"
      :aria-valuenow="width"
      :aria-valuemin="min"
      :aria-valuemax="max"
      class="absolute top-0 z-20 h-full w-1 cursor-col-resize bg-transparent transition hover:bg-blue-400 focus:bg-blue-500 focus:outline-none"
      :class="side === 'right' ? 'right-0' : 'left-0'"
      @pointerdown.prevent="beginResize"
      @keydown="resizeByKeyboard"
    />
  </div>
</template>
