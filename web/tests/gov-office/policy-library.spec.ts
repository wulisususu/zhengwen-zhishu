import { mount, flushPromises } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ listPolicies: vi.fn(), searchPolicies: vi.fn(), getPolicy: vi.fn(), getCurrentActor: vi.fn(), listDocuments: vi.fn(), importPolicy: vi.fn(), getPolicyStats: vi.fn(), verifyPolicy: vi.fn() }));
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
  api.getPolicyStats.mockResolvedValue({ origin: "backend", total: 1, current: 0, abolished: 0, unverified: 1 });
});
it("shows real source and exact clause and emits its stable ID for a draft", async () => {
  const w = mount(PolicyLibraryPanel, { props: { documentId: "draft-1" } });
  await flushPromises();
  await w.get('[data-testid="policy-open-1"]').trigger("click"); await flushPromises();
  expect(w.text()).toContain("第一条 数据应分类管理。");
  expect(w.get('a[href="https://www.gov.cn/zhengce/policy.htm"]').text()).toContain("打开官方原文");
  await w.get('[data-testid="select-clause-7"]').trigger("click");
  expect(w.emitted("select")?.[0]).toEqual(["clause:7"]);
  expect(w.get(".policy-detail").text()).toContain("状态待核实");
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
  await (w.vm as unknown as { openImport: () => Promise<void> }).openImport(); await flushPromises();
  const input = w.get('[aria-label="上传政策文件"]');
  expect(input.attributes("accept")).toContain(".pdf");
  Object.defineProperty(input.element, "files", { value: [new File(["%PDF"], "policy.pdf", { type: "application/pdf" })] });
  await input.trigger("change");
  await w.get("form.policy-import").trigger("submit"); await flushPromises();
  expect(w.text()).toContain("已使用原 OCR 回退链路");
  expect(w.text()).toContain("PDF 第 2 页");
});

const reviewer = { roles: ["reviewer"], account: "reviewer" };
const mountAs = async (actor?: object, props = {}) => {
  if (actor) api.getCurrentActor.mockResolvedValue(actor);
  const w = mount(PolicyLibraryPanel, { props, attachTo: document.body }); await flushPromises(); return w;
};

it("filters files and clauses by status and shows the library counts", async () => {
  api.getPolicyStats.mockResolvedValue({ origin: "backend", total: 101, current: 0, abolished: 0, unverified: 101 });
  const w = await mountAs();
  const filters = w.findAll(".policy-filter");
  expect(filters.map(f => f.text())).toEqual(["全部101", "待核实101", "现行0", "已废止0"]);
  expect(api.listPolicies).toHaveBeenLastCalledWith("", { statuses: [] });
  await w.get('[aria-label="政策检索词"]').setValue("数据");
  await filters[1].trigger("click"); await flushPromises();
  expect(filters[1].attributes("aria-pressed")).toBe("true");
  expect(api.listPolicies).toHaveBeenLastCalledWith("数据", { statuses: ["unverified"] });
  expect(api.searchPolicies).toHaveBeenLastCalledWith("数据", ["unverified"]);
  w.unmount();
});

it("searches every status by default and switches to clause hits when there are some", async () => {
  api.searchPolicies.mockResolvedValue({ hits: [{ citation_id: "clause:7", policy_id: 1, policy_title: "数据管理办法", clause: "第一条", status: "unverified", excerpt: { before: "", highlight: "数据", after: "应分类管理。" } }] });
  const w = await mountAs();
  await w.get('[aria-label="政策检索词"]').setValue("数据");
  await w.get('[data-testid="policy-search"]').trigger("submit"); await flushPromises();
  expect(api.searchPolicies).toHaveBeenLastCalledWith("数据", ["current", "unverified", "abolished"]);
  expect(w.get('[role="tab"][aria-selected="true"]').text()).toBe("条款命中 1");
  expect(w.text()).toContain("应分类管理。");
  w.unmount();
});

