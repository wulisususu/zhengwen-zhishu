// Data access contract for the government-office workbench.
//
// Production HTTP and explicit demo adapters share this boundary. Policy QA
// and automatic proofreading remain unavailable in production until integrated.

import type {
  Actor,
  AskOptions,
  Citation,
  DocTypeId,
  DraftChanges,
  ExportResult,
  FieldKey,
  IssueResolution,
  Material,
  OfficialDocument,
  PolicyStats,
  QaSession,
  QaTurn,
  RuntimeStatus,
} from "../types";

export interface DocumentQuery {
  keyword?: string;
  docType?: DocTypeId | "all";
}

export interface GovOfficeAdapter {
  /** "mock" adapters must only return payloads with origin === "demo". */
  readonly mode: "mock" | "http";

  getRuntimeStatus(): Promise<RuntimeStatus>;
  getCurrentActor(): Promise<Actor>;
  /**
   * Demo only: the mock adapter simulates the demo_drafter and demo_reviewer
   * identities. A backend adapter must not implement these; real permissions
   * come from the backend login.
   */
  listDemoActors?(): Promise<Actor[]>;
  switchDemoActor?(account: string): Promise<Actor>;

  getPolicyStats(): Promise<PolicyStats>;
  listQaSessions(): Promise<QaSession[]>;
  getCitations(ids: string[]): Promise<Citation[]>;
  askPolicyQuestion(sessionId: string, question: string, options: AskOptions): Promise<QaTurn>;

  listDocuments(query?: DocumentQuery): Promise<OfficialDocument[]>;
  createDocument?(changes: DraftChanges): Promise<OfficialDocument>;
  uploadMaterial?(file: File): Promise<Material>;
  generateDraft?(id: string, prompt: string): Promise<OfficialDocument>;
  getDocument(id: string): Promise<OfficialDocument>;
  updateFields(id: string, fields: Partial<Record<FieldKey, string>>): Promise<OfficialDocument>;
  applySuggestion(id: string, issueId: string): Promise<OfficialDocument>;
  resolveIssue(id: string, issueId: string, resolution: IssueResolution): Promise<OfficialDocument>;
  clearResolution(id: string, issueId: string): Promise<OfficialDocument>;
  rerunReview(id: string): Promise<OfficialDocument>;
  listMaterialLibrary(): Promise<Material[]>;
  addMaterials(id: string, materialIds: string[]): Promise<OfficialDocument>;
  removeMaterial(id: string, materialId: string): Promise<OfficialDocument>;
  saveDraft(id: string, changes?: DraftChanges): Promise<OfficialDocument>;
  submitForReview(id: string): Promise<OfficialDocument>;
  approve(id: string, opinion: string): Promise<OfficialDocument>;
  returnForRevision(id: string, opinion: string): Promise<OfficialDocument>;
  exportDocument(id: string, kind: ExportResult["kind"]): Promise<ExportResult>;
}

export class GovOfficeError extends Error {
  constructor(message: string, readonly code: string) {
    super(message);
    this.name = "GovOfficeError";
  }
}
