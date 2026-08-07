import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { nextTick } from "vue";

const manifest = (projectId: string, effect = "fade") => ({
  version: 1,
  project_id: projectId,
  animation_revision: 1,
  slides: [{
    slide_id: "slide-1",
    animations: [{
      animation_id: "anim-1", element_id: "element-1", category: "entrance" as const,
      effect: effect as "fade" | "wipe", order: 1, duration_ms: 500, delay_ms: 0,
      trigger: "on_click" as const, direction: null, repeat: 1, enabled: true,
    }],
  }],
});

const response = (data: unknown) => new Response(JSON.stringify({ data }), { status: 200 });

describe("animation store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it("drops an older project load response after switching projects", async () => {
    let resolveA!: (value: Response) => void;
    const fetchMock = vi.fn((url: RequestInfo | URL) => String(url).includes("/a/")
      ? new Promise<Response>((resolve) => { resolveA = resolve; })
      : Promise.resolve(response({ project_id: "b", document_revision: 2, animation_revision: 3, manifest: manifest("b", "wipe") })));
    vi.stubGlobal("fetch", fetchMock);
    const { useAnimationStore } = await import("../src/features/ppt-workbench/stores/animationStore");
    const store = useAnimationStore();

    const staleLoad = store.load("a");
    await store.load("b");
    resolveA(response({ project_id: "a", document_revision: 1, animation_revision: 1, manifest: manifest("a") }));
    await staleLoad;

    expect(store.projectId).toBe("b");
    expect(store.manifest?.project_id).toBe("b");
    expect(store.animationRevision).toBe(3);
  });

  it("serializes changes made while an animation save is in flight", async () => {
    let resolveFirst!: (value: Response) => void;
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce(response({ project_id: "p", document_revision: 1, animation_revision: 3, animation_count: 1, sha256: "second" }));
    vi.stubGlobal("fetch", fetchMock);
    const { useAnimationStore } = await import("../src/features/ppt-workbench/stores/animationStore");
    const store = useAnimationStore();
    store.projectId = "p";
    store.manifest = manifest("p");
    store.documentRevision = 1;
    store.animationRevision = 1;

    store.updateAnimation("slide-1", "anim-1", { effect: "wipe" });
    const first = store.save();
    store.updateAnimation("slide-1", "anim-1", { duration_ms: 750 });
    const second = store.save();
    resolveFirst(response({ project_id: "p", document_revision: 1, animation_revision: 2, animation_count: 1, sha256: "first" }));
    await Promise.all([first, second]);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({ expected_animation_revision: 1, manifest: { slides: [{ animations: [{ effect: "wipe", duration_ms: 500 }] }] } });
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toMatchObject({ expected_animation_revision: 2, manifest: { slides: [{ animations: [{ effect: "wipe", duration_ms: 750 }] }] } });
    expect(store.animationRevision).toBe(3);
  });

  it("persists a drag reorder across different objects on the selected slide", async () => {
    const { useAnimationStore } = await import("../src/features/ppt-workbench/stores/animationStore");
    const { usePptEditorStore } = await import("../src/features/ppt-workbench/stores/pptEditor");
    const AnimationPanel = (await import("../src/features/ppt-workbench/components/animation/AnimationPanel.vue")).default;
    const animations = useAnimationStore();
    const editor = usePptEditorStore();
    animations.projectId = "p";
    animations.manifest = { ...manifest("p"), slides: [{ slide_id: "slide-1", animations: [
      manifest("p").slides[0].animations[0],
      { ...manifest("p").slides[0].animations[0], animation_id: "anim-2", element_id: "element-2", order: 2 },
    ] }] };
    editor.projectId = "p";
    editor.selectedSlideId = "slide-1";
    editor.selectedElementIds = ["element-1"];
    editor.document = { project_id: "p", base_task_id: "task", slides: [{ slide_id: "slide-1", order: 1, width: 1280, height: 720, elements: [{ id: "element-1" }, { id: "element-2" }] }] } as any;
    const save = vi.spyOn(animations, "save").mockResolvedValue();

    const wrapper = mount(AnimationPanel);
    await nextTick();
    const cards = wrapper.findAll(".animation-card");
    expect(cards).toHaveLength(2);
    await cards[0].trigger("dragstart");
    await cards[1].trigger("drop");

    expect(animations.getSlideAnimations("slide-1").map((item) => item.animation_id)).toEqual(["anim-2", "anim-1"]);
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("flushes a reordered manifest to the server", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ project_id: "p", document_revision: 1, animation_revision: 2, animation_count: 2, sha256: "ordered" }));
    vi.stubGlobal("fetch", fetchMock);
    const { useAnimationStore } = await import("../src/features/ppt-workbench/stores/animationStore");
    const store = useAnimationStore();
    store.projectId = "p";
    store.manifest = { ...manifest("p"), slides: [{ slide_id: "slide-1", animations: [
      manifest("p").slides[0].animations[0],
      { ...manifest("p").slides[0].animations[0], animation_id: "anim-2", element_id: "element-2", order: 2 },
    ] }] };
    store.documentRevision = 1;
    store.animationRevision = 1;

    store.reorderAnimations("slide-1", ["anim-2", "anim-1"]);
    await store.flushSave();

    const saved = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(saved.manifest.slides[0].animations.map((item: { animation_id: string; order: number }) => [item.animation_id, item.order])).toEqual([["anim-2", 1], ["anim-1", 2]]);
  });


  it("does not expose unsupported direction or repeat controls", async () => {
    const { useAnimationStore } = await import("../src/features/ppt-workbench/stores/animationStore");
    const { usePptEditorStore } = await import("../src/features/ppt-workbench/stores/pptEditor");
    const AnimationPanel = (await import("../src/features/ppt-workbench/components/animation/AnimationPanel.vue")).default;
    const animations = useAnimationStore();
    const editor = usePptEditorStore();
    animations.projectId = "p";
    animations.manifest = manifest("p", "wipe");
    editor.projectId = "p";
    editor.selectedSlideId = "slide-1";
    editor.selectedElementIds = ["element-1"];
    editor.document = { project_id: "p", base_task_id: "task", slides: [{ slide_id: "slide-1", order: 1, width: 1280, height: 720, elements: [{ id: "element-1" }] }] } as any;

    const wrapper = mount(AnimationPanel);
    await nextTick();

    expect(wrapper.text()).not.toContain("Direction");
    expect(wrapper.text()).not.toContain("Repeat");
    expect(wrapper.findAll('input[type="number"]')).toHaveLength(2);
  });

});
