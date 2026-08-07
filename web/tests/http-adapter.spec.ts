import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpPptWorkflowAdapter } from "../src/features/ppt-workbench/adapters/HttpPptWorkflowAdapter";
import type { PptWorkflowAdapter } from "../src/features/ppt-workbench/adapters/PptWorkflowAdapter";
import type { PptWorkflowEvent } from "../src/features/ppt-workbench/protocol/events";
import { byteStream } from "./fixtures/legacySse";

function incrementalFrames(): string[] {
  return [
    'event: planning.started\ndata: {"event_id":"evt-1","event_type":"planning.started","task_id":"pptinc-task-1","project_id":"pptproj-1","sequence":1,"timestamp":"2026-07-20T00:00:01Z","data":{"status":"planning"}}\n\n',
    'event: planning.completed\ndata: {"event_id":"evt-2","event_type":"planning.completed","task_id":"pptinc-task-1","project_id":"pptproj-1","sequence":2,"timestamp":"2026-07-20T00:00:02Z","data":{"page_count":4,"outline":[{"index":1,"title":"封面"},{"index":2,"title":"治理框架"}],"design_summary":{"preview":"聚焦企业人工智能治理框架与行动建议。"}}}\n\n',
    'event: slide.started\ndata: {"event_id":"evt-3","event_type":"slide.started","task_id":"pptinc-task-1","project_id":"pptproj-1","sequence":3,"timestamp":"2026-07-20T00:00:03Z","data":{"slide_id":"pptinc-task-1:slide:1","index":1,"title":"封面","status":"started"}}\n\n',
    'event: slide.completed\ndata: {"event_id":"evt-4","event_type":"slide.completed","task_id":"pptinc-task-1","project_id":"pptproj-1","sequence":4,"timestamp":"2026-07-20T00:00:04Z","data":{"slide_id":"pptinc-task-1:slide:1","index":1,"title":"封面","status":"completed","preview_file_id":11,"preview_url":"/api/v1/files/11/download","thumbnail_file_id":11,"thumbnail_url":"/api/v1/files/11/download"}}\n\n',
    'event: validation.completed\ndata: {"event_id":"evt-5","event_type":"validation.completed","task_id":"pptinc-task-1","project_id":"pptproj-1","sequence":5,"timestamp":"2026-07-20T00:00:05Z","data":{"passed":true,"warnings":[],"errors":[],"blocking_errors":[],"metrics":{"svg_xml_invalid_count":0}}}\n\n',
    'event: export.ready\ndata: {"event_id":"evt-6","event_type":"export.ready","task_id":"pptinc-task-1","project_id":"pptproj-1","sequence":6,"timestamp":"2026-07-20T00:00:06Z","data":{"final_file":{"file_id":88,"download_url":"/api/v1/files/88/download","size":4096,"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","valid":true,"validation_result":{"passed":true,"warnings":[],"errors":[],"blocking_errors":[]}}}}\n\n',
    'event: task.completed\ndata: {"event_id":"evt-7","event_type":"task.completed","task_id":"pptinc-task-1","project_id":"pptproj-1","sequence":7,"timestamp":"2026-07-20T00:00:07Z","data":{"final_file":{"file_id":88,"download_url":"/api/v1/files/88/download","size":4096,"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","valid":true,"validation_result":{"passed":true,"warnings":[],"errors":[],"blocking_errors":[]}}}}\n\n',
  ];
}

async function collect(adapter: PptWorkflowAdapter, sources?: { attachmentFileIds?: number[]; knowledgeDocIds?: number[]; sourcePolicy?: "parsed_only" | "ready_only" }): Promise<PptWorkflowEvent[]> {
  const events: PptWorkflowEvent[] = [];
  for await (const event of adapter.start({
    projectId: "project-1",
    chatId: "chat-1",
    prompt: "请生成一份企业人工智能治理方案 PPT",
    attachmentFileIds: sources?.attachmentFileIds,
    knowledgeDocIds: sources?.knowledgeDocIds,
    sourcePolicy: sources?.sourcePolicy,
  })) {
    events.push(event);
  }
  return events;
}

