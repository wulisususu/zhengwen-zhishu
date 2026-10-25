import { describe, expect, it } from "vitest";
import {
  documentGates,
  evaluateIssue,
  issueActions,
  summarizeIssues,
} from "../../src/features/gov-office/domain/issueRules";
import type { Actor, IssueResolution, OfficialDocument, ReviewIssue } from "../../src/features/gov-office/types";

const at = "2025-10-25T10:00:00";

function issue(partial: Partial<ReviewIssue>): ReviewIssue {
  return {
    id: "i",
    severity: "critical",
    source: "rule",
    title: "t",
    description: "d",
    locationLabel: "l",
    anchor: "a",
    section: "s",
    ...partial,
  };
}

function doc(issues: ReviewIssue[], resolutions: Record<string, IssueResolution> = {}, extra: Partial<OfficialDocument> = {}): OfficialDocument {
  return {
    id: "doc",
    origin: "demo",
    title: "t",
    docType: "notice",
    status: "draft",
    docNumber: { id: "seg-docno", text: "x" },
    fields: { recipient: "", issuer: "", undertaker: "" },
    blocks: [],
    signDate: "2025年10月25日",
    author: "a",
    department: "d",
    createdAt: at,
    version: 1,
    materials: [],
    policyRefs: [],
    issues,
    resolutions,
    history: [],
    lastReviewedAt: at,
    ...extra,
  };
}

const drafter: Actor = { origin: "demo", name: "起草人", department: "d", roles: ["drafter"], canFormalIssue: false };
const reviewer: Actor = { origin: "demo", name: "审核人", department: "d", roles: ["reviewer"], canFormalIssue: true };

describe("evaluateIssue", () => {
  it("keeps a deterministic critical issue open until fixed", () => {
    const i = issue({ id: "r1" });
    expect(evaluateIssue(i, doc([i])).state).toBe("open");
    expect(evaluateIssue(i, doc([i], { r1: { kind: "fixed", by: "x", at } })).state).toBe("resolved");
  });

  it("requires human review for AI critical issues before anything else", () => {
    const i = issue({ id: "a1", source: "ai" });
    expect(evaluateIssue(i, doc([i])).state).toBe("needs_human_review");
    expect(evaluateIssue(i, doc([i], { a1: { kind: "ai_confirmed", by: "x", at } })).state).toBe("confirmed_open");
    expect(evaluateIssue(i, doc([i], { a1: { kind: "ai_dismissed", by: "x", reason: "依据已补充", at } })).state).toBe("resolved");
  });

  it("resolves a required-field issue once the field is filled", () => {
    const i = issue({ id: "f1", requiredField: "recipient" });
    expect(evaluateIssue(i, doc([i])).state).toBe("open");
    const filled = doc([i], {}, { fields: { recipient: "各区政务服务管理部门", issuer: "", undertaker: "" } });
    expect(evaluateIssue(i, filled)).toMatchObject({ state: "resolved", resolvedLabel: "已填写" });
  });

  it("treats a requested exception as still pending and an approved one as resolved", () => {
    const i = issue({ id: "r1" });
    expect(evaluateIssue(i, doc([i], { r1: { kind: "exception_requested", by: "x", reason: "r", at } })).state).toBe("exception_pending");
    expect(evaluateIssue(i, doc([i], { r1: { kind: "exception_approved", by: "审核人", reason: "r", at } })).state).toBe("resolved");
  });

  it("ignores an illegal hint_ignored resolution on a critical issue", () => {
    const i = issue({ id: "r1" });
    expect(evaluateIssue(i, doc([i], { r1: { kind: "hint_ignored", by: "x", at } })).state).toBe("open");
  });
});

