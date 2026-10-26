import { beforeEach, afterEach, it, expect, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useGovDocumentsStore } from "../../src/features/gov-office/stores/govDocuments";
import { createMockGovOfficeAdapter } from "../../src/features/gov-office/adapters/MockGovOfficeAdapter";
import { setGovOfficeAdapter } from "../../src/features/gov-office/adapters";
import { HttpGovOfficeAdapter } from "../../src/features/gov-office/adapters/HttpGovOfficeAdapter";
import type { OfficialDocument } from "../../src/features/gov-office/types";

const login = (token: string) => localStorage.setItem("mqw-session", JSON.stringify({ token }));
beforeEach(() => { setActivePinia(createPinia()); login("account-A"); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear(); setGovOfficeAdapter(null); });

it.each(["list", "detail", "mutation"])("discards previous-account %s results after login changes", async (kind) => {
  let resolve!: (value: any) => void;
  const delayed = new Promise<any>((done) => { resolve = done; });
  const adapter = createMockGovOfficeAdapter();
  adapter.listDocuments = () => delayed;
  adapter.getDocument = () => delayed;
  adapter.saveDraft = () => delayed;
  setGovOfficeAdapter(adapter);
  const store = useGovDocumentsStore();
  const pending = kind === "list" ? store.loadList() : kind === "detail" ? store.load("private-A") : store.saveDraft("private-A", "saved");
  login("account-B"); store.$reset();
  const doc = { id: "private-A", origin: "backend", title: "A的私有文稿" } as OfficialDocument;
  resolve(kind === "list" ? [doc] : doc);
  await pending;
  expect(store.order).toEqual([]);
  expect(store.byId["private-A"]).toBeUndefined();
  expect(store.notice).toBe("");
});

it("does not download previous-account responses after a login change", async () => {
  let resolve!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((done) => { resolve = done; })));
  const download = vi.spyOn(URL, "createObjectURL");
  const pending = new HttpGovOfficeAdapter().exportDocument("private-A", "internal_draft");
  login("account-B");
  resolve(new Response(new Blob(["private content"]), { headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document" } }));
  await expect(pending).rejects.toMatchObject({ code: "auth_changed" });
  expect(download).not.toHaveBeenCalled();
});
