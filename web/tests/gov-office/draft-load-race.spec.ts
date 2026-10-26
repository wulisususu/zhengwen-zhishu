import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";
import { afterEach, expect, it, vi } from "vitest";
import DraftWorkbenchPage from "../../src/features/gov-office/pages/DraftWorkbenchPage.vue";
import { createMockGovOfficeAdapter, DEMO_ACTORS } from "../../src/features/gov-office/adapters/MockGovOfficeAdapter";
import { setGovOfficeAdapter } from "../../src/features/gov-office/adapters";
import { useGovDocumentsStore } from "../../src/features/gov-office/stores/govDocuments";
import { useGovSessionStore } from "../../src/features/gov-office/stores/govSession";
import type { DraftChanges, OfficialDocument } from "../../src/features/gov-office/types";

afterEach(() => { setGovOfficeAdapter(null); vi.restoreAllMocks(); });

it("keeps early edits when the initial document refresh finishes, then accepts the saved response", async () => {
  const adapter = createMockGovOfficeAdapter();
  const doc = { ...await adapter.getDocument("demo-d1"), origin: "backend" as const, version: 1, body: "", signDate: "",
    fields: { recipient: "", issuer: "", undertaker: "" }, docNumber: { id: "number", text: "" }, banji: undefined };
  let finishLoad!: (doc: OfficialDocument) => void;
  adapter.getDocument = () => new Promise(resolve => { finishLoad = resolve; });
  const save = vi.fn(async (_id: string, changes?: DraftChanges) => ({ ...doc, ...changes, title: "服务端确认标题", version: 2 } as OfficialDocument));
  adapter.saveDraft = save;
  setGovOfficeAdapter(adapter);
  const pinia = createPinia(); setActivePinia(pinia);
  const session = useGovSessionStore(); session.adapterMode = "http"; session.actor = DEMO_ACTORS[0]; session.loaded = true;
  useGovDocumentsStore().upsert(doc);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/gov/draft/:id", component: DraftWorkbenchPage }] });
  await router.push("/gov/draft/demo-d1"); await router.isReady();
  const w = mount(RouterView, { global: { plugins: [pinia, router], stubs: {
    GovLayout: { template: "<main><slot /></main>" },
    GovPageHeader: { template: "<header><slot name='actions' /></header>" },
    A4Preview: true, OfficialDocumentView: true, IssuePanel: true,
  } } });
  await flushPromises();
  await w.findAll('button').find(b => b.text().includes("要素与材料"))!.trigger("click");
  await w.get('[aria-label="成文日期"]').setValue("2026年10月26日");
  await w.get('[aria-label="发文字号"]').setValue("办发〔2026〕10号");
  await w.get('#gov-field-issuer').setValue("测试办公室");
  finishLoad(structuredClone(doc)); await flushPromises();
  expect((w.get('[aria-label="成文日期"]').element as HTMLInputElement).value).toBe("2026年10月26日");
  expect((w.get('[aria-label="发文字号"]').element as HTMLInputElement).value).toBe("办发〔2026〕10号");
  expect((w.get('#gov-field-issuer').element as HTMLInputElement).value).toBe("测试办公室");
  await w.findAll('button').find(b => b.text().includes("保存草稿"))!.trigger("click"); await flushPromises();
  expect(save.mock.calls[0][1]).toMatchObject({ signDate: "2026年10月26日", docNumber: { text: "办发〔2026〕10号" }, fields: { issuer: "测试办公室" } });
  expect((w.get('[aria-label="文稿标题"]').element as HTMLInputElement).value).toBe("服务端确认标题");
  expect(w.text()).not.toContain("有修改未保存");
  w.unmount();
});
