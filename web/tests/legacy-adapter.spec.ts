import { describe, expect, it, vi } from "vitest";
import {
  LegacyPptMasterAdapter,
  mapLegacyPptMasterEvent,
  type LegacyPptMasterAdapterOptions,
} from "../src/features/ppt-workbench/adapters/LegacyPptMasterAdapter";
import type { PptWorkflowEvent } from "../src/features/ppt-workbench/protocol/events";
import type { PptExportArtifact } from "../src/features/ppt-workbench/types/project";
import type { GenerationStatus } from "../src/features/ppt-workbench/types/task";
import {
  allSuccessfulLegacyFrames,
  byteStream,
  doneEventWithForbiddenPathGetters,
  externalOriginDoneFrame,
  fallbackLegacyFrame,
  incompleteLegacyFrames,
  invalidDoneFrame,
  legacyProgressStageCases,
  legacyProgressEvent,
  malformedDoneFrame,
  sensitiveFallbackFrame,
  sensitiveProgressFrame,
  validDoneFrame,
} from "./fixtures/legacySse";

const input = { projectId: "project-1", chatId: "chat-1", prompt: "生成一页产品介绍" };

function sseResponse(frames: string, init?: ResponseInit) {
  return new Response(byteStream([frames]), {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
    ...init,
  });
}

function adapterOptions(overrides: Partial<LegacyPptMasterAdapterOptions> = {}): LegacyPptMasterAdapterOptions {
  return {
    baseUrl: "http://backend.test:8000",
    getAccessToken: () => "test-token",
    requestIdFactory: () => "request-fixed-1",
    fetchImpl: vi.fn(async () => sseResponse(validDoneFrame)),
    ...overrides,
  };
}

async function collect(adapter: LegacyPptMasterAdapter): Promise<PptWorkflowEvent[]> {
  const events: PptWorkflowEvent[] = [];
  for await (const event of adapter.start(input)) events.push(event);
  return events;
}