describe("issueActions", () => {
  it("never offers ignore on critical issues", () => {
    const rule = issue({ id: "r1" });
    const ai = issue({ id: "a1", source: "ai" });
    for (const actor of [drafter, reviewer]) {
      expect(issueActions(rule, doc([rule]), actor)).not.toContain("ignore_hint");
      expect(issueActions(ai, doc([ai]), actor)).not.toContain("ignore_hint");
    }
  });

  it("offers ignore for warnings and hints", () => {
    const w = issue({ id: "w1", severity: "warning" });
    const h = issue({ id: "h1", severity: "hint", source: "ai" });
    expect(issueActions(w, doc([w]), drafter)).toContain("ignore_hint");
    expect(issueActions(h, doc([h]), drafter)).toContain("ignore_hint");
  });

  it("lets drafters request and reviewers approve exceptions for rule critical issues", () => {
    const r = issue({ id: "r1" });
    expect(issueActions(r, doc([r]), drafter)).toContain("request_exception");
    expect(issueActions(r, doc([r]), drafter)).not.toContain("approve_exception");
    const pending = doc([r], { r1: { kind: "exception_requested", by: "x", reason: "r", at } });
    expect(issueActions(r, pending, reviewer)).toContain("approve_exception");
  });

  it("offers human review actions on unreviewed AI critical issues", () => {
    const a = issue({ id: "a1", source: "ai" });
    expect(issueActions(a, doc([a]), drafter)).toEqual(expect.arrayContaining(["ai_confirm", "ai_dismiss"]));
  });
});

describe("summarizeIssues", () => {
  it("counts only unresolved issues and lists blockers", () => {
    const issues = [
      issue({ id: "r1" }),
      issue({ id: "a1", source: "ai" }),
      issue({ id: "w1", severity: "warning" }),
      issue({ id: "h1", severity: "hint" }),
    ];
    const summary = summarizeIssues(doc(issues, { h1: { kind: "hint_ignored", by: "x", at } }));
    expect(summary.open).toEqual({ critical: 2, warning: 1, hint: 0 });
    expect(summary.blockers.map((b) => b.issue.id)).toEqual(["r1", "a1"]);
    expect(summary.resolved.map((r) => r.issue.id)).toEqual(["h1"]);
  });
});

describe("documentGates", () => {
  const blocking = issue({ id: "r1" });

  it("always allows saving and internal draft export", () => {
    const gates = documentGates(doc([blocking]), drafter);
    expect(gates.canSaveDraft).toBe(true);
    expect(gates.canExportInternalDraft).toBe(true);
  });

  it("allows submitting a draft for review even with blockers", () => {
    expect(documentGates(doc([blocking]), drafter).canSubmit).toBe(true);
    expect(documentGates(doc([blocking], {}, { status: "pending" }), drafter).canSubmit).toBe(false);
  });

  it("blocks approval while critical issues remain", () => {
    const pending = doc([blocking], {}, { status: "pending" });
    const gates = documentGates(pending, reviewer);
    expect(gates.canApprove).toBe(false);
    expect(gates.approveBlockedReason).toContain("1 项严重问题");
    const fixed = doc([blocking], { r1: { kind: "fixed", by: "x", at } }, { status: "pending" });
    expect(documentGates(fixed, reviewer).canApprove).toBe(true);
  });

  it("requires the reviewer role to approve or return", () => {
    const pending = doc([], {}, { status: "pending" });
    expect(documentGates(pending, drafter).canApprove).toBe(false);
    expect(documentGates(pending, drafter).canReturn).toBe(false);
    expect(documentGates(pending, reviewer).canReturn).toBe(true);
  });

  it("requires approval, no blockers and formal permission for formal export", () => {
    const approved = doc([], {}, { status: "approved" });
    expect(documentGates(approved, reviewer).canFormalExport).toBe(true);
    expect(documentGates(approved, drafter).canFormalExport).toBe(false);
    expect(documentGates(approved, drafter).formalExportBlockedReason).toContain("权限");
    expect(documentGates(doc([], {}, { status: "pending" }), reviewer).canFormalExport).toBe(false);
  });

  it("locks editing while the document is pending or approved", () => {
    expect(documentGates(doc([]), drafter).canEdit).toBe(true);
    expect(documentGates(doc([], {}, { status: "returned" }), drafter).canEdit).toBe(true);
    expect(documentGates(doc([], {}, { status: "pending" }), drafter).canEdit).toBe(false);
    expect(documentGates(doc([], {}, { status: "approved" }), drafter).canEdit).toBe(false);
  });
});