it("loads the next page of files instead of capping the list", async () => {
  api.listPolicies.mockResolvedValueOnce({ items: [policy], total: 2 }).mockResolvedValueOnce({ items: [{ ...policy, id: 2, title: "第二页政策" }], total: 2 });
  const w = await mountAs();
  await w.get(".policy-more").trigger("click"); await flushPromises();
  expect(api.listPolicies).toHaveBeenLastCalledWith("", { statuses: [], page: 2 });
  expect(w.text()).toContain("第二页政策");
  expect(w.find(".policy-more").exists()).toBe(false);
  w.unmount();
});

it("offers import to a reviewer through a drawer and sends the optional metadata", async () => {
  api.importPolicy.mockResolvedValue({ policy });
  const w = await mountAs(reviewer);
  expect(w.emitted("import-available")?.[0]).toEqual([true]);
  expect(w.find('[data-testid="policy-import"]').exists()).toBe(false);
  await (w.vm as unknown as { openImport: (mode: string) => Promise<void> }).openImport("url"); await flushPromises();
  await w.get('[aria-label="政策原文网址"]').setValue("https://www.gov.cn/zhengce/a.htm");
  await w.get('[aria-label="导入政策文号"]').setValue("国办发〔2025〕1号");
  await w.get("form.policy-import").trigger("submit"); await flushPromises();
  const form = api.importPolicy.mock.calls[0][0] as FormData;
  expect(form.get("url")).toBe("https://www.gov.cn/zhengce/a.htm");
  expect(form.get("doc_number")).toBe("国办发〔2025〕1号");
  expect(w.find('[data-testid="policy-import"]').exists()).toBe(false);
  w.unmount();
});

it("keeps import away from drafters and puts the target draft in the toolbar", async () => {
  const w = await mountAs();
  expect(w.emitted("import-available")?.[0]).toEqual([false]);
  await (w.vm as unknown as { openImport: () => Promise<void> }).openImport(); await flushPromises();
  expect(w.find('[data-testid="policy-import"]').exists()).toBe(false);
  expect(w.get(".policy-toolbar").find('[aria-label="引用目标文稿"]').exists()).toBe(true);
  w.unmount();
});

it("docks verification under the clauses and moves to the next unverified policy", async () => {
  const next = { ...policy, id: 2, title: "下一份政策" };
  api.listPolicies.mockResolvedValue({ items: [policy, { ...policy, id: 3, verified_status: "current" }, next], total: 3 });
  api.verifyPolicy.mockResolvedValue({ policy });
  const w = await mountAs(reviewer);
  await w.get('[data-testid="policy-open-1"]').trigger("click"); await flushPromises();
  const dock = w.get(".policy-detail form.policy-verify");
  await dock.get('input[value="current"]').setValue(true);
  await dock.get('[aria-label="核验依据与说明"]').setValue("已对照官网原文");
  await dock.trigger("submit"); await flushPromises();
  expect(api.verifyPolicy).toHaveBeenCalledWith(1, "current", "已对照官网原文");
  api.getPolicy.mockResolvedValueOnce({ policy: next, clauses: [] });
  await w.findAll("form.policy-verify button").find(b => b.text().includes("下一份待核实"))!.trigger("click"); await flushPromises();
  expect(api.getPolicy).toHaveBeenLastCalledWith(2);
  w.unmount();
});

it("guides the first import when the library is empty", async () => {
  api.listPolicies.mockResolvedValue({ items: [], total: 0 });
  const asReviewer = await mountAs(reviewer);
  expect(asReviewer.text()).toContain("政策库里还没有文件");
  await asReviewer.findAll(".policy-empty button").find(b => b.text() === "从官方网址导入")!.trigger("click"); await flushPromises();
  expect(asReviewer.find('[aria-label="政策原文网址"]').exists()).toBe(true);
  asReviewer.unmount();
  const asDrafter = await mountAs({ account: "writer", roles: ["drafter"] });
  expect(asDrafter.text()).toContain("请联系审核人导入");
  expect(asDrafter.find(".policy-empty button").exists()).toBe(false);
  asDrafter.unmount();
});
