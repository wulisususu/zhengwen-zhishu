// Draft workbench layout: the editor is the default centre view, elements live in the left column, and
// preview / outline (which render the backend's saved doc.blocks) are shown only after unsaved edits are saved.
import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";
import { defineComponent, h } from "vue";
import { afterEach, expect, it, vi } from "vitest";
import DraftWorkbenchPage from "../../src/features/gov-office/pages/DraftWorkbenchPage.vue";
import { createMockGovOfficeAdapter, DEMO_ACTORS } from "../../src/features/gov-office/adapters/MockGovOfficeAdapter";
import { setGovOfficeAdapter } from "../../src/features/gov-office/adapters";
import { useGovDocumentsStore } from "../../src/features/gov-office/stores/govDocuments";
import { useGovSessionStore } from "../../src/features/gov-office/stores/govSession";
import type { DraftChanges, OfficialDocument } from "../../src/features/gov-office/types";

afterEach(() => { setGovOfficeAdapter(null); vi.restoreAllMocks(); });

const scrollToAnchor = vi.fn();
const A4Preview = defineComponent({
  name: "A4Preview",
  setup(_, { expose, slots }) { expose({ scrollToAnchor }); return () => h("div", { class: "a4-stub" }, slots.default?.()); },
});

async function mountWorkbench(save: (id: string, changes?: DraftChanges) => Promise<OfficialDocument>) {
  const adapter = createMockGovOfficeAdapter();
  const doc = { ...await adapter.getDocument("demo-d1"), origin: "backend" as const, version: 1, body: "原正文", signDate: "",
    docNumber: { id: "number", text: "办发〔2026〕8号" }, banji: undefined, note: "", titleLines: [], tables: [] } as OfficialDocument;
  adapter.getDocument = async () => structuredClone(doc);
  adapter.saveDraft = vi.fn(save);
  setGovOfficeAdapter(adapter);
  const pinia = createPinia(); setActivePinia(pinia);
  const session = useGovSessionStore(); session.adapterMode = "http"; session.actor = DEMO_ACTORS[0]; session.loaded = true;
  useGovDocumentsStore().upsert(doc);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/gov/draft/:id", component: DraftWorkbenchPage }] });
  await router.push("/gov/draft/demo-d1"); await router.isReady();
  const w = mount(RouterView, { global: { plugins: [pinia, router], stubs: {
    GovLayout: { template: "<main><slot /></main>" },
    GovPageHeader: { template: "<header><slot name='actions' /></header>" },
    A4Preview, OfficialDocumentView: true, IssuePanel: true, DocumentOutline: true,
  } } });
  await flushPromises();
  return { w, doc, adapter };
}

const button = (w: ReturnType<typeof mount>, text: string) => w.findAll("button").find(b => b.text() === text)!;

it("opens on the editor in the centre column with elements in the left column", async () => {
  const { w } = await mountWorkbench(async () => { throw new Error("not saved"); });
  const centre = w.get('[aria-label="正文编辑区"]');
  expect(centre.find('[aria-label="正文编辑"]').exists()).toBe(true);
  expect(centre.find('[aria-label="成文日期"]').exists()).toBe(false);
  expect(w.find(".a4-stub").exists()).toBe(false);
  expect(button(w, "编辑").attributes("aria-pressed")).toBe("true");

  await button(w, "要素与材料").trigger("click");
  const left = w.get('[aria-label="起草要素与材料"]');
  for (const label of ["成文日期", "发文字号", "印发机关", "印发日期"]) expect(left.find(`[aria-label="${label}"]`).exists()).toBe(true);
  // Less-used notice elements and tables are folded, not expanded by default.
  const more = left.get("details");
  expect(more.attributes("open")).toBeUndefined();
  expect(more.find('[aria-label="抄送机关"]').exists()).toBe(true);
  // The read-only copy of the saved number / date is gone; the editable fields are the only ones.
  expect(left.findAll('[aria-label="发文字号"]')).toHaveLength(1);
  expect(left.text()).not.toContain("—");
});

it("saves unsaved edits before showing the preview, and stays in the editor if saving fails", async () => {
  let fail = true;
  const { w, doc } = await mountWorkbench(async (_id, changes) => {
    if (fail) throw new Error("网络错误");
    return { ...doc, ...changes, version: 2 } as OfficialDocument;
  });
  await w.get('[aria-label="正文编辑"]').setValue("改后的正文");

  await button(w, "预览").trigger("click"); await flushPromises();
  expect(w.find(".a4-stub").exists()).toBe(false);
  expect((w.get('[aria-label="正文编辑"]').element as HTMLTextAreaElement).value).toBe("改后的正文");

  fail = false;
  await button(w, "预览").trigger("click"); await flushPromises();
  expect(w.find(".a4-stub").exists()).toBe(true);
  expect(w.find('[aria-label="正文编辑"]').exists()).toBe(false);
  const { saveDraft } = (await import("../../src/features/gov-office/adapters")).getGovOfficeAdapter();
  expect(vi.mocked(saveDraft).mock.calls.at(-1)![1]).toMatchObject({ body: "改后的正文" });

  await button(w, "编辑").trigger("click");
  expect((w.get('[aria-label="正文编辑"]').element as HTMLTextAreaElement).value).toBe("改后的正文");
});

it("locating an issue switches to the preview and scrolls once it is mounted", async () => {
  scrollToAnchor.mockClear();
  const { w } = await mountWorkbench(async () => { throw new Error("not saved"); });
  await button(w, "提纲").trigger("click"); await flushPromises();
  expect(w.find(".a4-stub").exists()).toBe(false);
  w.findComponent({ name: "IssuePanel" }).vm.$emit("locate", "demo-d1-p1");
  await flushPromises();
  expect(w.find(".a4-stub").exists()).toBe(true);
  expect(scrollToAnchor).toHaveBeenCalledWith("demo-d1-p1");
});
