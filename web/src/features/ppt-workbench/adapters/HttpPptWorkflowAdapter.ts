import type { WorkflowCapabilities } from "../protocol/capabilities";
import type { PptWorkflowEvent, PptWorkflowEventType } from "../protocol/events";
import type { PptExportArtifact, PptBrief, PresentationProject } from "../types/project";
import type { OutlineItem, Slide, ValidationIssue, ValidationResult } from "../types/presentation";
import type { WorkflowError, WorkflowStage } from "../types/task";
import type {
  DownloadedPptFile,
  PptWorkflowAdapter,
  StartPptWorkflowInput,
} from "./PptWorkflowAdapter";
import { parseSseStream } from "./legacySseParser";
import { createClientUuid } from "../utils/uuid";
import {
  digestBlobSha256,
  downloadLegacyArtifact,
  saveBlobWithObjectUrl,
} from "./legacyDownload";
import { normalizePageCount } from "../utils/pageCount";

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type PageFormat = "ppt169" | "ppt43";

interface IncrementalValidationResult {
  passed?: unknown;
  warnings?: unknown[];
  errors?: unknown[];
  blocking_errors?: unknown[];
}

interface IncrementalFinalFile {
  file_id?: unknown;
  download_url?: unknown;
  size?: unknown;
  sha256?: unknown;
  valid?: unknown;
  validation_result?: IncrementalValidationResult;
  slide_count?: unknown;
}

interface IncrementalPlanningData {
  page_count?: unknown;
  outline?: unknown[];
  design_summary?: unknown;
}

interface IncrementalSlideData {
  slide_id?: unknown;
  index?: unknown;
  title?: unknown;
  status?: unknown;
  preview_file_id?: unknown;
  preview_url?: unknown;
  thumbnail_file_id?: unknown;
  thumbnail_url?: unknown;
  notes?: unknown;
  revision?: unknown;
  errors?: unknown[];
}

interface IncrementalTaskFailedData {
  code?: unknown;
  failed_indices?: unknown[];
  completed_slide_count?: unknown;
}

interface IncrementalEnvelope<T = Record<string, unknown>> {
  event_id: string;
  event_type: string;
  task_id: string;
  project_id: string;
  sequence: number;
  timestamp: string;
  data: T;
}

export interface HttpPptWorkflowAdapterOptions {
  baseUrl?: string;
  endpointPath?: string;
  getAccessToken?: () => string | Promise<string>;
  onUnauthorized?: () => void | Promise<void>;
  pageCount?: number;
  pageFormat?: PageFormat;
  requestIdFactory?: () => string;
  fetchImpl?: FetchLike;
  maxNetworkRetries?: number;
  retryDelayMs?: number;
  maxPreviewBytes?: number;
  saveBlob?: (blob: Blob, filename: string) => void | Promise<void>;
  digestSha256?: (blob: Blob) => Promise<string>;
  verifyDownloadSha256?: boolean;
  fallbackAdapter?: PptWorkflowAdapter;
}

const capabilities: WorkflowCapabilities = {
  incrementalOutline: true,
  incrementalSlides: true,
  taskCancellation: false,
  taskResume: false,
  slideRegeneration: false,
  proposalApply: false,
  fileDownload: true,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function asText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value instanceof Error) return value.message;
  if (value && typeof value === "object" && "message" in value && typeof value.message === "string") return value.message;
  return String(value ?? "");
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(asText).filter(Boolean) : [];
}

function safeSummaryText(value: unknown, fallback: string): string {
  if (typeof value !== "string") return fallback;
  const normalized = value.replace(/\s+/g, " ").trim().slice(0, 300);
  return normalized || fallback;
}

function absoluteUrl(baseUrl: string, path: string): string | null {
  try {
    const base = new URL(`${baseUrl.replace(/\/+$/, "")}/`);
    const resolved = new URL(path, base);
    return resolved.origin === base.origin ? resolved.toString() : null;
  } catch {
    return null;
  }
}

function parseRetryAfter(value: string | null): number | undefined {
  if (!value) return undefined;
  if (/^\d+$/.test(value.trim())) return Number.parseInt(value, 10);
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return undefined;
  return Math.max(0, Math.ceil((timestamp - Date.now()) / 1000));
}

