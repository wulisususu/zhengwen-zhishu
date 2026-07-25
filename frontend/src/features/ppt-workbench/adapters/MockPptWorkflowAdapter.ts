import { mockWorkflowCapabilities } from "../protocol/capabilities";
import type { PptWorkflowEvent } from "../protocol/events";
import type { OutlineItem, Slide } from "../types/presentation";
import type { StartPptWorkflowInput, PptWorkflowAdapter } from "./PptWorkflowAdapter";
import { createClientUuid } from "../utils/uuid";

const DEFAULT_DELAY_MS = 500;

export class MockPptWorkflowAdapter implements PptWorkflowAdapter {
  readonly capabilities = mockWorkflowCapabilities;

  constructor(private readonly delayMs = DEFAULT_DELAY_MS) {}

  async *start(input: StartPptWorkflowInput): AsyncIterable<PptWorkflowEvent> {
    const taskId = `mock-task-${createClientUuid()}`;
    let sequence = 0;
    const emit = <T>(type: PptWorkflowEvent<T>["type"], payload: T): PptWorkflowEvent<T> => ({
      eventId: createClientUuid(),
      taskId,
      projectId: input.projectId,
      chatId: input.chatId,
      sequence: ++sequence,
      timestamp: new Date().toISOString(),
      type,
      payload,
    });

    yield emit("task.started", { prompt: input.prompt });
    yield* this.withDelay(emit("assistant.text.delta", { text: "我先梳理演示目标、受众与叙事结构。" }));
    yield* this.withDelay(emit("brief.ready", {
      brief: {
        goal: input.prompt,
        audience: "目标受众",
        slideCount: 4,
        constraints: ["清晰、专业、可展示"],
      },
    }));

    const outline: OutlineItem[] = [
      { id: "outline-1", title: "封面：核心主题", description: "明确演示主题与价值主张", status: "ready", children: [] },
      { id: "outline-2", title: "现状与问题", description: "说明背景、挑战与机会", status: "ready", children: [] },
      { id: "outline-3", title: "解决方案", description: "展示方案结构和关键能力", status: "ready", children: [] },
      { id: "outline-4", title: "落地路径", description: "列出执行节奏和预期成果", status: "ready", children: [] },
    ];
    for (const item of outline) {
      yield* this.withDelay(emit("outline.item.added", { item }));
    }
    yield* this.withDelay(emit("outline.ready", { outline }));
    yield* this.withDelay(emit("design.ready", {
      theme: { id: "theme-professional-blue", name: "专业蓝", primaryColor: "#2563eb", backgroundColor: "#f8fafc", fontFamily: "Microsoft YaHei" },
    }));

    for (const item of outline) {
      const slide: Slide = {
        id: `slide-${outline.indexOf(item) + 1}`,
        index: outline.indexOf(item) + 1,
        title: item.title,
        status: "generating",
        revision: 1,
        elements: [],
        userModifiedFields: [],
      };
      yield* this.withDelay(emit("slide.started", { slide }));
      const completedSlide: Slide = {
        ...slide,
        status: "ready",
        elements: [{ id: `${slide.id}-title`, type: "text", text: item.title, x: 80, y: 64, width: 920, height: 80, fontSize: 34, color: "#0f172a" }],
      };
      yield* this.withDelay(emit("slide.completed", { slide: completedSlide }));
    }

    yield* this.withDelay(emit("proposal.created", {
      proposal: {
        id: "mock-proposal-1",
        taskId,
        projectId: input.projectId,
        status: "pending",
        target: "slide",
        targetId: "slide-2",
        summary: "建议将第二页标题改为更聚焦的表述。",
        patch: { slideId: "slide-2", field: "title", from: "现状与问题", to: "关键挑战与机会" },
        baseProjectVersion: 1,
        createdAt: new Date().toISOString(),
      },
    }));
    yield* this.withDelay(emit("validation.completed", {
      result: { score: 100, issues: [], checkedAt: new Date().toISOString() },
    }));
    yield* this.withDelay(emit("export.ready", { downloadUrl: "/mock/presentation.pptx" }));
    yield emit("task.completed", { finishedAt: new Date().toISOString() });
  }

  private async *withDelay<T>(event: T): AsyncIterable<T> {
    await new Promise<void>((resolve) => window.setTimeout(resolve, this.delayMs));
    yield event;
  }
}
