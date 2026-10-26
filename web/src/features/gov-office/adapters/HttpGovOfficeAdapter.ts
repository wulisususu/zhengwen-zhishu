import { getSessionToken } from "../../../stores/auth.js";
import { handleUnauthorized } from "../../../api.js";
import { GovOfficeError } from "./GovOfficeAdapter";
import type { GovOfficeAdapter, DocumentQuery } from "./GovOfficeAdapter";
import type { Actor, AskOptions, Citation, DraftChanges, ExportResult, FieldKey, IssueResolution, Material, OfficialDocument, PolicyStats, QaSession, QaTurn, RuntimeStatus } from "../types";

const BASE = "/api/v1/gov";

async function request(path: string, method = "GET", body?: unknown): Promise<Response> {
  const token = getSessionToken();
  if (!token) throw new GovOfficeError("请先登录", "401");
  const headers = new Headers({ Authorization: `Bearer ${token}` });
  const form = body instanceof FormData;
  if (body !== undefined && !form) headers.set("Content-Type", "application/json");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), path.endsWith("/generate") ? 180000 : 30000);
  let res: Response;
  try {
    res = await fetch(BASE + path, { method, headers, body: body === undefined ? undefined : form ? body as FormData : JSON.stringify(body), signal: controller.signal });
  } catch {
    throw new GovOfficeError("连接后端失败或请求超时，请稍后重试", "network");
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    if (res.status === 401) handleUnauthorized();
    const error = await res.json().catch(() => ({}));
    const detail = Array.isArray(error.detail) ? error.detail.map((d: { msg?: string }) => d.msg).join("；") : error.detail;
    throw new GovOfficeError(detail || error.message || `请求失败（${res.status}）`, String(res.status));
  }
  return res;
}

async function json<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await request(path, method, body);
  const envelope = await res.json();
  if (envelope.code !== 0) throw new GovOfficeError(envelope.message || "后端处理失败", String(envelope.code));
  return envelope.data as T;
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename;
  document.body.appendChild(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function downloadGovMaterial(file: Material): Promise<void> {
  if (!file.downloadUrl?.startsWith(BASE + "/materials/")) throw new GovOfficeError("材料没有可用下载地址", "unavailable");
  const res = await request(file.downloadUrl.slice(BASE.length));
  download(await res.blob(), file.name);
}

export class HttpGovOfficeAdapter implements GovOfficeAdapter {
  readonly mode = "http" as const;
  private documents = new Map<string, OfficialDocument>();

  private remember(doc: OfficialDocument) { this.documents.set(doc.id, doc); return doc; }
  private async revision(id: string) { return (this.documents.get(id) ?? await this.getDocument(id)).version; }
  private async change(id: string, suffix: string, data: object = {}, method = "POST") {
    return this.remember(await json<OfficialDocument>(`/documents/${encodeURIComponent(id)}${suffix}`, method, { version: await this.revision(id), ...data }));
  }
  getRuntimeStatus() { return json<RuntimeStatus>("/runtime"); }
  getCurrentActor() { return json<Actor>("/actor"); }
  async getPolicyStats(): Promise<PolicyStats> { return { origin: "backend", available: false, total: 0, current: 0, abolished: 0, unverified: 0 }; }
  async listQaSessions(): Promise<QaSession[]> { return []; }
  async getCitations(_ids: string[]): Promise<Citation[]> { return []; }
  async askPolicyQuestion(_id: string, _question: string, _options: AskOptions): Promise<QaTurn> { throw new GovOfficeError("政策检索服务未接入", "unavailable"); }
  async listDocuments(query: DocumentQuery = {}) {
    const params = new URLSearchParams();
    if (query.keyword) params.set("keyword", query.keyword);
    if (query.docType) params.set("docType", query.docType);
    const docs = await json<OfficialDocument[]>("/documents?" + params);
    docs.forEach((d) => this.remember(d)); return docs;
  }
  async getDocument(id: string) { return this.remember(await json<OfficialDocument>(`/documents/${encodeURIComponent(id)}`)); }
  async createDocument(changes: DraftChanges) { return this.remember(await json<OfficialDocument>("/documents", "POST", { title: "新建通知", docType: "notice", ...changes })); }
  saveDraft(id: string, changes: DraftChanges = {}) { return this.change(id, "", changes, "PUT"); }
  async updateFields(id: string, fields: Partial<Record<FieldKey, string>>) {
    const doc = this.documents.get(id) ?? await this.getDocument(id);
    return this.saveDraft(id, { fields: { ...doc.fields, ...fields } });
  }
  async listMaterialLibrary() { return json<Material[]>("/materials"); }
  async uploadMaterial(file: File) { const form = new FormData(); form.append("file", file); return json<Material>("/materials", "POST", form); }
  addMaterials(id: string, materialIds: string[]) { return this.change(id, "/materials", { fileIds: materialIds.map(Number) }); }
  async removeMaterial(id: string, materialId: string) {
    return this.remember(await json<OfficialDocument>(`/documents/${encodeURIComponent(id)}/materials/${encodeURIComponent(materialId)}?version=${await this.revision(id)}`, "DELETE"));
  }
  submitForReview(id: string) { return this.change(id, "/submit"); }
  approve(id: string, opinion: string) { return this.change(id, "/approve", { opinion }); }
  returnForRevision(id: string, opinion: string) { return this.change(id, "/return", { opinion }); }
  rerunReview(id: string) { return this.change(id, "/check"); }
  generateDraft(id: string, prompt: string) { return this.change(id, "/generate", { prompt }); }
  async applySuggestion(_id: string, _issue: string): Promise<OfficialDocument> { throw new GovOfficeError("自动审校未接入", "unavailable"); }
  async resolveIssue(_id: string, _issue: string, _resolution: IssueResolution): Promise<OfficialDocument> { throw new GovOfficeError("自动审校未接入", "unavailable"); }
  async clearResolution(_id: string, _issue: string): Promise<OfficialDocument> { throw new GovOfficeError("自动审校未接入", "unavailable"); }
  async exportDocument(id: string, kind: ExportResult["kind"]): Promise<ExportResult> {
    if (kind === "formal") throw new GovOfficeError("正式发文权限尚未配置", "forbidden");
    const res = await request(`/documents/${encodeURIComponent(id)}/export`, "POST", { kind });
    if (!res.headers.get("Content-Type")?.includes("wordprocessingml")) throw new GovOfficeError("后端未返回有效 DOCX 文件", "invalid_export");
    const filename = `内部草稿-${id}.docx`;
    download(await res.blob(), filename);
    return { generated: true, kind, filename, watermark: "未审核 · 内部草稿", message: "内部草稿已生成并下载，不能作为正式文件使用。" };
  }
}