function httpFailure(status: number, retryAfter: string | null): WorkflowError {
  const retryAfterSeconds = parseRetryAfter(retryAfter);
  const table: Record<number, WorkflowError> = {
    401: { code: "AUTHENTICATION_REQUIRED", message: "登录状态已失效，请重新登录", retryable: false, httpStatus: 401 },
    409: { code: "IDEMPOTENT_TASK_RUNNING", message: "任务仍在生成", retryable: true, httpStatus: 409 },
    413: { code: "REQUEST_TOO_LARGE", message: "请求内容过大", retryable: false, httpStatus: 413 },
    422: { code: "INVALID_REQUEST", message: "生成参数不合法", retryable: false, httpStatus: 422 },
    429: { code: "RATE_LIMITED", message: "生成服务繁忙，请稍后重试", retryable: true, httpStatus: 429, retryAfterSeconds },
    507: { code: "PROJECT_QUOTA_EXCEEDED", message: "服务器存储不足", retryable: false, httpStatus: 507 },
  };
  return table[status] ?? {
    code: "INCREMENTAL_HTTP_ERROR",
    message: "增量 PPT 服务请求失败",
    retryable: status >= 500,
    httpStatus: status,
  };
}

function toValidationResult(raw: IncrementalValidationResult): ValidationResult {
  const warnings = asStringList(raw.warnings);
  const errors = asStringList(raw.errors);
  const blocking = asStringList(raw.blocking_errors);
  const issues: ValidationIssue[] = [
    ...warnings.map((message, index) => ({ id: `warning-${index + 1}`, severity: "warning" as const, message })),
    ...errors.map((message, index) => ({ id: `error-${index + 1}`, severity: "error" as const, message })),
    ...blocking.map((message, index) => ({ id: `blocking-${index + 1}`, severity: "error" as const, message, blocking: true })),
  ];
  const passed = raw.passed === true && blocking.length === 0 && errors.length === 0;

  return {
    score: passed ? (warnings.length ? 85 : 100) : 0,
    issues,
    checkedAt: new Date().toISOString(),
  };
}

function outlineFromPlanning(data: IncrementalPlanningData): OutlineItem[] {
  const items = Array.isArray(data.outline) ? data.outline : [];
  return items.map((item, offset) => {
    const record = isRecord(item) ? item : {};
    const index = Number(record.index);
    const title = safeSummaryText(record.title, `第 ${offset + 1} 页`);
    const description = safeSummaryText(record.description, `${title} 页面内容`);
    return {
      id: `outline-${Number.isFinite(index) && index > 0 ? index : offset + 1}`,
      title,
      description,
      status: "ready" as const,
      children: [],
    };
  });
}

function briefFromPlanning(prompt: string, data: IncrementalPlanningData): PptBrief {
  const summary = isRecord(data.design_summary) ? data.design_summary : {};
  return {
    goal: safeSummaryText(summary.preview, safeSummaryText(prompt, "根据当前需求生成演示文稿")),
    audience: safeSummaryText(summary.audience, "待确认"),
    slideCount: Number.isInteger(data.page_count) ? Number(data.page_count) : 0,
    constraints: [],
  };
}

function stageCardPayload(stage: WorkflowStage, text: string, progress: number) {
  return {
    text,
    stage,
    progress,
    presentation: "stage-card" as const,
  };
}

function failedTaskMessage(code: string, validation?: ValidationResult, failedIndices?: number[]): string {
  const blocking = validation?.issues.find((issue) => issue.blocking)?.message;
  const error = validation?.issues.find((issue) => issue.severity === "error")?.message;
  switch (code) {
    case "validation_failed":
      return blocking ?? error ?? "PPT 质检未通过，请先处理阻断项";
    case "slide_generation_failed":
      return failedIndices?.length
        ? `第 ${failedIndices.join("、")} 页生成失败，已保留其他已完成页面`
        : "部分页面生成失败，已保留其他已完成页面";
    case "export_failed":
      return "PPTX 导出失败，请稍后重试";
    default:
      return "增量 PPT 工作流执行失败";
  }
}

function sequenceWithOffset(sequence: number, offset: number): number {
  return sequence + offset / 100;
}

