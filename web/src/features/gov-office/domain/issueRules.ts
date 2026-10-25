// Pure rules for review issues and document gates.
//
// Tiered blocking (confirmed product decision):
// - Deterministic (rule) critical issues must be fixed before approval or
//   formal export. The only other way out is an exception that a reviewer
//   approves with a recorded reason.
// - AI critical issues must be reviewed by a person; the model alone never
//   blocks irreversibly. A person either confirms them (then they must be
//   fixed) or dismisses them with a recorded reason.
// - Warnings and hints never block and may be ignored.
// - Saving, submitting for review and exporting an internal draft marked
//   "未审核" are always allowed.
//
// The backend must enforce the same rules; these functions only drive the UI.

import type { Actor, IssueResolution, OfficialDocument, ReviewIssue } from "../types";

export type IssueState = "open" | "needs_human_review" | "confirmed_open" | "exception_pending" | "resolved";

export interface IssueEvaluation {
  issue: ReviewIssue;
  state: IssueState;
  resolution?: IssueResolution;
  resolvedLabel?: string;
}

export type IssueAction =
  | "locate"
  | "apply_suggestion"
  | "fill_field"
  | "ignore_hint"
  | "ai_confirm"
  | "ai_dismiss"
  | "request_exception"
  | "approve_exception"
  | "undo";

function isFieldFilled(issue: ReviewIssue, doc: OfficialDocument): boolean {
  return !!issue.requiredField && doc.fields[issue.requiredField].trim().length > 0;
}

/** Resolutions that are legal for the issue's severity and source. */
function isAllowedResolution(issue: ReviewIssue, resolution: IssueResolution): boolean {
  switch (resolution.kind) {
    case "fixed":
      return true;
    case "hint_ignored":
      return issue.severity !== "critical";
    case "ai_confirmed":
    case "ai_dismissed":
      return issue.source === "ai";
    case "exception_requested":
    case "exception_approved":
      return issue.source === "rule" && issue.severity === "critical";
  }
}

export function evaluateIssue(issue: ReviewIssue, doc: OfficialDocument): IssueEvaluation {
  if (isFieldFilled(issue, doc)) return { issue, state: "resolved", resolvedLabel: "已填写" };

  const raw = doc.resolutions[issue.id];
  const resolution = raw && isAllowedResolution(issue, raw) ? raw : undefined;
  const base = { issue, resolution };

  switch (resolution?.kind) {
    case "fixed":
      return { ...base, state: "resolved", resolvedLabel: "已采纳建议" };
    case "hint_ignored":
      return { ...base, state: "resolved", resolvedLabel: `已忽略提示（${resolution.by}）` };
    case "ai_dismissed":
      return { ...base, state: "resolved", resolvedLabel: `人工复核：不成立（${resolution.by}）` };
    case "exception_approved":
      return { ...base, state: "resolved", resolvedLabel: `例外放行（审核人：${resolution.by}）` };
    case "exception_requested":
      return { ...base, state: "exception_pending" };
    case "ai_confirmed":
      return { ...base, state: "confirmed_open" };
    default:
      if (issue.source === "ai" && issue.severity === "critical") return { ...base, state: "needs_human_review" };
      return { ...base, state: "open" };
  }
}

export function issueActions(issue: ReviewIssue, doc: OfficialDocument, actor: Actor): IssueAction[] {
  const { state, resolution } = evaluateIssue(issue, doc);
  const actions: IssueAction[] = ["locate"];
  const isReviewer = actor.roles.includes("reviewer");
  const isDrafter = actor.roles.includes("drafter");

  if (state === "resolved") {
    const undoable = resolution && ["hint_ignored", "ai_dismissed"].includes(resolution.kind);
    if (undoable) actions.push("undo");
    return actions;
  }

  if (issue.requiredField) actions.push("fill_field");
  if (issue.suggestion && state !== "needs_human_review") actions.push("apply_suggestion");

  if (issue.severity !== "critical") {
    actions.push("ignore_hint");
    return actions;
  }

  if (issue.source === "ai") {
    if (state === "needs_human_review") actions.push("ai_confirm", "ai_dismiss");
    if (state === "confirmed_open") actions.push("undo");
    return actions;
  }

  if (state === "open" && isDrafter) actions.push("request_exception");
  if (state === "exception_pending" && isDrafter) actions.push("undo");
  if (isReviewer && !issue.requiredField) actions.push("approve_exception");
  return actions;
}

export interface IssueSummary {
  evaluations: IssueEvaluation[];
  unresolved: IssueEvaluation[];
  resolved: IssueEvaluation[];
  blockers: IssueEvaluation[];
  open: { critical: number; warning: number; hint: number };
  humanReviewed: IssueEvaluation[];
}

export function summarizeIssues(doc: OfficialDocument): IssueSummary {
  const evaluations = doc.issues.map((issue) => evaluateIssue(issue, doc));
  const unresolved = evaluations.filter((e) => e.state !== "resolved");
  const resolved = evaluations.filter((e) => e.state === "resolved");
  const count = (severity: ReviewIssue["severity"]) => unresolved.filter((e) => e.issue.severity === severity).length;
  return {
    evaluations,
    unresolved,
    resolved,
    blockers: unresolved.filter((e) => e.issue.severity === "critical"),
    open: { critical: count("critical"), warning: count("warning"), hint: count("hint") },
    humanReviewed: evaluations.filter((e) => e.resolution && ["ai_dismissed", "exception_approved"].includes(e.resolution.kind)),
  };
}

export interface DocumentGates {
  canEdit: boolean;
  canSaveDraft: boolean;
  canSubmit: boolean;
  canExportInternalDraft: boolean;
  canApprove: boolean;
  canReturn: boolean;
  canFormalExport: boolean;
  approveBlockedReason: string;
  formalExportBlockedReason: string;
  blockers: IssueEvaluation[];
}

export function documentGates(doc: OfficialDocument, actor: Actor): DocumentGates {
  const { blockers } = summarizeIssues(doc);
  const isReviewer = actor.roles.includes("reviewer");
  const editable = doc.status === "draft" || doc.status === "returned";

  let approveBlockedReason = "";
  if (doc.status !== "pending") approveBlockedReason = "仅待审核文稿可以审核。";
  else if (!isReviewer) approveBlockedReason = "当前用户没有审核权限。";
  else if (blockers.length) approveBlockedReason = `仍有 ${blockers.length} 项严重问题未处理，须修复、完成人工复核或经审核人批准例外后才能通过。`;

  let formalExportBlockedReason = "";
  if (doc.status !== "approved") formalExportBlockedReason = "正式导出须先审核通过。";
  else if (blockers.length) formalExportBlockedReason = `仍有 ${blockers.length} 项严重问题未处理。`;
  else if (!actor.canFormalIssue) formalExportBlockedReason = "当前用户没有正式发文权限。";

  return {
    canEdit: editable,
    canSaveDraft: true,
    canSubmit: editable,
    canExportInternalDraft: true,
    canApprove: !approveBlockedReason,
    canReturn: doc.status === "pending" && isReviewer,
    canFormalExport: !formalExportBlockedReason,
    approveBlockedReason,
    formalExportBlockedReason,
    blockers,
  };
}
