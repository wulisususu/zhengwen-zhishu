import { defineStore } from "pinia";
import { getSessionToken } from "../../../stores/auth.js";
import { getGovOfficeAdapter, GovOfficeError } from "../adapters";
import type { DocumentQuery } from "../adapters";
import type { DraftChanges, ExportResult, FieldKey, IssueResolution, Material, OfficialDocument } from "../types";

/** Shared document state for drafting, proofreading and the review center. */
export const useGovDocumentsStore = defineStore("govDocuments", {
  state: () => ({
    byId: {} as Record<string, OfficialDocument>,
    order: [] as string[],
    materialLibrary: [] as Material[],
    loading: false,
    error: "",
    notice: "",
  }),
  getters: {
    list: (state) => state.order.map((id) => state.byId[id]).filter(Boolean),
  },
  actions: {
    async create(changes: DraftChanges) {
      const adapter = getGovOfficeAdapter();
      if (!adapter.createDocument) return this.run(async () => { throw new GovOfficeError("演示模式不支持新建", "unavailable"); });
      const doc = await this.run(() => adapter.createDocument!(changes));
      if (doc) this.upsert(doc);
      return doc;
    },
    upsert(doc: OfficialDocument) {
      this.byId = { ...this.byId, [doc.id]: doc };
      if (!this.order.includes(doc.id)) this.order = [...this.order, doc.id];
    },
    clearMessages() {
      this.error = "";
      this.notice = "";
    },
    async run<T>(op: () => Promise<T>, notice = ""): Promise<T | undefined> {
      const token = getSessionToken();
      this.error = "";
      try {
        const result = await op();
        if (getSessionToken() !== token) return undefined;
        if (notice) this.notice = notice;
        return result;
      } catch (err) {
        if (getSessionToken() !== token) return undefined;
        this.notice = "";
        this.error = err instanceof GovOfficeError ? err.message : "操作失败，请稍后重试。";
        return undefined;
      }
    },
    async loadList(query?: DocumentQuery) {
      this.loading = true;
      const docs = await this.run(() => getGovOfficeAdapter().listDocuments(query));
      this.loading = false;
      if (!docs) return;
      docs.forEach((d) => this.upsert(d));
      this.order = docs.map((d) => d.id);
    },
    async load(id: string) {
      const doc = await this.run(() => getGovOfficeAdapter().getDocument(id));
      if (doc) this.upsert(doc);
      return doc;
    },
    async loadMaterialLibrary() {
      const lib = await this.run(() => getGovOfficeAdapter().listMaterialLibrary());
      if (lib) this.materialLibrary = lib;
    },
    async mutate(op: () => Promise<OfficialDocument>, notice = "") {
      const doc = await this.run(op, notice);
      if (doc) this.upsert(doc);
      return doc;
    },
    updateFields(id: string, fields: Partial<Record<FieldKey, string>>) {
      return this.mutate(() => getGovOfficeAdapter().updateFields(id, fields));
    },
    applySuggestion(id: string, issueId: string) {
      return this.mutate(() => getGovOfficeAdapter().applySuggestion(id, issueId), "已采纳修改建议。");
    },
    resolveIssue(id: string, issueId: string, resolution: IssueResolution, notice: string) {
      return this.mutate(() => getGovOfficeAdapter().resolveIssue(id, issueId, resolution), notice);
    },
    clearResolution(id: string, issueId: string) {
      return this.mutate(() => getGovOfficeAdapter().clearResolution(id, issueId), "已撤销处理。");
    },
    rerunReview(id: string, notice: string) {
      return this.mutate(() => getGovOfficeAdapter().rerunReview(id), notice);
    },
    addMaterials(id: string, materialIds: string[]) {
      return this.mutate(() => getGovOfficeAdapter().addMaterials(id, materialIds), `已添加 ${materialIds.length} 份材料。`);
    },
    removeMaterial(id: string, materialId: string) {
      return this.mutate(() => getGovOfficeAdapter().removeMaterial(id, materialId), "已移除材料。");
    },
    saveDraft(id: string, notice: string, changes?: DraftChanges) {
      return this.mutate(() => getGovOfficeAdapter().saveDraft(id, changes), notice);
    },
    submitForReview(id: string) {
      return this.mutate(() => getGovOfficeAdapter().submitForReview(id), "已提交审核。");
    },
    async approve(id: string, opinion: string) {
      const result = await this.mutate(() => getGovOfficeAdapter().approve(id, opinion), "已审核通过。");
      if (!result) {
        const message = this.error;
        await this.load(id);
        this.error = message;
      }
      return result;
    },
    returnForRevision(id: string, opinion: string) {
      return this.mutate(() => getGovOfficeAdapter().returnForRevision(id, opinion), "已退回修改。");
    },
    async exportDocument(id: string, kind: ExportResult["kind"]) {
      return this.run(() => getGovOfficeAdapter().exportDocument(id, kind));
    },
  },
});
