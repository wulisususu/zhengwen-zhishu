import { onBeforeUnmount, onMounted, ref } from "vue";

/** Width breakpoints for the desktop targets: 1280×800, 1440×900, 1920×1080. */
export const COMPACT_BELOW = 1366;
export const WIDE_FROM = 1600;

export function useViewport() {
  const width = ref(typeof window === "undefined" ? 1440 : window.innerWidth);
  const update = () => {
    width.value = window.innerWidth;
  };
  onMounted(() => {
    update();
    window.addEventListener("resize", update);
  });
  onBeforeUnmount(() => window.removeEventListener("resize", update));
  return { width };
}
