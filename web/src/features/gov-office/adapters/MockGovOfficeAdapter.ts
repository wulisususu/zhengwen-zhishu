// In-memory demo adapter. It exists because the backend contracts are not
// defined yet. It never generates files, never calls a model and never
// invents a runtime state; anything it returns carries origin = "demo".

import { DEMO_CITATIONS, DEMO_DOCUMENTS, DEMO_MATERIAL_LIBRARY, DEMO_POLICY_STATS, DEMO_QA_SESSIONS } from "./mockData";
import { GovOfficeError } from "./GovOfficeAdapter";
import type { DocumentQuery, GovOfficeAdapter } from "./GovOfficeAdapter";
import { documentGates, evaluateIssue, summarizeIssues } from "../domain/issueRules";
import type {
  Actor,
  AskOptions,
  ExportResult,
  FieldKey,
  IssueResolution,
  OfficialDocument,
  QaTurn,
  ReviewRecord,
  RuntimeStatus,
  Tone,
} from "../types";

const DEMO_ACTOR: Actor = {
  origin: "demo",
  name: "演示用户",
  department: "综合处",
  // The demo actor holds both roles so the whole flow can be walked through.
  // A real backend must keep drafter and reviewer separate.
  roles: ["drafter", "reviewer"],
  canFormalIssue: false,
};

