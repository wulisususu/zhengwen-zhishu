import { afterEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import RecentPptProjects from "../src/features/ppt-workbench/components/chat/RecentPptProjects.vue";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("recent PPT projects", () => {
  it("uses the authenticated backend history instead of localStorage summaries", async () => {
    localStorage.setItem("ppt-workbench:recent:v1", JSON.stringify([{ projectId: "stale", title: "旧缓存", updatedAt: "2026-01-01T00:00:00Z" }]));
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ data: [{ project_id: "pptproj_real", title: "真实历史 PPT", updated_at: "2026-07-22T00:00:00Z", editor_supported: true }] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/ppt/:projectId?", component: { template: "<div />" } }] });
    await router.push("/ppt/pptproj_real");
    await router.isReady();

    const wrapper = mount(RecentPptProjects, { global: { plugins: [router] } });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/ppt-master/projects/recent");
    expect(wrapper.text()).toContain("真实历史 PPT");
    expect(wrapper.text()).not.toContain("旧缓存");
    await wrapper.get("button").trigger("click");
    expect(router.currentRoute.value.params.projectId).toBe("pptproj_real");
  });
});
