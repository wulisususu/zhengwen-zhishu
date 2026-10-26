import { mount, flushPromises } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ listPolicies: vi.fn(), searchPolicies: vi.fn(), getPolicy: vi.fn(), getCurrentActor: vi.fn(), listDocuments: vi.fn(), importPolicy: vi.fn() }));
vi.mock("../../src/features/gov-office/adapters", () => ({ getGovOfficeAdapter: () => api }));
import PolicyLibraryPanel from "../../src/features/gov-office/components/policy/PolicyLibraryPanel.vue";
const policy = { id: 1, title: "数据管理办法", url: "https://www.gov.cn/zhengce/policy.htm", verified_status: "unverified", version: 1 };
beforeEach(() => {
  vi.clearAllMocks();
  api.listPolicies.mockResolvedValue({ items: [policy], total: 1 });
  api.searchPolicies.mockResolvedValue({ hits: [] });
  api.getPolicy.mockResolvedValue({ policy, clauses: [{ id: 7, sequence: 1, article_number: "第一条", content: "第一条 数据应分类管理。", needs_review: false }] });
  api.getCurrentActor.mockResolvedValue({ account: "writer", roles: ["drafter"] });
  api.listDocuments.mockResolvedValue([]);
});
it("shows real source and exact clause and emits its stable ID for a draft", async () => {
  const w = mount(PolicyLibraryPanel, { props: { documentId: "draft-1" } });
  await flushPromises();
  await w.get('[data-testid="policy-open-1"]').trigger("click"); await flushPromises();
  expect(w.text()).toContain("第一条 数据应分类管理。");
  expect(w.get('a[href="https://www.gov.cn/zhengce/policy.htm"]').text()).toContain("打开官方原文");
  await w.get('[data-testid="select-clause-7"]').trigger("click");
  expect(w.emitted("select")?.[0]).toEqual(["clause:7"]);
  expect(w.text()).toContain("未核验");
  expect(w.find('[data-testid="policy-import"]').exists()).toBe(false);
});
it("keeps an API error visible rather than replacing it with demo results", async () => {
  api.listPolicies.mockRejectedValue(new Error("政策库暂不可用"));
  const w = mount(PolicyLibraryPanel); await flushPromises();
  expect(w.get('[role="alert"]').text()).toContain("政策库暂不可用");
});
it("explicitly warns when viewing a superseded policy version", async () => {
  api.getPolicy.mockResolvedValue({ policy: { ...policy, is_current: false, superseded_by: 2 }, clauses: [] });
  const w = mount(PolicyLibraryPanel); await flushPromises();
  await w.get('[data-testid="policy-open-1"]').trigger("click"); await flushPromises();
  expect(w.text()).toContain("历史版本"); expect(w.text()).toContain("已被替代");
});
it("ignores an older query that completes after a newer query", async () => {
  const w = mount(PolicyLibraryPanel); await flushPromises();
  let finishOld: (value: unknown) => void = () => {};
  api.listPolicies.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; }));
  await w.get('[aria-label="政策检索词"]').setValue("旧");
  await w.get('[data-testid="policy-search"]').trigger("submit");
  api.listPolicies.mockResolvedValueOnce({ items: [{ ...policy, id: 2, title: "最新政策" }], total: 1 });
  await w.get('[aria-label="政策检索词"]').setValue("新");
  await w.get('[data-testid="policy-search"]').trigger("submit"); await flushPromises();
  finishOld({ items: [{ ...policy, title: "过期搜索" }], total: 1 }); await flushPromises();
  expect(w.text()).toContain("最新政策"); expect(w.text()).not.toContain("过期搜索");
});

it("accepts PDF imports and shows OCR fallback and source-page warnings", async () => {
  api.getCurrentActor.mockResolvedValue({ roles: ["reviewer"], account: "reviewer" });
  api.importPolicy.mockResolvedValue({ policy, extraction: { page_count: 2, parser: "poppler_pdf_hybrid", fallback: true, warnings: ["逐页人工复核"] } });
  api.getPolicy.mockResolvedValue({ policy, clauses: [{ id: 7, sequence: 1, content: "原文", needs_review: true, page_number: 2, source_anchor: "PDF第2页 / sha256:example" }] });
  const w = mount(PolicyLibraryPanel); await flushPromises();
  const input = w.get('[aria-label="上传政策文件"]');
  expect(input.attributes("accept")).toContain(".pdf");
  Object.defineProperty(input.element, "files", { value: [new File(["%PDF"], "policy.pdf", { type: "application/pdf" })] });
  await input.trigger("change");
  await w.get("form.policy-import").trigger("submit"); await flushPromises();
  expect(w.text()).toContain("已使用原 OCR 回退链路");
  expect(w.text()).toContain("PDF 第 2 页");
});