const INTERNAL_WATERMARK = "未审核 · 内部草稿";

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function nowStamp(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function createMockGovOfficeAdapter(): GovOfficeAdapter {
  const documents = new Map(DEMO_DOCUMENTS.map((d) => [d.id, clone(d)]));
  const sessions = clone(DEMO_QA_SESSIONS);
  let recordSeq = 0;

  function find(id: string): OfficialDocument {
    const doc = documents.get(id);
    if (!doc) throw new GovOfficeError("文稿不存在", "not_found");
    return doc;
  }

  function record(doc: OfficialDocument, action: string, tone: Tone, note?: string) {
    const entry: ReviewRecord = { id: `${doc.id}-r${++recordSeq}`, action, actor: DEMO_ACTOR.name, at: nowStamp(), tone };
    if (note) entry.note = note;
    doc.history.push(entry);
  }

  function assertEditable(doc: OfficialDocument) {
    if (!documentGates(doc, DEMO_ACTOR).canEdit) throw new GovOfficeError("文稿审核中或已审核通过，不能修改。", "locked");
  }

  function setSegmentText(doc: OfficialDocument, segmentId: string, text: string) {
    if (doc.docNumber.id === segmentId) {
      doc.docNumber.text = text;
      return;
    }
    for (const block of doc.blocks) {
      for (const seg of block.segments) {
        if (seg.kind === "text" && seg.id === segmentId) {
          seg.text = text;
          return;
        }
      }
    }
    throw new GovOfficeError("建议对应的正文位置不存在", "segment_not_found");
  }

  function validateResolution(doc: OfficialDocument, issueId: string, resolution: IssueResolution) {
    const issue = doc.issues.find((i) => i.id === issueId);
    if (!issue) throw new GovOfficeError("审校问题不存在", "not_found");
    const critical = issue.severity === "critical";
    const illegal =
      (resolution.kind === "hint_ignored" && critical) ||
      ((resolution.kind === "ai_confirmed" || resolution.kind === "ai_dismissed") && issue.source !== "ai") ||
      ((resolution.kind === "exception_requested" || resolution.kind === "exception_approved") && !(critical && issue.source === "rule"));
    if (illegal) throw new GovOfficeError("该问题不允许这样处理", "illegal_resolution");
    if ("reason" in resolution && !resolution.reason.trim()) throw new GovOfficeError("请填写处理理由", "reason_required");
    if (resolution.kind === "exception_approved" && !DEMO_ACTOR.roles.includes("reviewer")) {
      throw new GovOfficeError("只有审核人可以批准例外", "forbidden");
    }
    return issue;
  }

  return {
    mode: "mock",

    async getRuntimeStatus(): Promise<RuntimeStatus> {
      return { origin: "demo", modelMode: "unknown", label: "演示环境 · 模型状态未知", detail: "未接入后端，无法读取模型出口配置。" };
    },

    async getCurrentActor() {
      return clone(DEMO_ACTOR);
    },

    async getPolicyStats() {
      return { origin: "demo" as const, ...DEMO_POLICY_STATS };
    },

    async listQaSessions() {
      return clone(sessions);
    },

    async getCitations(ids) {
      return clone(DEMO_CITATIONS.filter((c) => ids.includes(c.id)));
    },

    async askPolicyQuestion(sessionId: string, question: string, _options: AskOptions): Promise<QaTurn> {
      const turn: QaTurn = {
        id: `${sessionId}-t${Date.now()}`,
        question,
        askedAt: nowStamp().slice(11),
        answer: {
          kind: "unavailable",
          badges: [{ label: "演示环境", tone: "warning" }],
          citationIds: [],
          sections: [
            {
              heading: "检索服务未接入",
              tone: "default",
              segments: [{ kind: "text", text: "当前为演示环境，未连接政策检索服务，不会生成回答，也不会引用任何依据。" }],
            },
          ],
          meta: "未发起检索（演示）",
        },
      };
      const session = sessions.find((s) => s.id === sessionId);
      if (session) session.turns.push(clone(turn));
      return turn;
    },

    async listDocuments(query: DocumentQuery = {}) {
      const keyword = (query.keyword ?? "").trim();
      return clone(
        [...documents.values()].filter((d) => {
          if (keyword && !d.title.includes(keyword) && !d.author.includes(keyword)) return false;
          if (query.docType && query.docType !== "all" && d.docType !== query.docType) return false;
          return true;
        }),
      );
    },

    async getDocument(id) {
      return clone(find(id));
    },

    async updateFields(id, fields: Partial<Record<FieldKey, string>>) {
      const doc = find(id);
      assertEditable(doc);
      doc.fields = { ...doc.fields, ...fields };
      return clone(doc);
    },

    async applySuggestion(id, issueId) {
      const doc = find(id);
      assertEditable(doc);
      const issue = doc.issues.find((i) => i.id === issueId);
      if (!issue?.suggestion) throw new GovOfficeError("该问题没有可采纳的修改建议", "no_suggestion");
      if (evaluateIssue(issue, doc).state === "needs_human_review") {
        throw new GovOfficeError("AI 判断的严重问题须先人工复核", "needs_human_review");
      }
      setSegmentText(doc, issue.suggestion.segmentId, issue.suggestion.replacement);
      const swap = issue.suggestion.replacePolicyRef;
      if (swap) doc.policyRefs = doc.policyRefs.filter((p) => p.id !== swap.fromId).concat([swap.to]);
      doc.resolutions[issueId] = { kind: "fixed", by: DEMO_ACTOR.name, at: nowStamp() };
      return clone(doc);
    },

    async resolveIssue(id, issueId, resolution) {
      const doc = find(id);
      const issue = validateResolution(doc, issueId, resolution);
      doc.resolutions[issueId] = clone(resolution);
      const reason = "reason" in resolution ? resolution.reason : "";
      if (resolution.kind === "exception_requested") record(doc, "申请例外处理", "warning", `${issue.title}：${reason}`);
      if (resolution.kind === "exception_approved") record(doc, "批准例外", "warning", `${issue.title}：${reason}`);
      if (resolution.kind === "ai_dismissed") record(doc, "AI 问题复核：不成立", "neutral", `${issue.title}：${reason}`);
      if (resolution.kind === "ai_confirmed") record(doc, "AI 问题复核：确认", "neutral", issue.title);
      return clone(doc);
    },

    async clearResolution(id, issueId) {
      const doc = find(id);
      const current = doc.resolutions[issueId];
      if (current && (current.kind === "fixed" || current.kind === "exception_approved")) {
        throw new GovOfficeError("已修复或已批准的处理不能撤销", "irreversible");
      }
      delete doc.resolutions[issueId];
      return clone(doc);
    },

    async rerunReview(id) {
      // Demo only: no checker runs; the timestamp is the sole change.
      const doc = find(id);
      doc.lastReviewedAt = nowStamp();
      return clone(doc);
    },

    async listMaterialLibrary() {
      return clone(DEMO_MATERIAL_LIBRARY);
    },

    async addMaterials(id, materialIds) {
      const doc = find(id);
      assertEditable(doc);
      const have = new Set(doc.materials.map((m) => m.id));
      const added = DEMO_MATERIAL_LIBRARY.filter((m) => materialIds.includes(m.id) && !have.has(m.id));
      doc.materials.push(...clone(added).map((m) => ({ ...m, meta: `${m.meta} · 未被引用` })));
      return clone(doc);
    },

    async removeMaterial(id, materialId) {
      const doc = find(id);
      assertEditable(doc);
      doc.materials = doc.materials.filter((m) => m.id !== materialId);
      return clone(doc);
    },

    async saveDraft(id) {
      const doc = find(id);
      assertEditable(doc);
      return clone(doc);
    },

    async submitForReview(id) {
      const doc = find(id);
      if (!documentGates(doc, DEMO_ACTOR).canSubmit) throw new GovOfficeError("当前状态不能提交审核", "invalid_status");
      const { blockers } = summarizeIssues(doc);
      doc.status = "pending";
      record(doc, "提交审核", "info", blockers.length ? `提交时仍有 ${blockers.length} 项严重问题待处理` : undefined);
      return clone(doc);
    },

    async approve(id, opinion) {
      const doc = find(id);
      const gates = documentGates(doc, DEMO_ACTOR);
      if (!gates.canApprove) throw new GovOfficeError(gates.approveBlockedReason, "blocked");
      doc.status = "approved";
      record(doc, "审核通过", "success", opinion.trim() || undefined);
      return clone(doc);
    },

    async returnForRevision(id, opinion) {
      const doc = find(id);
      if (!documentGates(doc, DEMO_ACTOR).canReturn) throw new GovOfficeError("当前状态不能退回", "invalid_status");
      if (!opinion.trim()) throw new GovOfficeError("退回修改时请填写审核意见", "opinion_required");
      doc.status = "returned";
      record(doc, "退回修改", "danger", opinion.trim());
      return clone(doc);
    },

    async exportDocument(id, kind): Promise<ExportResult> {
      const doc = find(id);
      if (kind === "formal") {
        const gates = documentGates(doc, DEMO_ACTOR);
        throw new GovOfficeError(gates.formalExportBlockedReason || "演示环境未接入正式导出服务", "formal_export_blocked");
      }
      return {
        generated: false,
        kind,
        watermark: INTERNAL_WATERMARK,
        message: `演示环境未接入导出服务，未生成文件。接入后端后将导出带「${INTERNAL_WATERMARK}」标识的 DOCX。`,
      };
    },
  };
}
