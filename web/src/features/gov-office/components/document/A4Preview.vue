<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useAnchorScroll } from "../../composables/useAnchorScroll";

// A4 at 96 dpi. The page is laid out at true size and scaled as a whole, so
// proportions stay exact at every zoom. This is a visual approximation only:
// DOCX layout is guaranteed by the backend template, not by this preview.
const A4_WIDTH = 794;
const A4_HEIGHT = 1123;
const GUTTER = 48;

const props = withDefaults(defineProps<{ zoom: "fit" | number; watermark?: string; cornerNote?: string; maxFit?: number }>(), {
  watermark: "",
  cornerNote: "",
  maxFit: 1,
});

const desk = ref<HTMLElement | null>(null);
const page = ref<HTMLElement | null>(null);
const deskWidth = ref(A4_WIDTH + GUTTER);
const pageHeight = ref(A4_HEIGHT);
let observer: ResizeObserver | null = null;

const scale = computed(() => {
  if (props.zoom !== "fit") return props.zoom;
  return Math.max(0.3, Math.min(props.maxFit, (deskWidth.value - GUTTER) / A4_WIDTH));
});
const frameStyle = computed(() => ({ width: `${A4_WIDTH * scale.value}px`, height: `${pageHeight.value * scale.value}px` }));
const pageStyle = computed(() => ({ transform: `scale(${scale.value})` }));

onMounted(() => {
  observer = new ResizeObserver(() => {
    if (desk.value) deskWidth.value = desk.value.clientWidth;
    if (page.value) pageHeight.value = Math.max(A4_HEIGHT, page.value.offsetHeight);
  });
  if (desk.value) observer.observe(desk.value);
  if (page.value) observer.observe(page.value);
});
onBeforeUnmount(() => observer?.disconnect());

const { scrollToAnchor } = useAnchorScroll(desk);
defineExpose({ scrollToAnchor, scale });
</script>

<template>
  <div ref="desk" class="gov-a4-desk">
    <div class="gov-a4-frame" :style="frameStyle">
      <article ref="page" class="gov-a4-page" :style="pageStyle" aria-label="公文预览">
        <span v-if="cornerNote" class="gov-a4-corner">{{ cornerNote }}</span>
        <span v-if="watermark" class="gov-a4-watermark" aria-hidden="true">{{ watermark }}</span>
        <slot />
      </article>
    </div>
    <p class="gov-a4-caption">预览仅示意 A4 版式比例，正式 DOCX 版式以后端模板渲染为准。</p>
  </div>
</template>

<style scoped>
.gov-a4-desk {
  height: 100%;
  overflow: auto;
  background: var(--gov-desk);
  padding: 24px 24px 40px;
}
.gov-a4-frame { position: relative; margin: 0 auto; }
.gov-a4-page {
  position: absolute;
  top: 0;
  left: 0;
  width: 794px;
  min-height: 1123px;
  transform-origin: top left;
  background: #fff;
  box-shadow: var(--gov-sh-page);
  /* GB/T 9704-2012: 天头 37mm, 订口 28mm, 版心 156×225mm */
  padding: 140px 98px 132px 106px;
  font-family: var(--gov-font-doc-body);
  font-size: 21.33px;
  line-height: 1.8;
  color: #111;
  overflow: hidden;
}
.gov-a4-corner {
  position: absolute; top: 40px; right: 48px;
  font-family: var(--gov-font-ui); font-size: 14px; color: var(--gov-text-3);
}
.gov-a4-watermark {
  position: absolute; top: 46%; left: 50%; transform: translate(-50%, -50%) rotate(-24deg);
  font-family: var(--gov-font-ui); font-size: 96px; font-weight: 700; letter-spacing: 12px;
  color: rgba(180, 35, 24, 0.07); white-space: nowrap; pointer-events: none; user-select: none;
}
.gov-a4-caption { margin: 12px auto 0; text-align: center; font-size: 12px; color: var(--gov-text-3); }
</style>