function makeSyntheticEvent<T>(
  taskId: string,
  projectId: string,
  chatId: string,
  sequence: number,
  type: PptWorkflowEventType,
  payload: T,
): PptWorkflowEvent<T> {
  return {
    eventId: `${taskId}-${sequence}-${type}`,
    taskId,
    projectId,
    chatId,
    sequence,
    timestamp: new Date().toISOString(),
    type,
    payload,
  };
}

function makeMappedEvent<T>(
  envelope: IncrementalEnvelope,
  projectId: string,
  chatId: string,
  type: PptWorkflowEventType,
  payload: T,
  offset = 0,
): PptWorkflowEvent<T> {
  return {
    eventId: `${envelope.event_id}:${type}:${offset}`,
    taskId: envelope.task_id,
    projectId,
    chatId,
    sequence: sequenceWithOffset(envelope.sequence, offset),
    timestamp: envelope.timestamp,
    type,
    payload,
  };
}

function isSafeSvg(text: string): boolean {
  const lowered = text.toLowerCase().replace("http://www.w3.org/2000/svg", "");
  return ![
    "file://", "http://", "https://", "<script", "<!doctype", "<!entity",
    "<foreignobject", "<use", "<image", "xlink:href", "href=", "url(",
  ].some((marker) => lowered.includes(marker));
}

