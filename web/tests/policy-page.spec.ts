// /policy page: the policy library lives only in the existing /gov/policies (T1).
// Imports are reviewer-only, start unverified, and status labels follow human verification.
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { defineComponent, h } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/api.js", () => ({ default: api }));

import PolicyPage from "../src/views/PolicyPage.vue";

const Blank = defineComponent({ render: () => h("div") });
const today = new Date();
const iso = (d: Date) => d.toISOString().slice(0, 10);
const past = iso(new Date(today.getFullYear() - 2, 0, 1));
const future = iso(new Date(today.getFullYear() + 2, 0, 1));

const POLICIES = [
  { id: 1, title: "未核验办法", verified_status: "unverified", version: 1, doc_number: null },
  { id: 2, title: "现行办法", verified_status: "current", version: 2, doc_number: "示规〔2026〕1号", effective_date: past },
  { id: 3, title: "已到期办法", verified_status: "current", version: 1, expire_date: past },
  { id: 4, title: "未生效办法", verified_status: "current", version: 1, effective_date: future },
];

function setup(roles: string[]) {
  api.get.mockImplementation((url: string) => {
    if (url === "/gov/policies") return Promise.resolve({ data: { code: 0, data: { items: POLICIES, total: POLICIES.length } } });
    if (url === "/gov/policies/stats") return Promise.resolve({ data: { code: 0, data: { total: 4, current: 3, abolished: 0, unverified: 1 } } });
    if (url === "/gov/actor") return Promise.resolve({ data: { code: 0, data: { roles } } });
    return Promise.reject(new Error("unexpected GET " + url));
  });
}

async function mountPage() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: Blank }] });
  await router.push("/policy");
  const w = mount(PolicyPage, { global: { plugins: [createPinia(), router] } });
  await flushPromises();
  return w;
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
});

describe("PolicyPage on the existing policy library", () => {
  it("lists policies from /gov/policies with verification-based status labels", async () => {
    setup(["drafter"]);
    const w = await mountPage();
    const urls = api.get.mock.calls.map((c) => c[0]);
    expect(urls).toEqual(expect.arrayContaining(["/gov/policies", "/gov/policies/stats", "/gov/actor"]));
    expect(urls.some((u: string) => u.startsWith("/policy/"))).toBe(false);
    const rows = w.findAll(".gov-doc").map((r) => r.text());
    expect(rows[0]).toContain("待核实");
    expect(rows[1]).toContain("现行有效");
    expect(rows[2]).toContain("已废止");
    expect(rows[3]).toContain("尚未生效");
    expect(w.text()).toContain("待核实 1");
  });

  it("does not offer import to a drafter", async () => {
    setup(["drafter"]);
    const w = await mountPage();
    expect(w.find('button[aria-label="导入政策"]').exists()).toBe(false);
  });

  it("imports a reviewer's file and pasted text through /gov/policies/import as unverified", async () => {
    setup(["reviewer"]);
    api.post.mockResolvedValue({ data: { code: 0, data: { policy: { id: 9, title: "新办法" }, clause_count: 3, needs_review_count: 0 } } });
    const w = await mountPage();
    await w.get('button[aria-label="导入政策"]').trigger("click");
    await w.findAll("button").find((b) => b.text() === "粘贴正文")!.trigger("click");
    await w.get("textarea").setValue("示例办法\n第一条 为了规范管理，制定本办法。\n第二条 本办法自发布之日起施行。");
    await w.get('input[placeholder="文号"]').setValue("示规〔2026〕2号");
    await w.findAll("button").find((b) => b.text().includes("导入（待核实）"))!.trigger("click");
    await flushPromises();
    expect(api.post).toHaveBeenCalledTimes(1);
    const [url, form] = api.post.mock.calls[0];
    expect(url).toBe("/gov/policies/import");
    const file = (form as FormData).get("file") as File;
    expect(file.name).toBe("粘贴正文.txt");
    expect(await file.text()).toContain("第一条");
    expect((form as FormData).get("doc_number")).toBe("示规〔2026〕2号");
    expect(w.text()).toContain("状态：待核实");
    expect(w.text()).toContain("核验前不能作为现行依据");
  });

  it("shows the backend's refusal instead of reporting success", async () => {
    setup(["reviewer"]);
    api.post.mockResolvedValue({ data: { code: 40000, message: "PDF解析或OCR失败，未获取完整逐页正文；未写入政策" } });
    const w = await mountPage();
    await w.get('button[aria-label="导入政策"]').trigger("click");
    await w.findAll("button").find((b) => b.text() === "粘贴正文")!.trigger("click");
    await w.get("textarea").setValue("第一条 内容。");
    await w.findAll("button").find((b) => b.text().includes("导入（待核实）"))!.trigger("click");
    await flushPromises();
    expect(w.text()).toContain("未写入政策");
    expect(w.text()).not.toContain("已导入");
  });
});
