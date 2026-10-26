// /gongwen page: drafting only. Results are saved as /gov/documents; notices continue in the
// existing workbench (layered review, submit, approval); exports always use the saved version.
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { defineComponent, h } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/api.js", () => ({ default: api }));

import GongwenPage from "../src/views/GongwenPage.vue";

const Blank = defineComponent({ render: () => h("div") });

function ir(docType: string) {
  return {
    doc_type: docType, title: `关于测试事项的${docType}`, recipients: ["示例市财政局"], issuer_org: "示例市数据管理局",
    signer_org: "示例市数据管理局", sign_date: "2026年10月26日", doc_number: "示数发〔2026〕3号",
    body: [{ text: "一、基本情况", level: 1 }, { text: "目前平台运维经费不足。", level: 0 }],
    cc: [], print_org: "", print_date: "", note: "",
  };
}

function setup(roles: string[], docType: string) {
  api.get.mockResolvedValue({ data: { code: 0, data: { roles } } });
  api.post.mockImplementation((url: string, body: unknown) => {
    if (url === "/gongwen/draft") return Promise.resolve({ data: { code: 0, data: { ir: ir(docType), issues: [], stats: { error: 0, warn: 0, info: 0 }, summary: { char_count: 20 }, meta: { generated_by: "llm", elapsed_ms: 10 } } } });
    if (url === "/gov/documents") return Promise.resolve({ data: { code: 0, data: { id: "doc-1", version: 1, docType: (body as { docType: string }).docType } } });
    if (url === "/gov/documents/doc-1/export") return Promise.resolve({ data: new Blob(["docx"]), headers: {} });
    return Promise.reject(new Error("unexpected POST " + url));
  });
}

async function mountPage(docType: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: Blank }] });
  await router.push("/gongwen");
  const w = mount(GongwenPage, { global: { plugins: [createPinia(), router] } });
  await flushPromises();
  await w.findAll("button").find((b) => b.text() === docType)!.trigger("click");
  await w.get("textarea").setValue("测试事项");
  await w.findAll("button").find((b) => b.text().includes("生成正文"))!.trigger("click");
  await flushPromises();
  return { w, router };
}

const button = (w: ReturnType<typeof mount>, text: string) => w.findAll("button").find((b) => b.text().includes(text))!;

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
  window.alert = vi.fn();
});

describe("GongwenPage saves into the existing document flow", () => {
  it("cannot export before saving and never calls the removed render endpoint", async () => {
    setup(["drafter"], "请示");
    const { w } = await mountPage("请示");
    expect(button(w, "导出内部草稿").attributes("disabled")).toBeDefined();
    expect(api.post.mock.calls.some(([u]) => String(u).startsWith("/gongwen/render"))).toBe(false);
  });

  it("saves a notice and continues in the workbench for review, submit and approval", async () => {
    sessionStorage.setItem("mqw-gongwen-references", JSON.stringify([{ citation_id: "clause:7", policy_title: "办法", clause_no: "第六条" }]));
    setup(["drafter"], "通知");
    const { w, router } = await mountPage("通知");
    await button(w, "保存并进入审校").trigger("click");
    await flushPromises();
    const [, payload] = api.post.mock.calls.find(([u]) => u === "/gov/documents")!;
    expect(payload).toMatchObject({
      title: "关于测试事项的通知", docType: "notice", citationIds: ["clause:7"],
      fields: { recipient: "示例市财政局", issuer: "示例市数据管理局" }, signDate: "2026年10月26日",
      docNumber: { text: "示数发〔2026〕3号" },
    });
    expect((payload as { body: string }).body).toBe("一、基本情况\n目前平台运维经费不足。");
    expect(router.currentRoute.value.path).toBe("/gov/draft/doc-1");
  });

  it("saves other types as internal drafts and exports the saved version with the mark", async () => {
    setup(["drafter"], "请示");
    const { w } = await mountPage("请示");
    await button(w, "保存为文稿").trigger("click");
    await flushPromises();
    expect(w.text()).toContain("已保存为内部草稿");
    await button(w, "导出内部草稿").trigger("click");
    await flushPromises();
    const exportCall = api.post.mock.calls.find(([u]) => u === "/gov/documents/doc-1/export")!;
    expect(exportCall[1]).toEqual({ kind: "internal_draft" });
  });

  it("does not let the reviewer role save drafts", async () => {
    setup(["reviewer"], "通知");
    const { w } = await mountPage("通知");
    expect(button(w, "保存并进入审校").attributes("disabled")).toBeDefined();
  });
});