describe("LegacyPptMasterAdapter contract", () => {
  it("declares only the capabilities implemented by the one-shot backend", () => {
    const adapter = new LegacyPptMasterAdapter();

    expect(adapter.capabilities).toEqual({
      incrementalOutline: false,
      incrementalSlides: false,
      taskCancellation: false,
      taskResume: false,
      slideRegeneration: false,
      proposalApply: false,
      fileDownload: true,
    });
  });

  it("exposes interrupted generation and normalized export contracts", () => {
    const interrupted: GenerationStatus = "interrupted";
    const artifact: PptExportArtifact = {
      fileId: 594,
      downloadUrl: "http://example.test/api/v1/files/594/download",
      size: 14_469,
      sha256: "abc123",
      valid: true,
      warnings: [],
    };
    const adapter = new LegacyPptMasterAdapter();

    expect(interrupted).toBe("interrupted");
    expect(artifact.fileId).toBe(594);
    expect(typeof adapter.download).toBe("function");
  });

  it("sends the production request contract with one stable idempotency key", async () => {
    const fetchImpl = vi.fn(async () => sseResponse(validDoneFrame));
    const adapter = new LegacyPptMasterAdapter(adapterOptions({
      fetchImpl,
      pageCount: 8,
      pageFormat: "ppt169",
    }));

    await collect(adapter);

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://backend.test:8000/api/v1/ppt-master/generate");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      Authorization: "Bearer test-token",
      "Content-Type": "application/json",
      "Idempotency-Key": "request-fixed-1",
    });
    expect(JSON.parse(String(init.body))).toEqual({
      user_input: input.prompt,
      page_count: 8,
      page_format: "ppt169",
      sources: [],
      request_id: "request-fixed-1",
    });
  });

  it("keeps request_id unchanged across a bounded network retry", async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("connection reset"))
      .mockResolvedValueOnce(sseResponse(validDoneFrame));
    const requestIdFactory = vi.fn(() => "request-retry-stable");
    const adapter = new LegacyPptMasterAdapter(adapterOptions({
      fetchImpl,
      requestIdFactory,
      maxNetworkRetries: 1,
      retryDelayMs: 0,
    }));

    await collect(adapter);

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(requestIdFactory).toHaveBeenCalledTimes(1);
    const ids = fetchImpl.mock.calls.map((call) => {
      const init = call[1] as RequestInit;
      return {
        header: (init.headers as Record<string, string>)["Idempotency-Key"],
        body: JSON.parse(String(init.body)).request_id,
      };
    });
    expect(ids).toEqual([
      { header: "request-retry-stable", body: "request-retry-stable" },
      { header: "request-retry-stable", body: "request-retry-stable" },
    ]);
  });

  it("normalizes all five Legacy event types at the adapter boundary", async () => {
    const events = await collect(new LegacyPptMasterAdapter(adapterOptions({
      fetchImpl: vi.fn(async () => sseResponse(allSuccessfulLegacyFrames)),
    })));

    expect(events.map((event) => event.type)).toEqual([
      "task.started",
      "assistant.text.delta",
      "design.ready",
      "validation.completed",
      "export.ready",
      "task.completed",
    ]);
    expect(events[0]?.payload).toMatchObject({ requestId: "request-fixed-1", pageCount: 8 });
    expect(events[1]?.payload).toMatchObject({
      stage: "design",
      progress: 15,
      text: "正在规划设计方案",
      presentation: "stage-card",
    });
    expect(JSON.stringify(events)).not.toContain("Planning design specification");
    expect(events[2]?.payload).not.toHaveProperty("theme");
    expect(events[4]?.payload).toMatchObject({
      artifact: {
        fileId: 594,
        downloadUrl: "http://backend.test:8000/api/v1/files/594/download",
        warnings: ["字体已替换"],
      },
    });

    const fallbackEvents = await collect(new LegacyPptMasterAdapter(adapterOptions({
      fetchImpl: vi.fn(async () => sseResponse(fallbackLegacyFrame)),
    })));
    expect(fallbackEvents.at(-1)).toMatchObject({
      type: "task.failed",
      payload: { error: { code: "RENDER_FAILED", message: "渲染失败" } },
    });
  });

  it.each(legacyProgressStageCases)("maps %s progress to a Chinese stage card without leaking raw text", (step, message, stage, text) => {
    const [mapped] = mapLegacyPptMasterEvent(
      legacyProgressEvent(step, message),
      { taskId: "task-1", projectId: "project-1", chatId: "chat-1", sequence: 2 },
    );

    expect(mapped.payload).toMatchObject({ stage, text, presentation: "stage-card" });
    expect(JSON.stringify(mapped.payload)).not.toContain(message);
  });

  it.each([
    [401, "AUTHENTICATION_REQUIRED", false],
    [409, "IDEMPOTENT_TASK_RUNNING", true],
    [429, "RATE_LIMITED", true],
    [413, "REQUEST_TOO_LARGE", false],
    [422, "INVALID_REQUEST", false],
    [507, "PROJECT_QUOTA_EXCEEDED", false],
  ] as const)("maps HTTP %i without retry storms", async (status, code, retryable) => {
    const fetchImpl = vi.fn(async () => new Response('{"detail":"backend detail"}', {
      status,
      headers: status === 429 ? { "Retry-After": "7", "Content-Type": "application/json" } : undefined,
    }));
    const onUnauthorized = vi.fn();
    const events = await collect(new LegacyPptMasterAdapter(adapterOptions({ fetchImpl, onUnauthorized })));
    const failure = events.at(-1);

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(failure).toMatchObject({
      type: "task.failed",
      payload: { error: { code, retryable, httpStatus: status } },
    });
    if (status === 429) {
      expect(failure?.payload).toMatchObject({ error: { retryAfterSeconds: 7 } });
    }
    expect(onUnauthorized).toHaveBeenCalledTimes(status === 401 ? 1 : 0);
    if (status === 429) expect(failure?.payload).not.toMatchObject({ terminalStatus: "interrupted" });
    if (status === 409) expect(failure?.payload).toMatchObject({ terminalStatus: "interrupted" });
  });

  it("parses an HTTP-date Retry-After without retrying automatically", async () => {
    const retryAt = new Date(Date.now() + 5_000).toUTCString();
    const fetchImpl = vi.fn(async () => new Response(null, { status: 429, headers: { "Retry-After": retryAt } }));
    const events = await collect(new LegacyPptMasterAdapter(adapterOptions({ fetchImpl })));
    const seconds = ((events.at(-1)?.payload as { error?: { retryAfterSeconds?: number } }).error?.retryAfterSeconds);

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(seconds).toBeGreaterThanOrEqual(1);
    expect(seconds).toBeLessThanOrEqual(5);
  });

  it("marks a stream that ends without a terminal event as interrupted", async () => {
    const events = await collect(new LegacyPptMasterAdapter(adapterOptions({
      fetchImpl: vi.fn(async () => sseResponse(incompleteLegacyFrames)),
    })));

    expect(events.at(-1)).toMatchObject({
      type: "task.failed",
      payload: {
        terminalStatus: "interrupted",
        error: { code: "LEGACY_STREAM_INTERRUPTED", retryable: true },
      },
    });
  });

  it("treats AbortController disconnect as a connection interruption, not task cancellation", async () => {
    const fetchImpl = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));
    const adapter = new LegacyPptMasterAdapter(adapterOptions({ fetchImpl }));
    const iterator = adapter.start(input)[Symbol.asyncIterator]();
    const started = await iterator.next();
    const terminalPromise = iterator.next();
    await Promise.resolve();

    adapter.disconnect(started.value.taskId);
    const terminal = await terminalPromise;

    expect(terminal.value).toMatchObject({
      type: "task.failed",
      payload: { terminalStatus: "interrupted", error: { code: "LEGACY_NETWORK_INTERRUPTED" } },
    });
    expect(terminal.value.type).not.toBe("task.cancelled");
  });

  it("does not complete or expose a download when done validation is inconsistent", async () => {
    const events = await collect(new LegacyPptMasterAdapter(adapterOptions({
      fetchImpl: vi.fn(async () => sseResponse(invalidDoneFrame)),
    })));

    expect(events.some((event) => event.type === "export.ready")).toBe(false);
    expect(events.some((event) => event.type === "task.completed")).toBe(false);
    expect(events.at(-1)).toMatchObject({
      type: "task.failed",
      payload: { error: { code: "LEGACY_VALIDATION_FAILED" } },
    });
    expect(events.find((event) => event.type === "validation.completed")?.payload).toMatchObject({
      validation: {
        issues: [expect.objectContaining({ message: "发现阻断问题", blocking: true })],
      },
    });
  });

  it("rejects malformed payloads as protocol errors instead of stream interruptions", async () => {
    const events = await collect(new LegacyPptMasterAdapter(adapterOptions({
      fetchImpl: vi.fn(async () => sseResponse(malformedDoneFrame)),
    })));

    expect(events.at(-1)).toMatchObject({
      type: "task.failed",
      payload: { error: { code: "LEGACY_EVENT_INVALID", retryable: false } },
    });
    expect(events.at(-1)?.payload).not.toMatchObject({ terminalStatus: "interrupted" });
  });

  it("rejects a cross-origin download URL before it becomes an export artifact", async () => {
    const events = await collect(new LegacyPptMasterAdapter(adapterOptions({
      fetchImpl: vi.fn(async () => sseResponse(externalOriginDoneFrame)),
    })));

    expect(events.some((event) => event.type === "export.ready")).toBe(false);
    expect(events.at(-1)).toMatchObject({
      type: "task.failed",
      payload: { error: { code: "LEGACY_DOWNLOAD_ORIGIN_FORBIDDEN" } },
    });
  });

  it("does not expose backend paths from progress or fallback messages", async () => {
    const progressEvents = await collect(new LegacyPptMasterAdapter(adapterOptions({
      fetchImpl: vi.fn(async () => sseResponse(`${sensitiveProgressFrame}${fallbackLegacyFrame}`)),
    })));
    expect(JSON.stringify(progressEvents)).not.toContain("/home/service");

    const fallbackEvents = await collect(new LegacyPptMasterAdapter(adapterOptions({
      fetchImpl: vi.fn(async () => sseResponse(sensitiveFallbackFrame)),
    })));
    expect(fallbackEvents.at(-1)).toMatchObject({
      payload: { error: { message: "PPT 生成失败" } },
    });
    expect(JSON.stringify(fallbackEvents)).not.toContain("secret.pptx");
  });

  it("cancels the unread response body after the first terminal event", async () => {
    const cancelled = vi.fn();
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(encoder.encode(validDoneFrame)); },
      cancel: cancelled,
    });
    const events = await collect(new LegacyPptMasterAdapter(adapterOptions({
      fetchImpl: vi.fn(async () => new Response(stream, { status: 200 })),
    })));

    expect(events.at(-1)?.type).toBe("task.completed");
    expect(cancelled).toHaveBeenCalledTimes(1);
  });

  it("never reads backend filesystem path fields from done data", () => {
    expect(() => mapLegacyPptMasterEvent(
      doneEventWithForbiddenPathGetters() as never,
      { taskId: "task-1", projectId: "project-1", chatId: "chat-1", sequence: 1, baseUrl: "http://backend.test:8000" },
    )).not.toThrow();
  });

  it("rejects invalid page settings before making a request", async () => {
    const fetchImpl = vi.fn();
    const events = await collect(new LegacyPptMasterAdapter(adapterOptions({
      fetchImpl,
      pageCount: 13,
      pageFormat: "ppt169",
    })));

    expect(fetchImpl).not.toHaveBeenCalled();
    expect(events.at(-1)).toMatchObject({
      type: "task.failed",
      payload: { error: { code: "INVALID_REQUEST" } },
    });
  });
});
