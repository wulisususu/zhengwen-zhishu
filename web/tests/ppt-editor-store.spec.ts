import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const doc = (projectId: string, text = "标题") => ({
  project_id: projectId, base_task_id: "task-1", slides: [{ slide_id: "slide-1", order: 1, width: 1280, height: 720, elements: [{ id: "text-1", type: "text", x: 10, y: 10, width: 200, height: 50, rotation: 0, z_index: 1, locked: false, style: {}, content: { text } }] }],
});

describe("ppt editor store", () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.restoreAllMocks(); });

  it("loads a draft and saves text using the current revision", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { document: doc("a"), revision: 1, original_file_id: 101 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { document: doc("a", "已编辑"), revision: 2, original_file_id: 101 } }), { status: 200 }));
    const { usePptEditorStore } = await import("../src/features/ppt-workbench/stores/pptEditor");
    const store = usePptEditorStore();
    await store.load("a", fetchImpl);
    store.setText("text-1", "已编辑");
    await store.save(fetchImpl);
    expect(store.revision).toBe(2);
    expect(JSON.parse(String(fetchImpl.mock.calls[1]?.[1]?.body))).toMatchObject({ expected_revision: 1 });
    expect(store.originalFileId).toBe(101);
  });

  it("drops an old project response instead of contaminating the active project", async () => {
    let resolveA!: (value: Response) => void;
    const fetchImpl = vi.fn((url: RequestInfo | URL) => String(url).includes("/a/") ? new Promise<Response>((resolve) => { resolveA = resolve; }) : Promise.resolve(new Response(JSON.stringify({ data: { document: doc("b"), revision: 1, original_file_id: 102 } }), { status: 200 })));
    const { usePptEditorStore } = await import("../src/features/ppt-workbench/stores/pptEditor");
    const store = usePptEditorStore();
    const old = store.load("a", fetchImpl); await store.load("b", fetchImpl); resolveA(new Response(JSON.stringify({ data: { document: doc("a"), revision: 1, original_file_id: 101 } }), { status: 200 })); await old;
    expect(store.projectId).toBe("b");
    expect(store.document?.project_id).toBe("b");
  });

  it("undoes and redoes a local element move without touching locked vectors", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ data: { document: doc("a"), revision: 1, original_file_id: 101 } }), { status: 200 }));
    const { usePptEditorStore } = await import("../src/features/ppt-workbench/stores/pptEditor");
    const store = usePptEditorStore(); await store.load("a", fetchImpl);
    store.moveElement("text-1", 40, 60); expect(store.document?.slides[0].elements[0].x).toBe(40);
    store.undo(); expect(store.document?.slides[0].elements[0].x).toBe(10);
    store.redo(); expect(store.document?.slides[0].elements[0].y).toBe(60);
  });

  it("stops automatic saving on 409 and can reload the server draft", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { document: doc("a"), revision: 1, original_file_id: 101 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: "editor_revision_conflict", revision: 2 } }), { status: 409 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { document: doc("a", "server"), revision: 2, original_file_id: 101 } }), { status: 200 }));
    const { usePptEditorStore } = await import("../src/features/ppt-workbench/stores/pptEditor");
    const store = usePptEditorStore(); await store.load("a", fetchImpl); store.setText("text-1", "local"); await store.save(fetchImpl);
    expect(store.savingState).toBe("conflict"); await store.reload(fetchImpl);
    expect(store.document?.slides[0].elements[0].content.text).toBe("server");
  });


  it("flushes the current revision before requesting an edited PPTX export", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { document: doc("a"), revision: 1, original_file_id: 101 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { document: doc("a", "导出标题"), revision: 2, original_file_id: 101 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { export_id: "ppexport_1", file_id: 202, download_url: "/api/v1/files/202/download", revision: 2 } }), { status: 200 }));
    const { usePptEditorStore } = await import("../src/features/ppt-workbench/stores/pptEditor");
    const store = usePptEditorStore();
    await store.load("a", fetchImpl);
    store.setText("text-1", "导出标题");

    const result = await store.exportPpt(fetchImpl);

    expect(result?.file_id).toBe(202);
    expect(fetchImpl.mock.calls[1]?.[0]).toContain("/editor");
    expect(fetchImpl.mock.calls[2]?.[0]).toContain("/editor/export");
    expect(JSON.parse(String(fetchImpl.mock.calls[2]?.[1]?.body))).toEqual({ expected_revision: 2 });
    expect(store.originalFileId).toBe(101);
  });



  it("flushes pending animations before exporting", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { document: doc("a"), revision: 1, original_file_id: 101 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { export_id: "ppexport_1", file_id: 202, download_url: "/api/v1/files/202/download", revision: 1 } }), { status: 200 }));
    const animationFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { project_id: "a", document_revision: 1, animation_revision: 2, animation_count: 1, sha256: "animation" } }), { status: 200 }));
    vi.stubGlobal("fetch", animationFetch);
    const { usePptEditorStore } = await import("../src/features/ppt-workbench/stores/pptEditor");
    const { useAnimationStore } = await import("../src/features/ppt-workbench/stores/animationStore");
    const editor = usePptEditorStore();
    const animations = useAnimationStore();
    await editor.load("a", fetchImpl);
    animations.projectId = "a";
    animations.documentRevision = 1;
    animations.animationRevision = 1;
    animations.manifest = { version: 1, project_id: "a", animation_revision: 1, slides: [{ slide_id: "slide-1", animations: [{ animation_id: "anim-1", element_id: "text-1", category: "entrance", effect: "fade", order: 1, duration_ms: 500, delay_ms: 0, trigger: "on_click", direction: null, repeat: 1, enabled: true }] }] };
    animations.updateAnimation("slide-1", "anim-1", { duration_ms: 750 });

    await editor.exportPpt(fetchImpl);

    expect(animationFetch).toHaveBeenCalledTimes(1);
    expect(fetchImpl.mock.calls[1]?.[0]).toContain("/editor/export");
  });

  it("serializes a later local change after an in-flight save without stale overwrite", async () => {
    let resolveFirst!: (response: Response) => void;
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { document: doc("a"), revision: 1, original_file_id: 101 } }), { status: 200 }))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { document: doc("a", "第二次修改"), revision: 3, original_file_id: 101 } }), { status: 200 }));
    const { usePptEditorStore } = await import("../src/features/ppt-workbench/stores/pptEditor");
    const store = usePptEditorStore();
    await store.load("a", fetchImpl);
    store.setText("text-1", "第一次修改");
    const firstSave = store.save(fetchImpl);
    store.setText("text-1", "第二次修改");
    const secondSave = store.save(fetchImpl);
    resolveFirst(new Response(JSON.stringify({ data: { document: doc("a", "第一次修改"), revision: 2, original_file_id: 101 } }), { status: 200 }));

    await Promise.all([firstSave, secondSave]);

    expect(store.revision).toBe(3);
    expect(store.document?.slides[0].elements[0].content.text).toBe("第二次修改");
    expect(JSON.parse(String(fetchImpl.mock.calls[2]?.[1]?.body))).toMatchObject({ expected_revision: 2 });
  });



  it("adds an authorized image element using an asset id rather than a browser URL", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ data: { document: doc("a"), revision: 1, original_file_id: 101 } }), { status: 200 }));
    const { usePptEditorStore } = await import("../src/features/ppt-workbench/stores/pptEditor");
    const store = usePptEditorStore(); await store.load("a", fetchImpl);

    store.addImage({ asset_id: "pptimg_abc", file_id: 301, width: 640, height: 360, download_url: "/api/v1/files/301/download" });

    const image = store.document?.slides[0].elements.find((item) => item.type === "image");
    expect(image).toMatchObject({ asset_id: "pptimg_abc", file_id: 301, fit: "cover" });
    expect(image?.content).not.toHaveProperty("blob_url");
  });

  it("adds editable native chart and table sidecar elements", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ data: { document: doc("a"), revision: 1, original_file_id: 101 } }), { status: 200 }));
    const { usePptEditorStore } = await import("../src/features/ppt-workbench/stores/pptEditor");
    const store = usePptEditorStore(); await store.load("a", fetchImpl);
    store.addChart("line"); store.addTable();
    const chart = store.document?.slides[0].elements.find((item) => item.type === "chart");
    const table = store.document?.slides[0].elements.find((item) => item.type === "table");
    expect(chart?.content.chart_type).toBe("line"); expect(table?.content.columns).toEqual(["项目", "数值"]);
    store.updateNative(chart!.id, { ...chart!.content, title: "真实数据", categories: ["A"], series: [{ name: "S", values: [9] }] });
    expect(store.document?.slides[0].elements.find((item) => item.id === chart!.id)?.content.title).toBe("真实数据");
  });


  it("inserts imported chart and table sidecar content without losing source refs", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ data: { document: doc("a"), revision: 1, original_file_id: 101 } }), { status: 200 }));
    const { usePptEditorStore } = await import("../src/features/ppt-workbench/stores/pptEditor");
    const store = usePptEditorStore(); await store.load("a", fetchImpl);
    const chartContent = { chart_type: "bar", title: "收入", categories: ["Q1"], series: [{ name: "收入", values: [20] }], source_refs: [{ file_id: 9, sheet: "数据" }] };
    const tableContent = { columns: ["项目"], rows: [["收入"]], source_refs: [{ file_id: 9, sheet: "数据" }] };
    store.addChart("bar", chartContent); store.addTable(tableContent);
    expect(store.document?.slides[0].elements.find((item) => item.type === "chart")?.content.source_refs[0].file_id).toBe(9);
    expect(store.document?.slides[0].elements.find((item) => item.type === "table")?.content.rows).toEqual([["收入"]]);
  });

});
