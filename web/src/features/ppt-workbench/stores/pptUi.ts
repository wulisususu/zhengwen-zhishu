import { defineStore } from "pinia";
import { DEFAULT_PPT_PAGE_COUNT, normalizePageCount } from "../utils/pageCount";

export const usePptUiStore = defineStore("pptUi", {
  state: () => ({
    activeModal: null as "export" | "proposal" | null,
    draggingPanel: null as "chat" | "inspector" | null,
    hoveredSlideId: null as string | null,
    selectedElementId: null as string | null,
    selectedPageCount: DEFAULT_PPT_PAGE_COUNT,
    pageCountManuallySelected: false,
    structuredMode: "flat" as "flat" | "structured", // P3-A structured PPTX
    structuredWorkspaceId: null as string | null,
  }),
  actions: {
    openModal(modal: "export" | "proposal") { this.activeModal = modal; },
    closeModal() { this.activeModal = null; },
    setPageCount(value: unknown, manual = true) {
      this.selectedPageCount = normalizePageCount(value);
      if (manual) this.pageCountManuallySelected = true;
    },
    setStructuredMode(mode: "flat" | "structured", workspaceId: string | null = null) {
      this.structuredMode = mode;
      this.structuredWorkspaceId = mode === "structured" ? workspaceId : null;
    },
    syncPageCountFromPrompt(value: unknown) {
      if (!this.pageCountManuallySelected) this.selectedPageCount = normalizePageCount(value, this.selectedPageCount);
    },
  },
});
