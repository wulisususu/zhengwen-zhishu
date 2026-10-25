import { nextTick, type Ref } from "vue";

/**
 * Scrolls an element marked with data-anchor="<id>" into view inside its own
 * scroll container, without moving the page or other panels.
 */
export function useAnchorScroll(container: Ref<HTMLElement | null>, offset = 96) {
  async function scrollToAnchor(anchor: string) {
    await nextTick();
    const box = container.value;
    if (!box) return;
    const el = box.querySelector<HTMLElement>(`[data-anchor="${CSS.escape(anchor)}"]`);
    if (!el) return;
    const top = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - offset;
    box.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
  }
  return { scrollToAnchor };
}
