import { describe, expect, it, vi } from "vitest";
import { createPinia } from "pinia";
import { mount } from "@vue/test-utils";
import PptWorkbenchPage from "../src/features/ppt-workbench/pages/PptWorkbenchPage.vue";
import { mockWorkflowCapabilities } from "../src/features/ppt-workbench/protocol/capabilities";
import type { PptWorkflowAdapter } from "../src/features/ppt-workbench/adapters/PptWorkflowAdapter";

describe("PptWorkbenchPage lifecycle", () => {
  it("disposes adapter-owned preview resources when the workbench unmounts", () => {
    const dispose = vi.fn();
    const adapter = {
      capabilities: mockWorkflowCapabilities,
      async *start() {},
      dispose,
    } as PptWorkflowAdapter;
    const wrapper = mount(PptWorkbenchPage, {
      props: { projectId: "project-lifecycle", adapter },
      global: { plugins: [createPinia()] },
    });

    wrapper.unmount();

    expect(dispose).toHaveBeenCalledTimes(1);
  });
});
