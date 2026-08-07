import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { usePptNativeEnhanceStore } from "../src/features/ppt-workbench/stores/pptNativeEnhance";

describe("ppt native enhance store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("analyzes an owned PPTX then creates an expected-SHA task", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { source_sha256: "a".repeat(64), slide_count: 2, slides: [] } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { task_id: "enhance_1", status: "completed", output_file_id: 88 } }) });
    const store = usePptNativeEnhanceStore();

    await store.analyze(77, fetchImpl as typeof fetch);
    await store.createTask({ transition_type: "fade", application_scope: "all" }, fetchImpl as typeof fetch);

    expect(fetchImpl).toHaveBeenNthCalledWith(1, "/api/v1/ppt-master/enhance/analyze", expect.objectContaining({ method: "POST" }));
    expect(fetchImpl).toHaveBeenNthCalledWith(2, "/api/v1/ppt-master/enhance/tasks", expect.objectContaining({ method: "POST", body: expect.stringContaining("expected_sha256") }));
    expect(store.task?.output_file_id).toBe(88);
  });
});
