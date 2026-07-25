import { defineStore } from "pinia";
import { useAnimationStore } from "./animationStore";

export type EditorDocument = {
  project_id: string;
  base_task_id: string;
  slides: Array<{ slide_id: string; order: number; width: number; height: number; elements: Array<Record<string, any>>; pptx_structure?: Record<string, any> | null }>;
};

type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));
let saveTimer: number | undefined;
let saveInFlight: Promise<void> | null = null;

export const usePptEditorStore = defineStore("ppt-editor", {
  state: () => ({
    projectId: "", document: null as EditorDocument | null, revision: 0, originalFileId: 0,
    selectedSlideId: "", selectedElementIds: [] as string[], undoStack: [] as EditorDocument[], redoStack: [] as EditorDocument[], animationUndoStack: [] as any[], animationRedoStack: [] as any[],
    loadEpoch: 0, saveSequence: 0, changeSequence: 0, savingState: "idle" as "idle" | "loading" | "dirty" | "saving" | "saved" | "failed" | "conflict", error: "", conflict: false,
    exportState: "idle" as "idle" | "saving" | "exporting" | "ready" | "failed", exportError: "", lastExport: null as { export_id: string; file_id: number; download_url: string; revision: number } | null,
  }),
  actions: {
    snapshot() { if (this.document) { const animations = useAnimationStore(); this.undoStack.push(clone(this.document)); this.animationUndoStack.push(clone(animations.manifest)); this.redoStack = []; this.animationRedoStack = []; } },
    async load(projectId: string, fetchImpl: Fetch = fetch) {
      const epoch = ++this.loadEpoch;
      this.projectId = projectId; this.document = null; this.revision = 0; this.changeSequence = 0; this.selectedSlideId = ""; this.selectedElementIds = []; this.undoStack = []; this.redoStack = []; this.animationUndoStack = []; this.animationRedoStack = []; this.error = ""; this.conflict = false; this.exportState = "idle"; this.exportError = ""; this.lastExport = null; this.savingState = "loading";
      let response: Response; let payload: any;
      try { response = await fetchImpl(`/api/v1/ppt-master/projects/${encodeURIComponent(projectId)}/editor`); payload = await response.json(); }
      catch { if (epoch === this.loadEpoch) { this.error = "加载编辑草稿失败"; this.savingState = "failed"; } return; }
      if (epoch !== this.loadEpoch || projectId !== this.projectId) return;
      if (!response.ok) { this.error = response.status === 404 ? "当前 PPT 不支持在线编辑" : "加载编辑草稿失败"; this.savingState = "failed"; return; }
      this.document = payload.data.document; this.revision = payload.data.revision; this.originalFileId = payload.data.original_file_id; this.selectedSlideId = this.document?.slides[0]?.slide_id ?? ""; this.savingState = "idle";
    },
    addImage(asset: { asset_id: string; file_id: number; width: number; height: number; download_url?: string }) {
      const slide = this.document?.slides.find((item) => item.slide_id === this.selectedSlideId) ?? this.document?.slides[0];
      if (!slide || !asset.asset_id.startsWith("pptimg_")) return;
      this.snapshot();
      const aspect = Math.max(0.1, Number(asset.width) / Math.max(1, Number(asset.height)));
      const width = Math.min(420, Math.max(120, 280 * aspect)); const height = width / aspect;
      slide.elements.push({
        id: `local:${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`,
        type: "image", asset_id: asset.asset_id, file_id: asset.file_id,
        x: Math.round((1280 - width) / 2), y: Math.round((720 - height) / 2), width, height,
        rotation: 0, z_index: slide.elements.length + 1, locked: false, fit: "cover",
        crop: { left: 0, top: 0, right: 0, bottom: 0 }, style: {}, content: { download_url: asset.download_url ?? "" },
      });
      this.changeSequence += 1; this.savingState = "dirty";
    },
    setImageFit(elementId: string, fit: "cover" | "contain") {
      const element = this.document?.slides.flatMap((slide) => slide.elements).find((item) => item.id === elementId);
      if (!element || element.type !== "image" || element.locked) return;
      this.snapshot(); element.fit = fit; this.changeSequence += 1; this.savingState = "dirty";
    },
    cropImage(elementId: string, inset = 0.05) {
      const element = this.document?.slides.flatMap((slide) => slide.elements).find((item) => item.id === elementId);
      if (!element || element.type !== "image" || element.locked) return;
      const crop = element.crop ?? { left: 0, top: 0, right: 0, bottom: 0 };
      const next = Math.min(0.45, Math.max(0, inset));
      this.snapshot(); element.crop = { left: next, top: next, right: next, bottom: next }; this.changeSequence += 1; this.savingState = "dirty";
    },
    replaceImage(elementId: string, asset: { asset_id: string; file_id: number; download_url?: string }) {
      const element = this.document?.slides.flatMap((slide) => slide.elements).find((item) => item.id === elementId);
      if (!element || element.type !== "image" || element.locked || !asset.asset_id.startsWith("pptimg_")) return;
      this.snapshot(); element.asset_id = asset.asset_id; element.file_id = asset.file_id; element.content = { ...element.content, download_url: asset.download_url ?? "" };
      this.changeSequence += 1; this.savingState = "dirty";
    },
    addChart(chartType: "column" | "bar" | "line" | "pie" = "column", importedContent?: Record<string, any>) {
      const slide = this.document?.slides.find((item) => item.slide_id === this.selectedSlideId) ?? this.document?.slides[0]; if (!slide) return;
      this.snapshot(); slide.elements.push({ id: `local:${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`, type: "chart", x: 300, y: 180, width: 480, height: 280, rotation: 0, z_index: slide.elements.length + 1, locked: false, content: importedContent ? clone(importedContent) : { chart_type: chartType, title: "数据图表", categories: ["类别 A", "类别 B", "类别 C"], series: [{ name: "系列 1", values: [12, 24, 18] }], source_refs: [] } }); this.changeSequence += 1; this.savingState = "dirty";
    },
    addTable(importedContent?: Record<string, any>) {
      const slide = this.document?.slides.find((item) => item.slide_id === this.selectedSlideId) ?? this.document?.slides[0]; if (!slide) return;
      this.snapshot(); slide.elements.push({ id: `local:${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`, type: "table", x: 300, y: 220, width: 480, height: 190, rotation: 0, z_index: slide.elements.length + 1, locked: false, content: importedContent ? clone(importedContent) : { columns: ["项目", "数值"], rows: [["收入", "120"], ["成本", "80"]], source_refs: [] } }); this.changeSequence += 1; this.savingState = "dirty";
    },
    updateNative(elementId: string, content: Record<string, any>) {
      const element = this.document?.slides.flatMap((slide) => slide.elements).find((item) => item.id === elementId); if (!element || element.locked || !["chart", "table"].includes(element.type)) return;
      this.snapshot(); element.content = clone(content); this.changeSequence += 1; this.savingState = "dirty";
    },
    setText(elementId: string, text: string) {
      if (!this.document) return;
      this.snapshot();
      for (const slide of this.document.slides) for (const element of slide.elements) if (element.id === elementId && element.type === "text" && !element.locked) element.content = { ...element.content, text };
      this.changeSequence += 1; this.savingState = "dirty";
    },
    moveElement(elementId: string, x: number, y: number) {
      if (!this.document) return;
      const element = this.document.slides.flatMap((slide) => slide.elements).find((item) => item.id === elementId);
      if (!element || element.locked) return;
      this.snapshot(); element.x = Math.max(0, Math.min(1280 - Math.max(0, Number(element.width) || 0), x)); element.y = Math.max(0, Math.min(720 - Math.max(0, Number(element.height) || 0), y)); this.changeSequence += 1; this.savingState = "dirty";
    },
    resizeElement(elementId: string, x: number, y: number, width: number, height: number) {
      if (!this.document) return;
      const element = this.document.slides.flatMap((slide) => slide.elements).find((item) => item.id === elementId);
      if (!element || element.locked) return;
      this.snapshot(); const min = element.type === "line" ? 0 : 12;
      if (width < min) { x += width - min; width = min; } if (height < min) { y += height - min; height = min; }
      element.x = Math.max(0, Math.min(1280 - min, x)); element.y = Math.max(0, Math.min(720 - min, y)); element.width = Math.max(min, Math.min(1280 - element.x, width)); element.height = Math.max(min, Math.min(720 - element.y, height)); this.changeSequence += 1; this.savingState = "dirty";
    },
    deleteSelected() { if (!this.document) return; for (const slide of this.document.slides) { const removable = slide.elements.some((item) => this.selectedElementIds.includes(item.id) && !item.locked); if (removable) { this.snapshot(); slide.elements = slide.elements.filter((item) => !this.selectedElementIds.includes(item.id) || item.locked); } } this.selectedElementIds = []; const animationStore = useAnimationStore(); animationStore.cleanupOrphaned(this.document.slides.flatMap((slide) => slide.elements.map((element) => element.id))); void animationStore.save().catch(() => undefined); this.changeSequence += 1; this.savingState = "dirty"; },
    moveLayer(elementId: string, mode: "up" | "down" | "top" | "bottom") { const slide = this.document?.slides.find((value) => value.elements.some((item) => item.id === elementId)); if (!slide) return; const index = slide.elements.findIndex((item) => item.id === elementId); if (index < 0 || slide.elements[index]?.locked) return; this.snapshot(); const [item] = slide.elements.splice(index, 1); const target = mode === "top" ? slide.elements.length : mode === "bottom" ? 0 : Math.max(0, Math.min(slide.elements.length, index + (mode === "up" ? 1 : -1))); slide.elements.splice(target, 0, item); slide.elements.forEach((element, z) => element.z_index = z + 1); this.changeSequence += 1; this.savingState = "dirty"; },
    reorderSlides(from: number, to: number) { if (!this.document || from === to || from < 0 || to < 0 || from >= this.document.slides.length || to >= this.document.slides.length) return; this.snapshot(); const [slide] = this.document.slides.splice(from, 1); this.document.slides.splice(to, 0, slide); this.document.slides.forEach((item, index) => item.order = index + 1); this.changeSequence += 1; this.savingState = "dirty"; },
    scheduleSave(fetchImpl: Fetch = fetch) { if (this.exportState === "ready") this.exportState = "idle"; if (saveTimer) window.clearTimeout(saveTimer); if (this.savingState === "conflict") return; saveTimer = window.setTimeout(() => { void this.save(fetchImpl); }, 500); },
    undo() { if (!this.document || !this.undoStack.length) return; const animations = useAnimationStore(); this.redoStack.push(clone(this.document)); this.animationRedoStack.push(clone(animations.manifest)); this.document = this.undoStack.pop()!; animations.manifest = this.animationUndoStack.pop() ?? null; void animations.save().catch(() => undefined); this.changeSequence += 1; this.savingState = "dirty"; },
    redo() { if (!this.document || !this.redoStack.length) return; const animations = useAnimationStore(); this.undoStack.push(clone(this.document)); this.animationUndoStack.push(clone(animations.manifest)); this.document = this.redoStack.pop()!; animations.manifest = this.animationRedoStack.pop() ?? null; void animations.save().catch(() => undefined); this.changeSequence += 1; this.savingState = "dirty"; },
    async reload(fetchImpl: Fetch = fetch) { if (this.projectId) await this.load(this.projectId, fetchImpl); },
    async flushSave(fetchImpl: Fetch = fetch) {
      if (saveTimer) { window.clearTimeout(saveTimer); saveTimer = undefined; }
      if (this.savingState === "conflict") throw new Error("版本冲突，请重新加载");
      // A pointer-up debounce may already be PATCHing.  Wait for it, then save
      // any mutation that happened while that response was in flight.
      if (saveInFlight) await saveInFlight;
      if (this.savingState === "dirty" || this.savingState === "failed") await this.save(fetchImpl);
      if (saveInFlight) await saveInFlight;
      if (this.savingState === "dirty") await this.save(fetchImpl);
      if (this.conflict) throw new Error("版本冲突，请重新加载");
      if (this.savingState === "failed") throw new Error(this.error || "保存失败，点击重试");
    },
    async exportPpt(fetchImpl: Fetch = fetch) {
      this.exportState = "saving"; this.exportError = "";
      try {
        await this.flushSave(fetchImpl);
        if (!this.projectId) throw new Error("编辑项目未加载");
        const animations = useAnimationStore();
        if (animations.projectId === this.projectId) {
          animations.setDocumentRevision(this.revision);
          await animations.flushSave();
        }
        this.exportState = "exporting";
        const response = await fetchImpl(`/api/v1/ppt-master/projects/${encodeURIComponent(this.projectId)}/editor/export`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: this.revision }) });
        const payload = await response.json();
        if (!response.ok || !payload?.data?.download_url || typeof payload.data.file_id !== "number") throw new Error(payload?.detail?.code || "导出失败，点击重试");
        this.lastExport = payload.data; this.exportState = "ready";
        return payload.data as { export_id: string; file_id: number; download_url: string; revision: number };
      } catch (cause) {
        this.exportState = "failed"; this.exportError = cause instanceof Error ? cause.message : "导出失败，点击重试";
        return null;
      }
    },
    async save(fetchImpl: Fetch = fetch): Promise<void> {
      if (saveInFlight) {
        await saveInFlight;
        if (this.savingState === "dirty") return this.save(fetchImpl);
        return;
      }
      if (!this.document || !this.projectId || this.savingState === "conflict") return;
      const run = async () => {
        const epoch = this.loadEpoch; const sequence = ++this.saveSequence; const changeSequence = this.changeSequence; const revision = this.revision; const document = clone(this.document!); this.savingState = "saving";
        try {
          const response = await fetchImpl(`/api/v1/ppt-master/projects/${encodeURIComponent(this.projectId)}/editor`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: revision, document }) });
          const payload = await response.json();
          if (epoch !== this.loadEpoch) return;
          if (response.status === 409) { this.conflict = true; this.savingState = "conflict"; return; }
          if (!response.ok) { this.error = "保存失败"; this.savingState = "failed"; return; }
          if (changeSequence !== this.changeSequence) { this.revision = payload.data.revision; this.savingState = "dirty"; return; }
          if (sequence !== this.saveSequence) return;
          this.document = payload.data.document; this.revision = payload.data.revision; const animations = useAnimationStore(); if (animations.projectId === this.projectId) animations.setDocumentRevision(this.revision); this.savingState = "saved";
        } catch { if (epoch === this.loadEpoch && changeSequence === this.changeSequence) { this.error = "保存失败"; this.savingState = "failed"; } }
      };
      const current = run(); saveInFlight = current;
      try { await current; } finally { if (saveInFlight === current) saveInFlight = null; }
    },
  },
});
