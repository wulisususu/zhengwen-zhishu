import { defineStore } from "pinia";

export type PptSourcePolicy = "parsed_only" | "ready_only";
export type PptSourceStatus = "queued" | "extracting" | "ocr" | "chunking" | "done" | "error";

export interface PptSourceAttachment {
  kind: "file" | "knowledge";
  fileId?: number;
  docId?: number;
  filename: string;
  fileType: string;
  size: number;
  status: PptSourceStatus;
  progress: number;
  error?: string;
  parseTaskId?: string;
  parsedFileId?: number;
}

export const usePptSourcesStore = defineStore("pptSources", {
  state: () => ({
    items: [] as PptSourceAttachment[],
    policy: "parsed_only" as PptSourcePolicy,
    manifest: [] as Record<string, unknown>[],
  }),
  getters: {
    pending: (state) => state.items.filter((item) => item.kind === "file" && !["done", "error"].includes(item.status)),
    failed: (state) => state.items.filter((item) => item.kind === "file" && item.status === "error"),
    attachmentFileIds: (state) => state.items.filter((item) => item.kind === "file").map((item) => item.fileId).filter((id): id is number => typeof id === "number"),
    knowledgeDocIds: (state) => state.items.filter((item) => item.kind === "knowledge").map((item) => item.docId).filter((id): id is number => typeof id === "number"),
    blocksGeneration(): boolean {
      return this.policy === "parsed_only" && (this.pending.length > 0 || this.failed.length > 0);
    },
  },
  actions: {
    restore(snapshot: { items?: PptSourceAttachment[]; policy?: PptSourcePolicy; manifest?: Record<string, unknown>[] } | undefined) {
      this.items = Array.isArray(snapshot?.items) ? snapshot!.items : [];
      this.policy = snapshot?.policy === "ready_only" ? "ready_only" : "parsed_only";
      this.manifest = Array.isArray(snapshot?.manifest) ? snapshot!.manifest : [];
    },
    upsert(item: PptSourceAttachment) {
      const key = item.kind === "file" ? item.fileId : item.docId;
      const index = this.items.findIndex((existing) => existing.kind === item.kind && (existing.kind === "file" ? existing.fileId : existing.docId) === key);
      if (index >= 0) this.items.splice(index, 1, { ...this.items[index], ...item });
      else this.items.push(item);
    },
    remove(kind: PptSourceAttachment["kind"], id: number) {
      this.items = this.items.filter((item) => !(item.kind === kind && (kind === "file" ? item.fileId : item.docId) === id));
    },
    setPolicy(policy: PptSourcePolicy) { this.policy = policy; },
    setManifest(manifest: Record<string, unknown>[]) { this.manifest = manifest; },
  },
});
