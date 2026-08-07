import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

describe("template fill store", () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.restoreAllMocks(); });

  it("keeps a confirmed plan immutable and applies it with its revision", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { template_id: "ptpl_1", status: "analyzed", analysis: { slides: [] } } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { plan_id: "fillplan_1", status: "draft", revision: 1, plan: { selected_slides: [] } } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { plan_id: "fillplan_1", status: "confirmed", revision: 1, plan: { selected_slides: [] } } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { task_id: "filltask_1", status: "completed", output_file_id: 99, artifact_manifest: { output_file_id: 99 } } }), { status: 200 }));
    const { usePptTemplateFillStore } = await import("../src/features/ppt-workbench/stores/pptTemplateFill");
    const store = usePptTemplateFillStore();

    await store.analyze("ptpl_1", fetchImpl);
    store.plan = { plan_id: "fillplan_1", status: "draft", revision: 1, plan: { selected_slides: [] } };
    await store.confirm(fetchImpl);
    await store.apply(fetchImpl);

    expect(store.plan?.status).toBe("confirmed");
    expect(store.task?.output_file_id).toBe(99);
    expect(fetchImpl.mock.calls[2]?.[0]).toContain("/confirm");
    expect(JSON.parse(String(fetchImpl.mock.calls[3]?.[1]?.body))).toEqual({ expected_revision: 1 });
  });

  it("loads owner-scoped preview slides and surfaces a revision conflict", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { template_id: "ptpl_2", status: "analyzed" } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: [{ slide_index: 1, preview_file_id: 701, download_url: "/api/v1/files/701/download" }] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: "template_fill_plan_revision_conflict" } }), { status: 409 }));
    const { usePptTemplateFillStore } = await import("../src/features/ppt-workbench/stores/pptTemplateFill");
    const store = usePptTemplateFillStore();
    await store.analyze("ptpl_2", fetchImpl);
    store.plan = { plan_id: "fillplan_2", status: "draft", revision: 4, plan: { selected_slides: [] } };
    await store.savePlan(fetchImpl);

    expect(store.slides).toEqual([{ slide_index: 1, preview_file_id: 701, download_url: "/api/v1/files/701/download" }]);
    expect(store.state).toBe("conflict");
    expect(store.error).toContain("revision_conflict");
    expect(fetchImpl.mock.calls[1]?.[0]).toContain("/slides");
  });

  it("does not issue an apply request until a plan is confirmed", async () => {
    const { usePptTemplateFillStore } = await import("../src/features/ppt-workbench/stores/pptTemplateFill");
    const store = usePptTemplateFillStore();
    const fetchImpl = vi.fn();
    store.plan = { plan_id: "fillplan_3", status: "draft", revision: 1, plan: { selected_slides: [] } };

    await store.apply(fetchImpl);

    expect(fetchImpl).not.toHaveBeenCalled();
    expect(store.error).toBe("请先确认填充计划");
  });

});
