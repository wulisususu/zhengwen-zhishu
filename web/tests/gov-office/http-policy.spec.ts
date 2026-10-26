import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { HttpGovOfficeAdapter } from "../../src/features/gov-office/adapters/HttpGovOfficeAdapter";

const response = (data: unknown) => new Response(JSON.stringify({ code: 0, data }), { headers: { "Content-Type": "application/json" } });
beforeEach(() => localStorage.setItem("mqw-session", JSON.stringify({ token: "real-token" })));
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

it("loads real library totals instead of unavailable placeholder totals", async () => {
  const fetcher = vi.fn().mockResolvedValue(response({ origin: "backend", available: true, total: 3, current: 1, abolished: 1, unverified: 1 }));
  vi.stubGlobal("fetch", fetcher);
  expect((await new HttpGovOfficeAdapter().getPolicyStats()).total).toBe(3);
  expect(fetcher.mock.calls[0][0]).toBe("/api/v1/gov/policies/stats");
});

it("resolves citation IDs through the real backend", async () => {
  const citation = { id: "clause:7@0-4", policyTitle: "真实政策", sourceUrl: "https://www.gov.cn/policy", version: 2, status: "unverified" };
  const fetcher = vi.fn().mockResolvedValue(response({ citations: [citation], missing: [] }));
  vi.stubGlobal("fetch", fetcher);
  expect(await new HttpGovOfficeAdapter().getCitations([citation.id])).toEqual([citation]);
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ ids: [citation.id] });
});

it("searches real clauses with explicit statuses and does not fabricate answers", async () => {
  const fetcher = vi.fn().mockResolvedValue(response({ hits: [], error: null }));
  vi.stubGlobal("fetch", fetcher);
  const api = new HttpGovOfficeAdapter();
  expect(typeof api.searchPolicies).toBe("function");
  await api.searchPolicies("数据", ["current", "unverified"]);
  expect(fetcher.mock.calls[0][0]).toBe("/api/v1/gov/policies/search");
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ query: "数据", statuses: ["current", "unverified"], limit: 30 });
});

it("saves citation IDs with server document version, without client status metadata", async () => {
  const doc = { id: "draft-1", version: 3, policyRefs: [] };
  const fetcher = vi.fn().mockResolvedValueOnce(response(doc)).mockResolvedValueOnce(response({ ...doc, version: 4 }));
  vi.stubGlobal("fetch", fetcher);
  const api = new HttpGovOfficeAdapter();
  await api.getDocument(doc.id);
  expect(typeof api.selectCitations).toBe("function");
  await api.selectCitations(doc.id, ["clause:7"]);
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ version: 3, citationIds: ["clause:7"] });
});

it("rejects stale citation responses after a login change", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => {
    localStorage.setItem("mqw-session", JSON.stringify({ token: "other-token" }));
    return response({ citations: [{ id: "clause:1" }], missing: [] });
  }));
  await expect(new HttpGovOfficeAdapter().getCitations(["clause:1"])).rejects.toThrow("角色已切换");
});
