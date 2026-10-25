import { beforeEach, describe, expect, it } from "vitest";
import { createMockGovOfficeAdapter } from "../../src/features/gov-office/adapters/MockGovOfficeAdapter";
import { GovOfficeError } from "../../src/features/gov-office/adapters/GovOfficeAdapter";
import type { GovOfficeAdapter } from "../../src/features/gov-office/adapters/GovOfficeAdapter";

const NOTICE = "demo-d1";

describe("MockGovOfficeAdapter", () => {
  let adapter: GovOfficeAdapter;
  beforeEach(() => {
    adapter = createMockGovOfficeAdapter();
  });

  it("marks everything it returns as demo data", async () => {
    expect(adapter.mode).toBe("mock");
    const docs = await adapter.listDocuments();
    expect(docs.every((d) => d.origin === "demo")).toBe(true);
    expect((await adapter.listQaSessions()).every((s) => s.origin === "demo")).toBe(true);
    expect((await adapter.getCurrentActor()).origin).toBe("demo");
  });

  it("does not invent a model runtime state", async () => {
    const status = await adapter.getRuntimeStatus();
    expect(status.modelMode).toBe("unknown");
    expect(status.label).toBe("演示环境 · 模型状态未知");
  });

  it("does not fabricate answers for new questions", async () => {
    const turn = await adapter.askPolicyQuestion("s1", "申请贴息需要哪些材料？", { scope: "current", excludeAbolished: true });
    expect(turn.answer.kind).toBe("unavailable");
    expect(turn.answer.citationIds).toEqual([]);
  });

  it("filters documents by keyword and type", async () => {
    expect((await adapter.listDocuments({ keyword: "请示" })).map((d) => d.id)).toEqual(["demo-d3"]);
    expect((await adapter.listDocuments({ docType: "report" })).map((d) => d.id)).toEqual(["demo-d2", "demo-d7"]);
  });

  it("returns copies so callers cannot mutate adapter state", async () => {
    const doc = await adapter.getDocument(NOTICE);
    doc.title = "changed";
    expect((await adapter.getDocument(NOTICE)).title).not.toBe("changed");
  });

  it("applies a suggestion to the text and records it as fixed", async () => {
    const doc = await adapter.applySuggestion(NOTICE, "d1-i2");
    const cite = doc.blocks.flatMap((b) => b.segments).find((s) => s.kind === "text" && s.id === "seg-cite");
    expect(cite && cite.kind === "text" ? cite.text : "").toContain("第十五条");
    expect(doc.resolutions["d1-i2"].kind).toBe("fixed");
    expect(doc.policyRefs.map((p) => p.id)).toContain("p-share-15");
    expect(doc.policyRefs.map((p) => p.id)).not.toContain("p-share-old-12");
  });

  it("updates the document number through its suggestion", async () => {
    const doc = await adapter.applySuggestion(NOTICE, "d1-i1");
    expect(doc.docNumber.text).toBe("示数办〔2025〕7号");
  });

  it("refuses to apply the suggestion of an AI critical issue before human review", async () => {
    await expect(adapter.applySuggestion(NOTICE, "d1-i5")).rejects.toBeInstanceOf(GovOfficeError);
    await adapter.resolveIssue(NOTICE, "d1-i5", { kind: "ai_confirmed", by: "x", at: "t" });
    const doc = await adapter.applySuggestion(NOTICE, "d1-i5");
    expect(doc.resolutions["d1-i5"].kind).toBe("fixed");
  });

  it("rejects ignoring a critical issue", async () => {
    await expect(adapter.resolveIssue(NOTICE, "d1-i1", { kind: "hint_ignored", by: "x", at: "t" })).rejects.toMatchObject({ code: "illegal_resolution" });
  });

  it("requires a reason for exceptions and AI dismissals", async () => {
    await expect(adapter.resolveIssue(NOTICE, "d1-i1", { kind: "exception_requested", by: "x", reason: " ", at: "t" })).rejects.toMatchObject({ code: "reason_required" });
    await expect(adapter.resolveIssue(NOTICE, "d1-i5", { kind: "ai_dismissed", by: "x", reason: "", at: "t" })).rejects.toMatchObject({ code: "reason_required" });
  });

  it("drives status by actions and records history", async () => {
    const submitted = await adapter.submitForReview(NOTICE);
    expect(submitted.status).toBe("pending");
    expect(submitted.history.at(-1)?.action).toBe("提交审核");
    await expect(adapter.updateFields(NOTICE, { recipient: "x" })).rejects.toMatchObject({ code: "locked" });
  });

  it("starts as demo_drafter and can switch to demo_reviewer", async () => {
    expect((await adapter.getCurrentActor()).account).toBe("demo_drafter");
    expect((await adapter.listDemoActors!()).map((a) => a.account)).toEqual(["demo_drafter", "demo_reviewer"]);
    const reviewer = await adapter.switchDemoActor!("demo_reviewer");
    expect(reviewer.roles).toEqual(["reviewer"]);
    expect((await adapter.getCurrentActor()).account).toBe("demo_reviewer");
  });

  it("keeps drafter and reviewer powers apart", async () => {
    await expect(adapter.approve("demo-d2", "")).rejects.toThrow("没有审核权限");
    await adapter.switchDemoActor!("demo_reviewer");
    await expect(adapter.updateFields(NOTICE, { recipient: "x" })).rejects.toMatchObject({ code: "forbidden" });
    await expect(adapter.submitForReview(NOTICE)).rejects.toMatchObject({ code: "forbidden" });
    await expect(adapter.resolveIssue(NOTICE, "d1-i1", { kind: "exception_requested", by: "x", reason: "r", at: "t" })).rejects.toMatchObject({ code: "forbidden" });
  });

  it("records actions under the acting identity", async () => {
    await adapter.submitForReview(NOTICE);
    await adapter.switchDemoActor!("demo_reviewer");
    const doc = await adapter.returnForRevision(NOTICE, "请补充主送机关");
    expect(doc.history.at(-2)?.actor).toBe("演示起草人");
    expect(doc.history.at(-1)?.actor).toBe("演示审核人");
  });

  it("blocks approval while critical issues remain", async () => {
    await adapter.submitForReview(NOTICE);
    await adapter.switchDemoActor!("demo_reviewer");
    await expect(adapter.approve(NOTICE, "")).rejects.toMatchObject({ code: "blocked" });
  });

  it("requires an opinion to return a document", async () => {
    await adapter.switchDemoActor!("demo_reviewer");
    await expect(adapter.returnForRevision("demo-d2", "  ")).rejects.toMatchObject({ code: "opinion_required" });
    const doc = await adapter.returnForRevision("demo-d2", "请补充下一步工作安排");
    expect(doc.status).toBe("returned");
    expect(doc.history.at(-1)?.note).toContain("请补充下一步工作安排");
  });

  it("approves a document without blockers", async () => {
    await adapter.switchDemoActor!("demo_reviewer");
    const doc = await adapter.approve("demo-d2", "同意");
    expect(doc.status).toBe("approved");
  });

  it("never claims to generate files", async () => {
    const internal = await adapter.exportDocument(NOTICE, "internal_draft");
    expect(internal.generated).toBe(false);
    expect(internal.watermark).toBe("未审核 · 内部草稿");
    await expect(adapter.exportDocument(NOTICE, "formal")).rejects.toMatchObject({ code: "formal_export_blocked" });
  });

  it("adds and removes materials", async () => {
    let doc = await adapter.addMaterials(NOTICE, ["m3"]);
    expect(doc.materials.map((m) => m.id)).toContain("m3");
    doc = await adapter.removeMaterial(NOTICE, "m3");
    expect(doc.materials.map((m) => m.id)).not.toContain("m3");
  });
});
