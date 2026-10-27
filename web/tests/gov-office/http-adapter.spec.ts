import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getGovOfficeAdapter, setGovOfficeAdapter } from "../../src/features/gov-office/adapters";

const doc = { id: "real-doc", origin: "backend", version: 4, title: "通知", body: "正文", fields: { recipient: "", issuer: "", undertaker: "" } };
const response = (data: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? { code: 0, data } : { detail: data }), { status, headers: { "Content-Type": "application/json" } });
async function adapter() {
  const module = await import("../../src/features/gov-office/adapters/HttpGovOfficeAdapter").catch(() => null);
  expect(module, "HTTP adapter must exist").not.toBeNull();
  return new module!.HttpGovOfficeAdapter();
}

beforeEach(() => { localStorage.setItem("mqw-session", JSON.stringify({ token: "real-login-token" })); setGovOfficeAdapter(null); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear(); });

describe("real government HTTP boundary", () => {
  it("defaults to HTTP without a demo flag", () => { expect(getGovOfficeAdapter().mode).toBe("http"); });
  it("loads the authenticated identity and reads the latest login token", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ account: "writer", origin: "backend" }));
    vi.stubGlobal("fetch", fetcher);
    const api = await adapter();
    await api.getCurrentActor();
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/gov/actor");
    expect(new Headers(fetcher.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer real-login-token");
    localStorage.setItem("mqw-session", JSON.stringify({ token: "new-login-token" }));
    fetcher.mockResolvedValueOnce(response({ account: "other" }));
    await api.getCurrentActor();
    expect(new Headers(fetcher.mock.calls[1][1].headers).get("Authorization")).toBe("Bearer new-login-token");
  });
  it("passes policy status filters and the page to the policy list", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetcher);
    const api = await adapter();
    await api.listPolicies("数据", { statuses: ["unverified", "current"], page: 3 });
    const url = new URL(fetcher.mock.calls[0][0], "http://local");
    expect(url.pathname).toBe("/api/v1/gov/policies");
    expect(url.searchParams.get("keyword")).toBe("数据");
    expect(url.searchParams.get("page")).toBe("3");
    expect(url.searchParams.getAll("status")).toEqual(["unverified", "current"]);
  });
  it("saves the fetched server version and editable content", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(response(doc)).mockResolvedValueOnce(response({ ...doc, version: 5, title: "新标题" }));
    vi.stubGlobal("fetch", fetcher);
    const api = await adapter();
    await api.getDocument(doc.id);
    const saved = await api.saveDraft(doc.id, { title: "新标题", body: "新正文" });
    expect(saved.version).toBe(5);
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ version: 4, title: "新标题", body: "新正文" });
  });
  it("reports conflicts without silently retrying or returning a demo", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(response(doc)).mockResolvedValueOnce(response("文稿已更新，请刷新", 409));
    vi.stubGlobal("fetch", fetcher);
    const api = await adapter();
    await api.getDocument(doc.id);
    await expect(api.saveDraft(doc.id, { title: "覆盖" })).rejects.toMatchObject({ code: "409", message: "文稿已更新，请刷新" });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("does not substitute demo data on network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network error")));
    await expect((await adapter()).listDocuments()).rejects.toThrow("连接");
  });
  it("uploads a real FormData body without a JSON content type", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ id: "1", name: "材料.txt" }));
    vi.stubGlobal("fetch", fetcher);
    await (await adapter()).uploadMaterial!(new File(["正文"], "材料.txt"));
    expect(fetcher.mock.calls[0][1].body).toBeInstanceOf(FormData);
    expect(new Headers(fetcher.mock.calls[0][1].headers).has("Content-Type")).toBe(false);
  });
  it("checks export response before downloading a real blob", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(new Blob(["PK-docx-bytes"]), { headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document" } }));
    vi.stubGlobal("fetch", fetcher);
    const create = vi.fn().mockReturnValue("blob:download");
    vi.spyOn(URL, "createObjectURL").mockImplementation(create);
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const result = await (await adapter()).exportDocument(doc.id, "internal_draft");
    expect(result.generated).toBe(true);
    expect(create).toHaveBeenCalledOnce(); expect(click).toHaveBeenCalledOnce();
  });
  it("does not report formal export permission or unavailable checks as success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response("自动审校未接入", 503)));
    const api = await adapter();
    await expect(api.exportDocument(doc.id, "formal")).rejects.toThrow();
    await expect(api.getPolicyStats()).rejects.toMatchObject({ code: "503" });
  });
});
