import { beforeEach, describe, expect, it } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import IssuePanel from "../../src/features/gov-office/components/review/IssuePanel.vue";
import { setGovOfficeAdapter } from "../../src/features/gov-office/adapters";
import { createMockGovOfficeAdapter } from "../../src/features/gov-office/adapters/MockGovOfficeAdapter";
import { useGovDocumentsStore } from "../../src/features/gov-office/stores/govDocuments";
import type { Actor } from "../../src/features/gov-office/types";

const drafter: Actor = { origin: "demo", account: "demo_drafter", name: "演示起草人", department: "综合处", roles: ["drafter"], canFormalIssue: false };

async function mountPanel() {
  const store = useGovDocumentsStore();
  const doc = await store.load("demo-d1");
  const wrapper = mount(IssuePanel, {
    props: { doc: doc!, actor: drafter, focusAnchor: "", editable: true },
    attachTo: document.body,
  });
  return { store, wrapper };
}

function cardsWithTag(wrapper: ReturnType<typeof mount>, tag: string) {
  return wrapper.findAll("article.gov-issue").filter((card) => card.findAll(".gov-tag").some((t) => t.text() === tag));
}

describe("IssuePanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    setGovOfficeAdapter(createMockGovOfficeAdapter());
  });

  it("does not render an ignore button on any critical issue", async () => {
    const { wrapper } = await mountPanel();
    const critical = cardsWithTag(wrapper, "严重");
    expect(critical.length).toBe(5);
    for (const card of critical) {
      expect(card.findAll("button").map((b) => b.text())).not.toContain("忽略提示");
    }
    wrapper.unmount();
  });

  it("ignores a warning and moves it to the resolved list", async () => {
    const { store, wrapper } = await mountPanel();
    const warning = wrapper.findAll("article.gov-issue").find((c) => c.text().includes("日期前后不一致"))!;
    await warning.findAll("button").find((b) => b.text() === "忽略提示")!.trigger("click");
    await flushPromises();
    expect(store.byId["demo-d1"].resolutions["d1-i6"].kind).toBe("hint_ignored");
    wrapper.unmount();
  });

  it("requires a reason before dismissing an AI critical issue", async () => {
    const { store, wrapper } = await mountPanel();
    const ai = wrapper.findAll("article.gov-issue").find((c) => c.text().includes("处罚性表述缺少政策依据"))!;
    expect(ai.text()).toContain("待人工复核");
    await ai.findAll("button").find((b) => b.text() === "判定不成立…")!.trigger("click");
    await flushPromises();
    const dialog = document.body.querySelector('[role="dialog"]') as HTMLElement;
    const confirm = [...dialog.querySelectorAll("button")].find((b) => b.textContent?.includes("确认不成立"))!;
    confirm.click();
    await flushPromises();
    expect(dialog.querySelector('[role="alert"]')).not.toBeNull();
    expect(store.byId["demo-d1"].resolutions["d1-i5"]).toBeUndefined();
    wrapper.unmount();
  });
});
