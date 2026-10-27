// 政策问答对话式改造：范围默认值、未核验前提、对话气泡、点选建议、多轮上下文。
// 对应计划 docs/superpowers/plans/2026-10-27-policy-qa-conversational.md 的 Task 5。
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { defineComponent, h } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/api.js", () => ({ default: api }));

import PolicyPage from "../src/views/PolicyPage.vue";

const Blank = defineComponent({ render: () => h("div") });

const NOTICE = "以下内容来自已入库但尚未经人工核验的政策，仅供参考；正式引用前，请审核人在政策库完成核验。";

const POLICIES = [
  { id: 1, title: "未核验办法", verified_status: "unverified", version: 1, doc_number: null },
  { id: 2, title: "现行办法", verified_status: "current", version: 2, doc_number: "示规〔2026〕1号" },
];

function setup() {
  api.get.mockImplementation((url: string) => {
    if (url === "/gov/policies") return Promise.resolve({ data: { code: 0, data: { items: POLICIES, total: POLICIES.length } } });
    if (url === "/gov/policies/stats") return Promise.resolve({ data: { code: 0, data: { total: 2, current: 1, abolished: 0, unverified: 1 } } });
    if (url === "/gov/actor") return Promise.resolve({ data: { code: 0, data: { roles: ["drafter"] } } });
    return Promise.reject(new Error("unexpected GET " + url));
  });
}

const sse = (...events: unknown[]) =>
  events.map((e) => "data: " + JSON.stringify(e)).join("\n\n") + "\n\n";

function streamResponder(respond: (call: number) => string) {
  const calls: Array<{ url: string; options: any }> = [];
  const fetcher = vi.fn((url: string, options: any) => {
    calls.push({ url, options });
    return Promise.resolve(new Response(respond(calls.length), { headers: { "Content-Type": "text/event-stream" } }));
  });
  vi.stubGlobal("fetch", fetcher);
  return calls;
}

async function mountPage() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: Blank }] });
  await router.push("/policy");
  const w = mount(PolicyPage, { global: { plugins: [createPinia(), router] } });
  await flushPromises();
  return w;
}

async function settle() {
  await flushPromises();
  await new Promise((r) => setTimeout(r, 0));
  await flushPromises();
}

async function ask(w: Awaited<ReturnType<typeof mountPage>>, question: string) {
  await w.get(".gov-composer-input").setValue(question);
  await w.get(".gov-send").trigger("click");
  await settle();
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("PolicyPage conversational policy QA", () => {
  it("defaults to the whole library and no longer promises a trial search", async () => {
    setup();
    const w = await mountPage();
    const select = w.get("select.gov-select").element as HTMLSelectElement;
    expect(select.value).toBe("all");
    const options = Array.from(select.options).map((o) => o.text);
    expect(options).toContain("全部入库政策（已核验优先）");
    expect(options).toContain("仅已核验现行政策");
    expect(w.text()).not.toContain("试查");
  });

  it("shows the backend's unverified notice above the conclusion and in the copied text", async () => {
    setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const citation = { index: 1, clause_id: 5, policy_title: "未核验办法", clause_no: "第六条", status: "待核实", excerpt: { pre: "", hl: "百分之五十", post: "" } };
    streamResponder(() => sse(
      { type: "evidence", citations: [citation], basis: "unverified", basis_notice: NOTICE, meta: { candidates: 1 } },
      { type: "final", data: { status: "answered", basis: "unverified", basis_notice: NOTICE, sufficient: true, sufficiency: "partial", conclusion: "贴息比例为百分之五十[1]。", citations: [citation], manual_confirm: [], candidates: [], meta: { candidates: 1, mode: "answer", generated_by: "extractive_numeric" } } },
    ));
    const w = await mountPage();
    await ask(w, "小微企业贴息比例是多少");
    expect(w.get(".gov-basis-notice").text()).toBe(NOTICE);
    expect(w.text()).toContain("依据未核验");
    await w.findAll("button").find((b) => b.text().includes("复制回答"))!.trigger("click");
    expect(writeText).toHaveBeenCalled();
    expect(writeText.mock.calls[0][0]).toBe(NOTICE + "\n贴息比例为百分之五十[1]。");
  });

  it("renders chat replies and applies the final replacement", async () => {
    setup();
    streamResponder(() => sse(
      { type: "mode", mode: "chat" },
      { type: "delta", text: "根据《不存在办法》可以申请。" },
      { type: "replace", text: "政策库里暂时没有找到和这个问题直接相关的内容。" },
      { type: "final", data: { status: "chat", reply: "政策库里暂时没有找到和这个问题直接相关的内容。", suggestions: [], scope_hint: "", citations: [], meta: { generated_by: "chat_fallback", kind: "policy" } } },
    ));
    const w = await mountPage();
    await ask(w, "有没有人才公寓补贴");
    expect(w.get(".gov-chat-bubble").text()).toContain("政策库里暂时没有找到");
    expect(w.text()).not.toContain("不存在办法");
    expect(w.text()).not.toContain("未找到足够依据");
  });

  it("asks about a suggested policy when it is clicked", async () => {
    setup();
    const calls = streamResponder((n: number) => {
      if (n === 1) {
        return sse(
          { type: "mode", mode: "chat" },
          { type: "final", data: { status: "chat", reply: "库里没有直接相关的内容。", suggestions: [{ policy_id: 2, title: "现行办法", status: "现行有效" }], scope_hint: "", citations: [], meta: { generated_by: "chat_fallback", kind: "policy" } } });
      }
      return sse({ type: "final", data: { status: "answered", basis: "verified", basis_notice: "", sufficient: true, sufficiency: "full", conclusion: "《现行办法》的主要内容如上[1]。", citations: [{ index: 1, clause_id: 9, policy_title: "现行办法", clause_no: "第一条", status: "现行有效", excerpt: { pre: "", hl: "现行", post: "" } }], candidates: [], meta: { mode: "overview", generated_by: "extractive_overview" } } });
    });
    const w = await mountPage();
    await ask(w, "帮我看看现行办法");
    expect(w.findAll(".gov-suggestion").length).toBe(1);
    await w.get(".gov-suggestion").trigger("click");
    await settle();
    expect(calls.length).toBe(2);
    const body = JSON.parse(calls[1].options.body);
    expect(body.scope).toBe("policy");
    expect(body.policy_ids).toEqual([2]);
    expect(body.question).toBe("介绍一下《现行办法》");
  });

  it("sends the last three finished turns as history", async () => {
    setup();
    const calls = streamResponder((n: number) => sse(
      { type: "mode", mode: "chat" },
      { type: "final", data: { status: "chat", reply: "回复" + n, suggestions: [], scope_hint: "", citations: [], meta: { generated_by: "chat_fallback", kind: "policy" } } }));
    const w = await mountPage();
    for (const q of ["问题1", "问题2", "问题3", "问题4"]) await ask(w, q);
    await ask(w, "问题5");
    expect(calls.length).toBe(5);
    const body = JSON.parse(calls[4].options.body);
    expect(body.history.length).toBe(3);
    expect(body.history[0]).toEqual({ question: "问题2", answer: "回复2" });
    expect(body.history[2]).toEqual({ question: "问题4", answer: "回复4" });
  });
});
