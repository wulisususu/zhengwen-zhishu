import { defineStore } from "pinia";

type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type Plan = { plan_id: string; status: "draft" | "confirmed"; revision: number; plan: Record<string, any> };
type Task = { task_id: string; status: string; output_file_id?: number; artifact_manifest?: Record<string, any> };

async function responseData(fetchImpl: Fetch, input: RequestInfo | URL, init?: RequestInit) {
  const response = await fetchImpl(input, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload?.detail?.code || "模板填充请求失败");
  return payload.data;
}

export const usePptTemplateFillStore = defineStore("ppt-template-fill", {
  state: () => ({ template: null as Record<string, any> | null, slides: [] as Record<string, any>[], plan: null as Plan | null, task: null as Task | null, state: "idle" as "idle" | "analyzing" | "saving" | "confirming" | "applying" | "completed" | "failed" | "conflict", error: "" }),
  actions: {
    async register(sourceFileId: number, title: string, fetchImpl: Fetch = fetch) {
      this.state = "analyzing"; this.error = "";
      try { this.template = await responseData(fetchImpl, "/api/v1/ppt-master/templates", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_file_id: sourceFileId, title }) }); this.state = "idle"; return this.template; }
      catch (cause) { this.state = "failed"; this.error = cause instanceof Error ? cause.message : "模板上传失败"; return null; }
    },
    async createPlan(selectedSlides: number[], sourceFileIds: number[], fetchImpl: Fetch = fetch) {
      if (!this.template?.template_id) return null;
      this.state = "saving"; this.error = "";
      try { this.plan = await responseData(fetchImpl, `/api/v1/ppt-master/templates/${encodeURIComponent(this.template.template_id)}/fill-plans`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ selected_slides: selectedSlides, source_file_ids: sourceFileIds }) }); this.state = "idle"; return this.plan; }
      catch (cause) { this.state = "failed"; this.error = cause instanceof Error ? cause.message : "计划创建失败"; return null; }
    },
    async analyze(templateId: string, fetchImpl: Fetch = fetch) {
      this.state = "analyzing"; this.error = "";
      try { this.template = await responseData(fetchImpl, `/api/v1/ppt-master/templates/${encodeURIComponent(templateId)}/analyze`, { method: "POST" }); this.slides = await responseData(fetchImpl, `/api/v1/ppt-master/templates/${encodeURIComponent(templateId)}/slides`); this.state = "idle"; return this.template; }
      catch (cause) { this.state = "failed"; this.error = cause instanceof Error ? cause.message : "模板分析失败"; return null; }
    },
    async savePlan(fetchImpl: Fetch = fetch) {
      if (!this.plan || this.plan.status !== "draft") return null;
      this.state = "saving"; this.error = "";
      try { const result = await responseData(fetchImpl, `/api/v1/ppt-master/fill-plans/${encodeURIComponent(this.plan.plan_id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: this.plan.revision, plan: this.plan.plan }) }); this.plan = result; this.state = "idle"; return result; }
      catch (cause) { this.state = String(cause).includes("revision_conflict") ? "conflict" : "failed"; this.error = cause instanceof Error ? cause.message : "计划保存失败"; return null; }
    },
    async confirm(fetchImpl: Fetch = fetch) {
      if (!this.plan || this.plan.status !== "draft") return null;
      this.state = "confirming"; this.error = "";
      try { this.plan = await responseData(fetchImpl, `/api/v1/ppt-master/fill-plans/${encodeURIComponent(this.plan.plan_id)}/confirm`, { method: "POST" }); this.state = "idle"; return this.plan; }
      catch (cause) { this.state = "failed"; this.error = cause instanceof Error ? cause.message : "计划确认失败"; return null; }
    },
    async apply(fetchImpl: Fetch = fetch) {
      if (!this.plan || this.plan.status !== "confirmed") { this.error = "请先确认填充计划"; return null; }
      this.state = "applying"; this.error = "";
      try { this.task = await responseData(fetchImpl, `/api/v1/ppt-master/fill-plans/${encodeURIComponent(this.plan.plan_id)}/apply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: this.plan.revision }) }); this.state = this.task?.status === "completed" ? "completed" : "failed"; return this.task; }
      catch (cause) { this.state = "failed"; this.error = cause instanceof Error ? cause.message : "生成失败"; return null; }
    },
  },
});
