import { defineStore } from "pinia";

type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type Analysis = { source_sha256: string; slide_count: number; slides: Record<string, unknown>[] };
type Task = { task_id: string; status: string; output_file_id?: number };

async function responseData(fetchImpl: Fetch, input: RequestInfo | URL, init?: RequestInit) {
  const response = await fetchImpl(input, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload?.detail?.code || "原生 PPT 增强请求失败");
  return payload.data;
}

export const usePptNativeEnhanceStore = defineStore("ppt-native-enhance", {
  state: () => ({ sourceFileId: 0, analysis: null as Analysis | null, task: null as Task | null, state: "idle" as "idle" | "analyzing" | "submitting" | "completed" | "failed", error: "" }),
  actions: {
    async analyze(sourceFileId: number, fetchImpl: Fetch = fetch) {
      this.state = "analyzing"; this.error = "";
      try {
        this.analysis = await responseData(fetchImpl, "/api/v1/ppt-master/enhance/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_file_id: sourceFileId }) });
        this.sourceFileId = sourceFileId; this.state = "idle"; return this.analysis;
      } catch (cause) { this.state = "failed"; this.error = cause instanceof Error ? cause.message : "PPT 分析失败"; return null; }
    },
    async createTask(options: Record<string, unknown>, fetchImpl: Fetch = fetch) {
      if (!this.sourceFileId || !this.analysis?.source_sha256) return null;
      this.state = "submitting"; this.error = "";
      try {
        this.task = await responseData(fetchImpl, "/api/v1/ppt-master/enhance/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_file_id: this.sourceFileId, expected_sha256: this.analysis.source_sha256, options }) });
        this.state = this.task?.status === "completed" ? "completed" : "idle"; return this.task;
      } catch (cause) { this.state = "failed"; this.error = cause instanceof Error ? cause.message : "PPT 增强失败"; return null; }
    },
  },
});
