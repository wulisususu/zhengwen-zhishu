import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
import NoticeMetadataForm from "../../src/features/gov-office/components/draft/NoticeMetadataForm.vue";
import OfficialDocumentView from "../../src/features/gov-office/components/document/OfficialDocumentView.vue";
import { documentGates, issueActions } from "../../src/features/gov-office/domain/issueRules";
import type { OfficialDocument, Actor } from "../../src/features/gov-office/types";

const doc = { id: "real1", origin: "backend", docType: "notice", title: "通知", status: "pending", authorAccount: "writer",
  docNumber: { id: "real1-number", text: "办发〔2026〕8号" }, fields: { issuer: "测试办公室", recipient: "各单位", undertaker: "" },
  signDate: "2026年10月26日", blocks: [], issues: [], resolutions: {}, policyRefs: [],
} as unknown as OfficialDocument;
const actor = { account: "reviewer", roles: ["reviewer"], canFormalIssue: false } as Actor;

it("edits notice number and printer without dropping existing tables", async () => {
  const value = { docNumber: "办发〔2026〕8号", printer: "办公室", printDate: "2026年10月26日", copyTo: "", note: "", titleLines: "", tables: [{ caption: "任务", head: ["事项"], rows: [["甲"]] }] };
  const w = mount(NoticeMetadataForm, { props: { modelValue: value } });
  await w.get('[aria-label="发文字号"]').setValue("办发〔2026〕9号");
  const emitted = w.emitted("update:modelValue")!.at(-1)![0] as typeof value;
  expect(emitted.docNumber).toBe("办发〔2026〕9号");
  expect(emitted.tables).toEqual(value.tables);
  expect(w.get('[aria-label="表格1第1行第1列"]').element).toBeTruthy();
});

it("previews exact table, title and banji anchors used by the backend", () => {
  const w = mount(OfficialDocumentView, { props: { doc: { ...doc, banji: { printer: "办公室", printDate: "2026年10月26日", copyTo: ["有关单位"] }, blocks: [{ id: "real1-t0", kind: "table", section: "正文", segments: [], table: { caption: "任务", head: ["事项"], rows: [["甲"]] } }] }, marks: {}, focusAnchor: "real1-t0" } });
  expect(w.get('[data-anchor="real1-t0"]').text()).toContain("甲");
  expect(w.get('[data-anchor="real1-banji"]').text()).toContain("办公室");
  expect(w.find('[data-anchor="real1-title"]').exists()).toBe(true);
});

it("does not offer unsupported exception or ignore operations for backend findings", () => {
  const issue = { id: "problem", severity: "critical", source: "rule", title: "问题", description: "", anchor: "real1-t0", section: "body", locationLabel: "表格" } as const;
  expect(issueActions(issue, doc, actor)).toEqual(["locate"]);
});

it("blocks approval when real format tool failed even with no displayed findings", () => {
  const d = { ...doc, review: { formatCheck: { status: "unavailable" }, gate: { canApprove: false, reasons: ["格式机检未完成"] } } } as OfficialDocument;
  const result = documentGates(d, actor);
  expect(result.canApprove).toBe(false);
  expect(result.approveBlockedReason).toContain("格式机检未完成");
});