async function wait(milliseconds: number): Promise<void> {
  if (milliseconds <= 0) return;
  await new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export class HttpPptWorkflowAdapter implements PptWorkflowAdapter {
  readonly capabilities = capabilities;
  private readonly activeConnections = new Map<string, AbortController>();
  private readonly previewObjectUrls = new Set<string>();
  private readonly options: Required<Pick<HttpPptWorkflowAdapterOptions,
    "baseUrl" | "endpointPath" | "getAccessToken" | "pageCount" | "pageFormat" |
    "requestIdFactory" | "fetchImpl" | "maxNetworkRetries" | "retryDelayMs" |
    "maxPreviewBytes" | "saveBlob" | "digestSha256" | "verifyDownloadSha256">>
    & Pick<HttpPptWorkflowAdapterOptions, "onUnauthorized" | "fallbackAdapter">;

  constructor(options: HttpPptWorkflowAdapterOptions = {}) {
    this.options = {
      baseUrl: options.baseUrl ?? "http://192.168.0.117:8000",
      endpointPath: options.endpointPath ?? "/api/v1/ppt-master/generate-incremental",
      getAccessToken: options.getAccessToken ?? (() => ""),
      onUnauthorized: options.onUnauthorized,
      pageCount: options.pageCount ?? 8,
      pageFormat: options.pageFormat ?? "ppt169",
      requestIdFactory: options.requestIdFactory ?? createClientUuid,
      fetchImpl: options.fetchImpl ?? fetch.bind(globalThis),
      maxNetworkRetries: Math.max(0, options.maxNetworkRetries ?? 0),
      retryDelayMs: Math.max(0, options.retryDelayMs ?? 500),
      maxPreviewBytes: Math.max(1, options.maxPreviewBytes ?? 5 * 1024 * 1024),
      saveBlob: options.saveBlob ?? saveBlobWithObjectUrl,
      digestSha256: options.digestSha256 ?? digestBlobSha256,
      verifyDownloadSha256: options.verifyDownloadSha256 ?? true,
      fallbackAdapter: options.fallbackAdapter,
    };
  }

  async *start(input: StartPptWorkflowInput): AsyncGenerator<PptWorkflowEvent> {
    const requestId = this.options.requestIdFactory();
    const pageCount = normalizePageCount(input.pageCount, normalizePageCount(this.options.pageCount));
    const provisionalTaskId = `incremental-${requestId}`;
    const endpoint = absoluteUrl(this.options.baseUrl, this.options.endpointPath);
    if (!endpoint) {
      yield makeSyntheticEvent(provisionalTaskId, input.projectId, input.chatId, 0, "task.started", { requestId, pageCount });
      yield makeSyntheticEvent(provisionalTaskId, input.projectId, input.chatId, 1, "task.failed", {
        error: { code: "INVALID_REQUEST", message: "增量 PPT 服务地址未通过安全校验", retryable: false },
      });
      return;
    }

    if (!input.prompt.trim() || pageCount < 3 || pageCount > 12
      || !Number.isInteger(pageCount)
      || !(["ppt169", "ppt43"] as const).includes(this.options.pageFormat)) {
      yield makeSyntheticEvent(provisionalTaskId, input.projectId, input.chatId, 0, "task.started", { requestId, pageCount });
      yield makeSyntheticEvent(provisionalTaskId, input.projectId, input.chatId, 1, "task.failed", {
        error: { code: "INVALID_REQUEST", message: "PPT 生成参数不合法", retryable: false },
      });
      return;
    }

    const token = await this.options.getAccessToken();
    if (!token) {
      await this.options.onUnauthorized?.();
          yield makeSyntheticEvent(provisionalTaskId, input.projectId, input.chatId, 0, "task.started", { requestId, pageCount });
      yield makeSyntheticEvent(provisionalTaskId, input.projectId, input.chatId, 1, "task.failed", {
        error: { code: "AUTHENTICATION_REQUIRED", message: "登录状态已失效，请重新登录", retryable: false, httpStatus: 401 },
      });
      return;
    }

    const controller = new AbortController();
    let liveTaskId = provisionalTaskId;
    const init: RequestInit = {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": requestId,
      },
      body: JSON.stringify({
        user_input: input.prompt,
        page_count: pageCount,
        page_format: this.options.pageFormat,
        sources: [],
        attachment_file_ids: input.attachmentFileIds ?? [],
        knowledge_doc_ids: input.knowledgeDocIds ?? [],
        source_policy: input.sourcePolicy ?? "parsed_only",
        request_id: requestId,
        ...(input.pptxStructureMode ? { pptx_structure_mode: input.pptxStructureMode } : {}),
        ...(input.structuredWorkspaceId ? { structured_workspace_id: input.structuredWorkspaceId } : {}),
      }),
      signal: controller.signal,
    };

    let response: Response | null = null;
    try {
      for (let attempt = 0; attempt <= this.options.maxNetworkRetries; attempt += 1) {
        try {
          response = await this.options.fetchImpl(endpoint, init);
          break;
        } catch (cause) {
          if (!controller.signal.aborted && attempt < this.options.maxNetworkRetries) {
            await wait(this.options.retryDelayMs);
            continue;
          }
          yield makeSyntheticEvent(provisionalTaskId, input.projectId, input.chatId, 0, "task.started", { requestId, pageCount });
          yield makeSyntheticEvent(provisionalTaskId, input.projectId, input.chatId, 1, "task.failed", {
            terminalStatus: "interrupted",
            error: {
              code: "INCREMENTAL_NETWORK_INTERRUPTED",
              message: cause instanceof DOMException && cause.name === "AbortError"
                ? "与增量 PPT 服务的连接已断开"
                : "增量 PPT 服务连接失败",
              retryable: true,
            },
          });
          return;
        }
      }

      if (!response) return;
      if (!response.ok) {
        if (response.status === 401) await this.options.onUnauthorized?.();
        if ([404, 405, 501].includes(response.status) && this.options.fallbackAdapter) {
          yield* this.options.fallbackAdapter.start(input);
          return;
        }
        yield makeSyntheticEvent(provisionalTaskId, input.projectId, input.chatId, 0, "task.started", { requestId, pageCount });
        yield makeSyntheticEvent(provisionalTaskId, input.projectId, input.chatId, 1, "task.failed", {
          error: httpFailure(response.status, response.headers.get("Retry-After")),
        });
        return;
      }

      if (!response.body) {
        yield makeSyntheticEvent(provisionalTaskId, input.projectId, input.chatId, 0, "task.started", { requestId, pageCount });
        yield makeSyntheticEvent(provisionalTaskId, input.projectId, input.chatId, 1, "task.failed", {
          terminalStatus: "interrupted",
          error: { code: "INCREMENTAL_STREAM_INTERRUPTED", message: "增量 PPT 服务未返回事件流", retryable: true },
        });
        return;
      }

      let started = false;
      let finalValidation: ValidationResult | null = null;

      for await (const message of parseSseStream(response.body)) {
        let envelope: IncrementalEnvelope | null = null;
        try {
          envelope = JSON.parse(message.data) as IncrementalEnvelope;
        } catch {
          yield makeSyntheticEvent(liveTaskId, input.projectId, input.chatId, 1, "task.failed", {
            error: { code: "INCREMENTAL_EVENT_INVALID", message: "增量 PPT 服务返回了无法解析的事件", retryable: false },
          });
          return;
        }
        if (!envelope || typeof envelope.event_id !== "string" || typeof envelope.event_type !== "string"
          || typeof envelope.task_id !== "string" || typeof envelope.sequence !== "number"
          || !isRecord(envelope.data)) {
          yield makeSyntheticEvent(liveTaskId, input.projectId, input.chatId, 1, "task.failed", {
            error: { code: "INCREMENTAL_EVENT_INVALID", message: "增量 PPT 服务返回了不符合契约的事件", retryable: false },
          });
          return;
        }

        liveTaskId = envelope.task_id;
        if (!started) {
          this.activeConnections.set(liveTaskId, controller);
          yield makeSyntheticEvent(liveTaskId, input.projectId, input.chatId, 0, "task.started", {
            requestId,
            pageCount,
            backendProjectId: envelope.project_id,
          });
          started = true;
        }

        if (envelope.event_type === "planning.started") {
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "assistant.text.delta", stageCardPayload("understanding", "正在分析需求", 12));
          continue;
        }

        if (envelope.event_type === "planning.completed") {
          const planning = envelope.data as IncrementalPlanningData;
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "brief.ready", {
            brief: briefFromPlanning(input.prompt, planning),
          });
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "outline.ready", {
            outline: outlineFromPlanning(planning),
          }, 1);
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "design.ready", {
            specification: {
              designSummary: isRecord(planning.design_summary) ? planning.design_summary : {},
              pageCount: planning.page_count,
            },
          }, 2);
          continue;
        }

        if (envelope.event_type === "slide.started") {
          const slideData = envelope.data as IncrementalSlideData;
          const index = Number(slideData.index);
          const slide: Slide = {
            id: typeof slideData.slide_id === "string" ? slideData.slide_id : `${envelope.task_id}:slide:${Number.isFinite(index) ? index : 0}`,
            index: Number.isFinite(index) ? index : 0,
            title: safeSummaryText(slideData.title, `第 ${Number.isFinite(index) ? index : 0} 页`),
            status: "generating",
            elements: [],
            userModifiedFields: [],
            revision: Number.isInteger(slideData.revision) ? Number(slideData.revision) : 1,
            ...(typeof slideData.notes === "string" && slideData.notes.trim() ? { speakerNotes: slideData.notes.trim() } : {}),
          };
          const total = Math.max(pageCount, 1);
          const ratio = Number.isFinite(index) && index > 0 ? Math.max(0, Math.min(1, (index - 1) / total)) : 0;
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "assistant.text.delta", stageCardPayload(
            "slides",
            `正在生成第 ${slide.index} / ${total} 页`,
            35 + Math.round(ratio * 40),
          ));
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "slide.started", { slide }, 1);
          continue;
        }

        if (envelope.event_type === "slide.completed") {
          const slideData = envelope.data as IncrementalSlideData;
          const previewUrl = typeof slideData.preview_url === "string"
            ? await this.loadPreviewUrl(slideData.preview_url, token)
            : undefined;
          const thumbnailUrl = typeof slideData.thumbnail_url === "string"
            ? (slideData.thumbnail_url === slideData.preview_url
              ? previewUrl
              : await this.loadPreviewUrl(slideData.thumbnail_url, token))
            : previewUrl;
          const index = Number(slideData.index);
          const slide: Slide = {
            id: typeof slideData.slide_id === "string" ? slideData.slide_id : `${envelope.task_id}:slide:${Number.isFinite(index) ? index : 0}`,
            index: Number.isFinite(index) ? index : 0,
            title: safeSummaryText(slideData.title, `第 ${Number.isFinite(index) ? index : 0} 页`),
            status: "ready",
            elements: [],
            userModifiedFields: [],
            revision: Number.isInteger(slideData.revision) ? Number(slideData.revision) : 1,
            ...(typeof slideData.notes === "string" && slideData.notes.trim() ? { speakerNotes: slideData.notes.trim() } : {}),
            ...(previewUrl ? { previewUrl } : {}),
            ...(thumbnailUrl ? { thumbnailUrl } : {}),
            ...(Number.isInteger(slideData.preview_file_id) ? { previewArtifactId: Number(slideData.preview_file_id) } : {}),
            ...(Number.isInteger(slideData.thumbnail_file_id) ? { thumbnailArtifactId: Number(slideData.thumbnail_file_id) } : {}),
          };
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "slide.completed", { slide });
          continue;
        }

        if (envelope.event_type === "slide.failed") {
          const slideData = envelope.data as IncrementalSlideData;
          const index = Number(slideData.index);
          const slide: Slide = {
            id: typeof slideData.slide_id === "string" ? slideData.slide_id : `${envelope.task_id}:slide:${Number.isFinite(index) ? index : 0}`,
            index: Number.isFinite(index) ? index : 0,
            title: safeSummaryText(slideData.title, `第 ${Number.isFinite(index) ? index : 0} 页`),
            status: "error",
            elements: [],
            userModifiedFields: [],
            revision: Number.isInteger(slideData.revision) ? Number(slideData.revision) : 1,
            ...(typeof slideData.notes === "string" && slideData.notes.trim() ? { speakerNotes: slideData.notes.trim() } : {}),
          };
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "slide.failed", {
            slide,
            errors: asStringList(slideData.errors),
          });
          continue;
        }

        if (envelope.event_type === "validation.completed") {
          finalValidation = toValidationResult(envelope.data as IncrementalValidationResult);
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "assistant.text.delta", stageCardPayload("validation", "正在执行质量检查", 88));
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "validation.completed", {
            validation: finalValidation,
          }, 1);
          continue;
        }

        if (envelope.event_type === "export.ready") {
          const finalFile = isRecord(envelope.data.final_file) ? envelope.data.final_file as IncrementalFinalFile : null;
          if (!finalFile) continue;
          const artifact = this.toExportArtifact(finalFile);
          if (!artifact) continue;
          const validation = finalValidation ?? toValidationResult(finalFile.validation_result ?? {});
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "assistant.text.delta", stageCardPayload("export", "正在导出 PPTX", 96));
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "export.ready", {
            artifact,
            validation,
          }, 1);
          continue;
        }

        if (envelope.event_type === "task.completed") {
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "task.completed", {
            finishedAt: envelope.timestamp,
          });
          return;
        }

        if (envelope.event_type === "task.failed") {
          const failed = envelope.data as IncrementalTaskFailedData;
          yield makeMappedEvent(envelope, input.projectId, input.chatId, "task.failed", {
            error: {
              code: typeof failed.code === "string" ? failed.code : "workflow_failed",
              message: failedTaskMessage(
                typeof failed.code === "string" ? failed.code : "workflow_failed",
                finalValidation ?? undefined,
                Array.isArray(failed.failed_indices)
                  ? failed.failed_indices.map((value) => Number(value)).filter((value) => Number.isFinite(value))
                  : undefined,
              ),
              retryable: false,
              details: failed,
            },
          });
          return;
        }
      }

      yield makeSyntheticEvent(started ? liveTaskId : provisionalTaskId, input.projectId, input.chatId, 1, "task.failed", {
        terminalStatus: "interrupted",
        error: { code: "INCREMENTAL_STREAM_INTERRUPTED", message: "增量 PPT 事件流未正常结束", retryable: true },
      });
    } finally {
      this.activeConnections.delete(provisionalTaskId);
      this.activeConnections.delete(liveTaskId);
    }
  }

  async loadHistoryProject(projectId: string): Promise<{ project: PresentationProject } | null> {
    const token = await this.options.getAccessToken();
    if (!token) {
      await this.options.onUnauthorized?.();
      return null;
    }
    const endpoint = absoluteUrl(this.options.baseUrl, `/api/v1/ppt-master/projects/${encodeURIComponent(projectId)}/history`);
    if (!endpoint) return null;
    const response = await this.options.fetchImpl(endpoint, { method: "GET", headers: { Authorization: `Bearer ${token}` } });
    if (response.status === 401) {
      await this.options.onUnauthorized?.();
      return null;
    }
    if (!response.ok) return null;
    const payload = await response.json() as { data?: { project?: PresentationProject } };
    const project = payload.data?.project;
    return project?.id === projectId ? { project } : null;
  }

  async restoreSlideAssets(slides: Slide[]): Promise<Slide[]> {
    const token = await this.options.getAccessToken();
    if (!token) {
      await this.options.onUnauthorized?.();
      return slides;
    }
    const restored: Slide[] = [];
    for (const slide of slides) {
      const next: Slide = { ...slide };
      const previewId = Number(slide.previewArtifactId);
      const thumbnailId = Number(slide.thumbnailArtifactId);
      if (!next.previewUrl && Number.isInteger(previewId) && previewId > 0) {
        next.previewUrl = await this.loadPreviewUrl(`/api/v1/files/${previewId}/download`, token);
      }
      if (!next.thumbnailUrl && Number.isInteger(thumbnailId) && thumbnailId > 0) {
        next.thumbnailUrl = thumbnailId === previewId && next.previewUrl
          ? next.previewUrl
          : await this.loadPreviewUrl(`/api/v1/files/${thumbnailId}/download`, token);
      }
      restored.push(next);
    }
    return restored;
  }

  disconnect(taskId: string): void {
    this.activeConnections.get(taskId)?.abort();
  }

  dispose(): void {
    this.activeConnections.forEach((controller) => controller.abort());
    this.activeConnections.clear();
    this.previewObjectUrls.forEach((url) => URL.revokeObjectURL(url));
    this.previewObjectUrls.clear();
  }

  async download(artifact: PptExportArtifact, fallbackTitle: string): Promise<DownloadedPptFile> {
    const token = await this.options.getAccessToken();
    if (!token) {
      await this.options.onUnauthorized?.();
      throw new Error("登录状态已失效，请重新登录");
    }
    const downloadUrl = absoluteUrl(this.options.baseUrl, artifact.downloadUrl);
    if (!downloadUrl) {
      throw new Error("PPT 下载地址未通过安全校验");
    }
    return downloadLegacyArtifact({
      artifact: { ...artifact, downloadUrl },
      fallbackTitle,
      token,
      fetchImpl: this.options.fetchImpl,
      saveBlob: this.options.saveBlob,
      digestSha256: this.options.digestSha256,
      verifySha256: this.options.verifyDownloadSha256,
      onUnauthorized: this.options.onUnauthorized,
    });
  }

  private async loadPreviewUrl(relativeUrl: string, token: string): Promise<string | undefined> {
    const target = absoluteUrl(this.options.baseUrl, relativeUrl);
    if (!target) return undefined;
    const response = await this.options.fetchImpl(target, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (response.status === 401) {
      await this.options.onUnauthorized?.();
      return undefined;
    }
    if (!response.ok) return undefined;

    const contentType = response.headers.get("Content-Type")?.split(";", 1)[0].trim().toLowerCase() ?? "";
    const contentLength = Number(response.headers.get("Content-Length"));
    if (contentType !== "image/svg+xml"
      || (Number.isFinite(contentLength) && contentLength > this.options.maxPreviewBytes)) return undefined;
    const blob = await response.blob();
    if (blob.size > this.options.maxPreviewBytes) return undefined;
    const text = await blob.text();
    if (!isSafeSvg(text)) return undefined;
    const objectUrl = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
    this.previewObjectUrls.add(objectUrl);
    return objectUrl;
  }

  private toExportArtifact(finalFile: IncrementalFinalFile): PptExportArtifact | null {
    const validation = finalFile.validation_result ?? {};
    const warnings = asStringList(validation.warnings);
    const errors = asStringList(validation.errors);
    const blocking = asStringList(validation.blocking_errors);
    const valid = finalFile.valid === true && validation.passed === true && errors.length === 0 && blocking.length === 0;
    if (!valid) return null;
    if (!Number.isInteger(finalFile.file_id) || typeof finalFile.download_url !== "string"
      || !Number.isFinite(finalFile.size) || typeof finalFile.sha256 !== "string") {
      return null;
    }
    const downloadUrl = absoluteUrl(this.options.baseUrl, finalFile.download_url);
    if (!downloadUrl) return null;
    return {
      fileId: Number(finalFile.file_id),
      downloadUrl,
      size: Number(finalFile.size),
      sha256: finalFile.sha256.toLowerCase(),
      valid: true,
      warnings,
      ...(Number.isInteger(finalFile.slide_count) ? { slideCount: Number(finalFile.slide_count) } : {}),
    };
  }
}