describe("HttpPptWorkflowAdapter contract", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview-1");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("maps incremental SSE milestones into the standard workflow contract", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/v1/ppt-master/generate-incremental")) {
        return new Response(byteStream(incrementalFrames()), {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      if (url.endsWith("/api/v1/files/11/download")) {
        return new Response(
          '<svg xmlns="http://www.w3.org/2000/svg"><text x="0" y="16">封面</text></svg>',
          { status: 200, headers: { "Content-Type": "image/svg+xml" } },
        );
      }
      throw new Error(`unexpected request: ${url}`);
    });

    const adapter = new HttpPptWorkflowAdapter({
      baseUrl: "http://backend.test:8000",
      pageCount: 4,
      pageFormat: "ppt169",
      requestIdFactory: () => "pptinc-request-1",
      getAccessToken: () => "token-1",
      fetchImpl,
    });
    const events = await collect(adapter);
    const eventTypes = events.map((item) => item.type);
    const submitRequest = fetchImpl.mock.calls[0] ?? [];
    const submitBody = String(submitRequest[1]?.body ?? "");
    const slideEvent = events.find((item) => item.type === "slide.completed");
    const readyPayload = slideEvent?.payload as { slide?: { previewUrl?: string; previewArtifactId?: number; thumbnailArtifactId?: number; status?: string } } | undefined;

    expect(adapter.capabilities).toMatchObject({
      incrementalOutline: true,
      incrementalSlides: true,
      fileDownload: true,
      taskCancellation: false,
      taskResume: false,
      slideRegeneration: false,
      proposalApply: false,
    });
    expect(eventTypes).toEqual([
      "task.started",
      "assistant.text.delta",
      "brief.ready",
      "outline.ready",
      "design.ready",
      "assistant.text.delta",
      "slide.started",
      "slide.completed",
      "assistant.text.delta",
      "validation.completed",
      "assistant.text.delta",
      "export.ready",
      "task.completed",
    ]);
    expect(events[0]).toMatchObject({
      type: "task.started",
      sequence: 0,
      payload: { requestId: "pptinc-request-1", pageCount: 4 },
    });
    expect(events[4]).toMatchObject({ type: "design.ready" });
    expect(events[4]?.sequence).toBeGreaterThan(2);
    expect(events[4]?.sequence).toBeLessThan(3);
    expect(events[7]).toMatchObject({ type: "slide.completed", sequence: 4 });
    expect(readyPayload?.slide).toMatchObject({
      status: "ready",
      previewUrl: "blob:preview-1",
      previewArtifactId: 11,
      thumbnailArtifactId: 11,
    });
    expect(submitRequest[1]?.headers).toMatchObject({
      Authorization: "Bearer token-1",
      "Content-Type": "application/json",
      "Idempotency-Key": "pptinc-request-1",
    });
    expect(submitBody).toContain('"sources":[]');
    expect(submitBody).toContain('"page_count":4');
    expect(fetchImpl.mock.calls[1]?.[1]?.headers).toMatchObject({ Authorization: "Bearer token-1" });
  });

  it("submits source IDs and an explicit policy without parsed source text", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      if (String(input).endsWith("/api/v1/ppt-master/generate-incremental")) {
        return new Response(byteStream(incrementalFrames()), { status: 200, headers: { "Content-Type": "text/event-stream" } });
      }
      if (String(input).endsWith("/api/v1/files/11/download")) {
        return new Response('<svg xmlns="http://www.w3.org/2000/svg"><text x="0" y="16">source</text></svg>', { status: 200 });
      }
      throw new Error(`unexpected request: ${input}`);
    });
    const adapter = new HttpPptWorkflowAdapter({ baseUrl: "http://backend.test:8000", getAccessToken: () => "token-1", fetchImpl, requestIdFactory: () => "ppt-source-request-1" });

    await collect(adapter, { attachmentFileIds: [12, 13], knowledgeDocIds: [101], sourcePolicy: "ready_only" });

    const payload = JSON.parse(String(fetchImpl.mock.calls[0]?.[1]?.body));
    expect(payload).toMatchObject({ attachment_file_ids: [12, 13], knowledge_doc_ids: [101], source_policy: "ready_only" });
    expect(JSON.stringify(payload)).not.toContain("收入增长");
  });

  it("rejects a protected SVG preview containing foreignObject", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/ppt-master/generate-incremental")) {
        return new Response(byteStream(incrementalFrames()), {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      if (url.endsWith("/api/v1/files/11/download")) {
        return new Response(
          '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject>unsafe</foreignObject></svg>',
          { status: 200, headers: { "Content-Type": "image/svg+xml" } },
        );
      }
      throw new Error(`unexpected request: ${url}`);
    });
    const adapter = new HttpPptWorkflowAdapter({
      baseUrl: "http://backend.test:8000",
      getAccessToken: () => "token-1",
      fetchImpl,
    });

    const events = await collect(adapter);
    const slide = events.find((event) => event.type === "slide.completed")?.payload as { slide?: { previewUrl?: string } };

    expect(slide.slide?.previewUrl).toBeUndefined();
  });

  it("rehydrates persisted artifact ids as safe blob URLs", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.headers).toMatchObject({ Authorization: "Bearer token-1" });
      const url = String(input);
      if (url.endsWith("/api/v1/files/22/download")) {
        return new Response(
          '<svg xmlns="http://www.w3.org/2000/svg"><text x="0" y="16">恢复预览</text></svg>',
          { status: 200, headers: { "Content-Type": "image/svg+xml" } },
        );
      }
      throw new Error(`unexpected request: ${url}`);
    });
    const adapter = new HttpPptWorkflowAdapter({
      baseUrl: "http://backend.test:8000",
      getAccessToken: () => "token-1",
      fetchImpl,
    });

    const [slide] = await adapter.restoreSlideAssets([{
      id: "slide-1",
      index: 1,
      title: "恢复预览",
      status: "ready",
      elements: [],
      previewArtifactId: 22,
      thumbnailArtifactId: 22,
      userModifiedFields: [],
      revision: 1,
    }]);

    expect(slide.previewUrl).toBe("blob:preview-1");
    expect(slide.thumbnailUrl).toBe("blob:preview-1");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("releases Blob preview URLs when the adapter is disposed", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/ppt-master/generate-incremental")) {
        return new Response(byteStream(incrementalFrames()), {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      if (url.endsWith("/api/v1/files/11/download")) {
        return new Response(
          '<svg xmlns="http://www.w3.org/2000/svg"><text x="0" y="16">封面</text></svg>',
          { status: 200, headers: { "Content-Type": "image/svg+xml" } },
        );
      }
      throw new Error(`unexpected request: ${url}`);
    });
    const adapter = new HttpPptWorkflowAdapter({
      baseUrl: "http://backend.test:8000",
      getAccessToken: () => "token-1",
      fetchImpl,
    });

    await collect(adapter);
    (adapter as unknown as { dispose: () => void }).dispose();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview-1");
  });

  it("falls back to Legacy when the incremental endpoint is unavailable", async () => {
    const fallbackEvents: PptWorkflowEvent[] = [{
      eventId: "fallback-1",
      taskId: "legacy-task-1",
      projectId: "project-1",
      chatId: "chat-1",
      sequence: 1,
      timestamp: "2026-07-20T00:00:00.000Z",
      type: "task.started",
      payload: { requestId: "legacy-1", pageCount: 1 },
    }, {
      eventId: "fallback-2",
      taskId: "legacy-task-1",
      projectId: "project-1",
      chatId: "chat-1",
      sequence: 2,
      timestamp: "2026-07-20T00:00:01.000Z",
      type: "task.completed",
      payload: {},
    }];
    const fallbackAdapter: PptWorkflowAdapter = {
      capabilities: {
        incrementalOutline: false,
        incrementalSlides: false,
        taskCancellation: false,
        taskResume: false,
        slideRegeneration: false,
        proposalApply: false,
        fileDownload: true,
      },
      async *start() {
        yield* fallbackEvents;
      },
    };
    const adapter = new HttpPptWorkflowAdapter({
      baseUrl: "http://backend.test:8000",
      getAccessToken: () => "token-1",
      fetchImpl: vi.fn(async () => new Response("missing", { status: 404 })),
      fallbackAdapter,
    });

    const events = await collect(adapter);

    expect(events).toEqual(fallbackEvents);
  });
});
