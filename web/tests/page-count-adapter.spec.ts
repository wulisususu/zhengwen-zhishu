import { describe, expect, it, vi } from "vitest";
import { HttpPptWorkflowAdapter } from "../src/features/ppt-workbench/adapters/HttpPptWorkflowAdapter";

describe("PPT page count request source", () => {
  it("uses the task page count instead of the adapter default", async () => {
    let request: RequestInit | undefined;
    const adapter = new HttpPptWorkflowAdapter({
      baseUrl: "http://backend.test:8000",
      pageCount: 8,
      getAccessToken: () => "token",
      requestIdFactory: () => "request-page-5",
      fetchImpl: vi.fn(async (_input, init) => {
        request = init;
        return new Response(null, { status: 500 });
      }),
    });

    const events = [];
    for await (const event of adapter.start({ projectId: "p", chatId: "c", prompt: "保护环境", pageCount: 5 })) {
      events.push(event);
    }

    expect(JSON.parse(String(request?.body))).toMatchObject({ page_count: 5 });
    expect(events[0]?.payload).toMatchObject({ pageCount: 5 });
  });
});
