import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { defineComponent, h } from "vue";
import { ENTRY_PATH, entryGuard } from "../../src/roleEntryGuard.js";
import RoleEntryPage from "../../src/features/gov-office/pages/RoleEntryPage.vue";
import { setGovOfficeAdapter } from "../../src/features/gov-office/adapters";
import { createMockGovOfficeAdapter } from "../../src/features/gov-office/adapters/MockGovOfficeAdapter";
import { useGovSessionStore, resetGovSessionLoading } from "../../src/features/gov-office/stores/govSession";

const Blank = defineComponent({ render: () => h("div") });
const OPTIONS = {
  code: 0,
  data: {
    enabled: true,
    roles: [
      { role: "drafter", label: "起草人", description: "起草通知" },
      { role: "reviewer", label: "审核人", description: "审核送审文稿" },
    ],
  },
};

function respond(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: ENTRY_PATH, component: RoleEntryPage },
      { path: "/gov/draft", component: Blank },
      { path: "/gov/review-center", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
}

async function mountEntry(fetcher: ReturnType<typeof vi.fn>, query = "") {
  vi.stubGlobal("fetch", fetcher);
  const router = makeRouter();
  await router.push(ENTRY_PATH + query);
  const wrapper = mount(RoleEntryPage, { global: { plugins: [router] } });
  await flushPromises();
  return { wrapper, router };
}

const session = () => JSON.parse(localStorage.getItem("mqw-session") || "{}");

beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
});
afterEach(() => vi.unstubAllGlobals());

describe("entry guard (no login page)", () => {
  it("sends every protected page to the role entry when there is no session", () => {
    expect(entryGuard({ path: "/gov" }, false)).toEqual({ path: "/entry" });
    expect(entryGuard({ path: "/gov/review-center" }, false)).toEqual({ path: "/entry" });
    expect(entryGuard({ path: "/chat" }, false)).toEqual({ path: "/entry" });
  });

  it("keeps the entry and welcome pages public and lets a session through", () => {
    expect(entryGuard({ path: "/entry" }, false)).toBe(true);
    expect(entryGuard({ path: "/welcome" }, false)).toBe(true);
    expect(entryGuard({ path: "/gov" }, true)).toBe(true);
    expect(entryGuard({ path: "/entry" }, true)).toBe(true);   // switching role stays possible
  });
});

describe("RoleEntryPage", () => {
  it("shows the two roles and no account or password fields", async () => {
    const { wrapper } = await mountEntry(vi.fn(() => respond(200, OPTIONS)));
    const buttons = wrapper.findAll("button[data-role]");
    expect(buttons.map((b) => b.attributes("data-role"))).toEqual(["drafter", "reviewer"]);
    expect(wrapper.text()).toContain("起草人");
    expect(wrapper.text()).toContain("审核人");
    expect(wrapper.text()).toContain("不是身份认证");
    expect(wrapper.find("input").exists()).toBe(false);
  });

  it.each([
    ["drafter", "/gov/draft"],
    ["reviewer", "/gov/review-center"],
  ])("%s enters its own workflow with a backend session", async (role, home) => {
    const fetcher = vi.fn((_url: string, init?: RequestInit) => init?.method === "POST"
      ? respond(200, { code: 0, data: { access_token: `tok-${role}`, token_type: "bearer", role } })
      : respond(200, OPTIONS));
    const { wrapper, router } = await mountEntry(fetcher);
    await wrapper.get(`button[data-role="${role}"]`).trigger("click");
    await flushPromises();
    const post = fetcher.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(post[0]).toBe("/api/v1/gov/entry");
    expect(JSON.parse(String(post[1]!.body))).toEqual({ role });
    expect(session()).toMatchObject({ token: `tok-${role}`, role });
    expect(router.currentRoute.value.path).toBe(home);
  });

  it("does not store a session when the backend refuses", async () => {
    const fetcher = vi.fn((_url: string, init?: RequestInit) => init?.method === "POST"
      ? respond(409, { detail: "角色账号与已有账号冲突，请联系系统维护人员" })
      : respond(200, OPTIONS));
    const { wrapper, router } = await mountEntry(fetcher);
    await wrapper.get('button[data-role="reviewer"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("角色账号与已有账号冲突");
    expect(localStorage.getItem("mqw-session")).toBeNull();
    expect(router.currentRoute.value.path).toBe("/entry");
  });

  it("disables both roles when the entry is switched off", async () => {
    const { wrapper } = await mountEntry(vi.fn(() => respond(200, { code: 0, data: { ...OPTIONS.data, enabled: false } })));
    expect(wrapper.text()).toContain("角色入口未开启");
    expect(wrapper.findAll("button[data-role]").every((b) => b.attributes("disabled") !== undefined)).toBe(true);
  });

  it("explains an expired session", async () => {
    const { wrapper } = await mountEntry(vi.fn(() => respond(200, OPTIONS)), "?expired=1");
    expect(wrapper.text()).toContain("会话已失效，请重新选择角色");
  });
});

describe("demo build follows the chosen role", () => {
  it("starts the mock as the reviewer when the reviewer role was chosen", async () => {
    localStorage.setItem("mqw-session", JSON.stringify({ token: "demo-reviewer", role: "reviewer" }));
    setGovOfficeAdapter(createMockGovOfficeAdapter());
    resetGovSessionLoading();
    const store = useGovSessionStore();
    await store.load();
    expect(store.isReviewer).toBe(true);
    expect(store.isDrafter).toBe(false);
    setGovOfficeAdapter(null);
  });
});
