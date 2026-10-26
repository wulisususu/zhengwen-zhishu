import type { WorkflowCapabilities } from "../protocol/capabilities";
import type { PptWorkflowEvent, PptWorkflowEventType } from "../protocol/events";
import type { PptExportArtifact } from "../types/project";
import type { PresentationTheme, ValidationIssue, ValidationResult } from "../types/presentation";
import type { WorkflowError, WorkflowStage } from "../types/task";
import type {
  DownloadedPptFile,
  PptWorkflowAdapter,
  StartPptWorkflowInput,
} from "./PptWorkflowAdapter";
import { parseSseStream } from "./legacySseParser";
import {
  digestBlobSha256,
  downloadLegacyArtifact,
  LegacyDownloadError,
  saveBlobWithObjectUrl,
} from "./legacyDownload";
import { createClientUuid } from "../utils/uuid";

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type PageFormat = "ppt169" | "ppt43";

interface LegacyValidationResult {
  passed?: boolean;
  warnings?: unknown[];
  errors?: unknown[];
  blocking_errors?: unknown[];
}

interface LegacyDoneData {
  file_id?: number;
  download_url?: string;
  size?: number;
  sha256?: string;
  valid?: boolean;
  validation_result?: LegacyValidationResult;
}

interface LegacyProgressData {
  message?: string;
  progress?: number;
  stage?: string;
  step?: string;
  current?: number;
  total?: number;
}

export type LegacyPptMasterRawEvent =
  | { type: "progress"; data: LegacyProgressData }
  | { type: "spec"; data: Record<string, unknown> }
  | { type: "validate"; data: LegacyValidationResult }
  | { type: "done"; data: LegacyDoneData }
  | { type: "fallback"; data: { message?: string; code?: string } };

export interface LegacyEventContext {
  taskId: string;
  projectId: string;
  chatId: string;
  sequence: number;
  baseUrl?: string;
}

export interface LegacyPptMasterAdapterOptions {
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
  saveBlob?: (blob: Blob, filename: string) => void | Promise<void>;
  digestSha256?: (blob: Blob) => Promise<string>;
  verifyDownloadSha256?: boolean;
}

const capabilities: WorkflowCapabilities = {
  incrementalOutline: false,
  incrementalSlides: false,
  taskCancellation: false,
  taskResume: false,
  slideRegeneration: false,
  proposalApply: false,
  fileDownload: true,
};

const stageAliases: Record<string, WorkflowStage> = {
  parse: "understanding",
  waiting: "understanding",
  analysis: "understanding",
  brief: "understanding",
  requirements: "understanding",
  understanding: "understanding",
  outline: "outline",
  spec: "design",
  design: "design",
  slides: "slides",
  svg: "slides",
  svg_done: "validation",
  generate: "slides",
  generating: "slides",
  render: "slides",
  validate: "validation",
  validation: "validation",
  export: "export",
  done: "export",
};

const legacyStageLabels: Record<string, string> = {
  parse: "正在分析需求",
  spec: "正在规划设计方案",
  svg: "正在生成幻灯片",
  svg_done: "正在执行质量检查",
  validate: "正在执行质量检查",
  export: "正在导出 PPTX",
};

const stepProgress: Record<string, number> = {
  parse: 5,
  spec: 15,
  svg: 35,
  svg_done: 70,
  validate: 80,
  export: 90,
};

function asText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value instanceof Error) return value.message;
  if (value && typeof value === "object" && "message" in value && typeof value.message === "string") return value.message;
  return String(value ?? "");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function safeDisplayMessage(value: unknown, fallback: string): string {
  if (typeof value !== "string") return fallback;
  const trimmed = value.trim().slice(0, 300);
  if (!trimmed || /traceback|[A-Za-z]:[\\/]|\/(?:home|app|tmp|var|opt|srv|root)(?:[\/\s]|$)/i.test(trimmed)) return fallback;
  return trimmed.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "");
}

function list(value: unknown): string[] {
  return Array.isArray(value) ? value.map(asText).filter(Boolean) : [];
}

function toValidationResult(raw: LegacyValidationResult): ValidationResult {
  const warnings = list(raw.warnings);
  const errors = list(raw.errors);
  const blocking = list(raw.blocking_errors);
  const issues: ValidationIssue[] = [
    ...warnings.map((message, index) => ({ id: `legacy-warning-${index + 1}`, severity: "warning" as const, message })),
    ...errors.map((message, index) => ({ id: `legacy-error-${index + 1}`, severity: "error" as const, message })),
    ...blocking.map((message, index) => ({ id: `legacy-blocking-${index + 1}`, severity: "error" as const, message, blocking: true })),
  ];

  return {
    score: raw.passed === true && errors.length === 0 && blocking.length === 0
      ? (warnings.length > 0 ? 85 : 100)
      : 0,
    issues,
    checkedAt: new Date().toISOString(),
  };
}

function absoluteDownloadUrl(baseUrl: string, downloadUrl: string): string | null {
  try {
    const base = new URL(`${baseUrl.replace(/\/+$/, "")}/`);
    const resolved = new URL(downloadUrl, base);
    return resolved.origin === base.origin ? resolved.toString() : null;
  } catch {
    return null;
  }
}

function normalizedProgress(data: LegacyProgressData) {
  const rawStage = (data.stage ?? data.step)?.trim().toLowerCase() ?? "";
  const current = Number(data.current);
  const total = Number(data.total);
  const stepRatio = rawStage === "svg" && Number.isFinite(current) && Number.isFinite(total) && total > 0
    ? Math.max(0, Math.min(1, current / total))
    : null;
  const inferredProgress = stepRatio === null
    ? (stepProgress[rawStage] ?? 0)
    : 35 + Math.round(stepRatio * 35);
  return {
    text: legacyStageLabels[rawStage] ?? "正在生成演示文稿",
    progress: Math.max(0, Math.min(100, Number.isFinite(data.progress) ? Number(data.progress) : inferredProgress)),
    stage: stageAliases[rawStage] ?? "understanding",
    presentation: "stage-card" as const,
  };
}

function normalizedTheme(value: unknown): PresentationTheme | undefined {
  if (!value || typeof value !== "object") return undefined;
  const candidate = value as Record<string, unknown>;
  if (!["id", "name", "primaryColor", "backgroundColor", "fontFamily"]
    .every((key) => typeof candidate[key] === "string")) return undefined;
  return candidate as unknown as PresentationTheme;
}

function normalizedDone(data: LegacyDoneData, baseUrl: string):
  | { artifact: PptExportArtifact; validation: ValidationResult }
  | { error: WorkflowError; validation: ValidationResult } {
  const rawValidation = data.validation_result ?? {};
  const validation = toValidationResult(rawValidation);
  const blocking = list(rawValidation.blocking_errors);
  const errors = list(rawValidation.errors);
  const consistent = data.valid === true && rawValidation.passed === true && blocking.length === 0 && errors.length === 0;
  const hasArtifact = Number.isInteger(data.file_id)
    && typeof data.download_url === "string"
    && data.download_url.length > 0
    && Number.isFinite(data.size)
    && Number(data.size) >= 0
    && typeof data.sha256 === "string"
    && data.sha256.length > 0;

  if (!consistent || !hasArtifact) {
    return {
      validation,
      error: {
        code: consistent ? "LEGACY_EXPORT_INVALID" : "LEGACY_VALIDATION_FAILED",
        message: blocking[0] ?? errors[0] ?? "PPT 质检未通过，暂不可下载",
        retryable: false,
      },
    };
  }

  const downloadUrl = absoluteDownloadUrl(baseUrl, String(data.download_url));
  if (!downloadUrl) {
    return {
      validation,
      error: {
        code: "LEGACY_DOWNLOAD_ORIGIN_FORBIDDEN",
        message: "PPT 下载地址未通过安全校验",
        retryable: false,
      },
    };
  }

  return {
    validation,
    artifact: {
      fileId: Number(data.file_id),
      downloadUrl,
      size: Number(data.size),
      sha256: String(data.sha256).toLowerCase(),
      valid: true,
      warnings: list(rawValidation.warnings),
    },
  };
}

/** Keeps temporary PPT-master vocabulary at the system boundary. */
export function mapLegacyPptMasterEvent(
  raw: LegacyPptMasterRawEvent,
  context: LegacyEventContext,
): PptWorkflowEvent[] {
  const baseUrl = context.baseUrl ?? "http://localhost";
  const event = <T>(type: PptWorkflowEventType, payload: T, offset = 0): PptWorkflowEvent<T> => ({
    eventId: `legacy-${context.taskId}-${context.sequence + offset}-${type}`,
    taskId: context.taskId,
    projectId: context.projectId,
    chatId: context.chatId,
    sequence: context.sequence + offset,
    timestamp: new Date().toISOString(),
    type,
    payload,
  });

  switch (raw.type) {
    case "progress":
      return [event("assistant.text.delta", normalizedProgress(raw.data))];
    case "spec":
      return [event("design.ready", {
        specification: raw.data,
        ...(normalizedTheme(raw.data.theme) ? { theme: normalizedTheme(raw.data.theme) } : {}),
      })];
    case "validate":
      return [event("validation.completed", { validation: toValidationResult(raw.data) })];
    case "done": {
      const result = normalizedDone(raw.data, baseUrl);
      if ("error" in result) {
        return [
          event("validation.completed", { validation: result.validation }),
          event("task.failed", { error: result.error }, 1),
        ];
      }
      return [
        event("export.ready", { artifact: result.artifact, validation: result.validation }),
        event("task.completed", { finishedAt: new Date().toISOString() }, 1),
      ];
    }
    case "fallback":
      return [event("task.failed", {
        error: {
          code: typeof raw.data.code === "string" && /^[A-Za-z0-9_.:-]{1,64}$/.test(raw.data.code)
            ? raw.data.code
            : "LEGACY_FALLBACK",
          message: safeDisplayMessage(raw.data.message, "PPT 生成失败"),
          retryable: false,
        },
      })];
  }
}

function parseRetryAfter(value: string | null): number | undefined {
  if (!value) return undefined;
  if (/^\d+$/.test(value.trim())) return Number.parseInt(value, 10);
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return undefined;
  return Math.max(0, Math.ceil((timestamp - Date.now()) / 1000));
}

function httpFailure(status: number, retryAfter: string | null): { error: WorkflowError; terminalStatus?: "interrupted" } {
  const retrySeconds = parseRetryAfter(retryAfter);
  const table: Record<number, WorkflowError> = {
    401: { code: "AUTHENTICATION_REQUIRED", message: "会话已失效，请重新选择角色", retryable: false, httpStatus: 401 },
    409: { code: "IDEMPOTENT_TASK_RUNNING", message: "任务仍在生成", retryable: true, httpStatus: 409 },
    429: { code: "RATE_LIMITED", message: "服务繁忙，请稍后重试", retryable: true, httpStatus: 429, retryAfterSeconds: retrySeconds },
    413: { code: "REQUEST_TOO_LARGE", message: "请求内容过大", retryable: false, httpStatus: 413 },
    422: { code: "INVALID_REQUEST", message: "生成参数不合法", retryable: false, httpStatus: 422 },
    507: { code: "PROJECT_QUOTA_EXCEEDED", message: "服务器项目配额不足", retryable: false, httpStatus: 507 },
  };
  const error = table[status] ?? {
    code: "LEGACY_HTTP_ERROR",
    message: "PPT 服务请求失败",
    retryable: status >= 500,
    httpStatus: status,
  };
  return status === 409 ? { error, terminalStatus: "interrupted" } : { error };
}

function parseRawEvent(type: string, data: unknown): LegacyPptMasterRawEvent | null {
  if (!isRecord(data)) return null;
  switch (type) {
    case "progress": return { type, data: data as LegacyProgressData };
    case "spec": return { type, data };
    case "validate": return { type, data: data as LegacyValidationResult };
    case "done": return { type, data: data as LegacyDoneData };
    case "fallback": return { type, data: data as { message?: string; code?: string } };
    default: return null;
  }
}

function wait(milliseconds: number): Promise<void> {
  if (milliseconds <= 0) return Promise.resolve();
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export class LegacyPptMasterAdapter implements PptWorkflowAdapter {
  readonly capabilities = capabilities;
  private readonly activeConnections = new Map<string, AbortController>();
  private readonly options: Required<Pick<LegacyPptMasterAdapterOptions,
    "baseUrl" | "endpointPath" | "getAccessToken" | "pageCount" | "pageFormat" |
    "requestIdFactory" | "fetchImpl" | "maxNetworkRetries" | "retryDelayMs" |
    "saveBlob" | "digestSha256" | "verifyDownloadSha256">>
    & Pick<LegacyPptMasterAdapterOptions, "onUnauthorized">;

  constructor(options: LegacyPptMasterAdapterOptions = {}) {
    this.options = {
      baseUrl: options.baseUrl ?? "http://192.168.0.11:8000",
      endpointPath: options.endpointPath ?? "/api/v1/ppt-master/generate",
      getAccessToken: options.getAccessToken ?? (() => ""),
      onUnauthorized: options.onUnauthorized,
      pageCount: options.pageCount ?? 8,
      pageFormat: options.pageFormat ?? "ppt169",
      requestIdFactory: options.requestIdFactory ?? createClientUuid,
      fetchImpl: options.fetchImpl ?? fetch.bind(globalThis),
      maxNetworkRetries: Math.max(0, options.maxNetworkRetries ?? 0),
      retryDelayMs: Math.max(0, options.retryDelayMs ?? 500),
      saveBlob: options.saveBlob ?? saveBlobWithObjectUrl,
      digestSha256: options.digestSha256 ?? digestBlobSha256,
      verifyDownloadSha256: options.verifyDownloadSha256 ?? true,
    };
  }

  async *start(input: StartPptWorkflowInput): AsyncGenerator<PptWorkflowEvent> {
    const requestId = this.options.requestIdFactory();
    const pageCount = input.pageCount ?? this.options.pageCount;
    const taskId = `legacy-${requestId}`;
    let sequence = 1;
    const makeEvent = <T>(type: PptWorkflowEventType, payload: T): PptWorkflowEvent<T> => ({
      eventId: `legacy-${taskId}-${sequence}-${type}`,
      taskId,
      projectId: input.projectId,
      chatId: input.chatId,
      sequence: sequence++,
      timestamp: new Date().toISOString(),
      type,
      payload,
    });

    yield makeEvent("task.started", { requestId, pageCount });

    if (!input.prompt.trim() || pageCount < 1 || pageCount > 12
      || !Number.isInteger(pageCount)
      || !(["ppt169", "ppt43"] as const).includes(this.options.pageFormat)) {
      yield makeEvent("task.failed", {
        error: { code: "INVALID_REQUEST", message: "PPT 生成参数不合法", retryable: false },
      });
      return;
    }

    const token = await this.options.getAccessToken();
    if (!token) {
      await this.options.onUnauthorized?.();
      yield makeEvent("task.failed", {
        error: { code: "AUTHENTICATION_REQUIRED", message: "会话已失效，请重新选择角色", retryable: false, httpStatus: 401 },
      });
      return;
    }

    const body = JSON.stringify({
      user_input: input.prompt,
      page_count: pageCount,
      page_format: this.options.pageFormat,
      sources: [],
      request_id: requestId,
    });
    const init: RequestInit = {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": requestId,
      },
      body,
    };
    const endpoint = absoluteDownloadUrl(this.options.baseUrl, this.options.endpointPath);
    if (!endpoint) {
      yield makeEvent("task.failed", {
        error: { code: "INVALID_REQUEST", message: "PPT 服务地址未通过安全校验", retryable: false },
      });
      return;
    }
    const controller = new AbortController();
    this.activeConnections.set(taskId, controller);
    init.signal = controller.signal;

    try {
      let response: Response | null = null;
      for (let attempt = 0; attempt <= this.options.maxNetworkRetries; attempt += 1) {
        try {
          response = await this.options.fetchImpl(endpoint, init);
          break;
        } catch (cause) {
          if (!controller.signal.aborted && attempt < this.options.maxNetworkRetries) {
            await wait(this.options.retryDelayMs);
            continue;
          }
          yield makeEvent("task.failed", {
            terminalStatus: "interrupted",
            error: {
              code: "LEGACY_NETWORK_INTERRUPTED",
              message: cause instanceof DOMException && cause.name === "AbortError"
                ? "与 PPT 服务的连接已断开"
                : "PPT 生成连接中断",
              retryable: true,
            },
          });
          return;
        }
      }

      if (!response) return;
      if (!response.ok) {
        if (response.status === 401) await this.options.onUnauthorized?.();
        yield makeEvent("task.failed", httpFailure(response.status, response.headers.get("Retry-After")));
        return;
      }
      if (!response.body) {
        yield makeEvent("task.failed", {
          terminalStatus: "interrupted",
          error: { code: "LEGACY_STREAM_INTERRUPTED", message: "PPT 服务未返回事件流", retryable: true },
        });
        return;
      }

      let terminal = false;
      try {
        for await (const message of parseSseStream(response.body)) {
          let data: unknown;
          try {
            data = JSON.parse(message.data);
          } catch {
            yield makeEvent("task.failed", {
              error: { code: "LEGACY_EVENT_INVALID", message: "PPT 服务返回了无法解析的事件", retryable: false },
            });
            return;
          }

          if (!(message.event === "progress" || message.event === "spec" || message.event === "validate"
            || message.event === "done" || message.event === "fallback")) {
            yield makeEvent("task.failed", {
              error: { code: "LEGACY_EVENT_UNSUPPORTED", message: "PPT 服务返回了不支持的事件", retryable: false },
            });
            return;
          }

          const raw = parseRawEvent(message.event, data);
          if (!raw) {
            yield makeEvent("task.failed", {
              error: { code: "LEGACY_EVENT_INVALID", message: "PPT 服务返回了不符合契约的事件", retryable: false },
            });
            return;
          }

          const mapped = mapLegacyPptMasterEvent(
            raw,
            {
              taskId,
              projectId: input.projectId,
              chatId: input.chatId,
              sequence,
              baseUrl: this.options.baseUrl,
            },
          );
          for (const event of mapped) {
            sequence = event.sequence + 1;
            yield event;
            terminal ||= event.type === "task.completed" || event.type === "task.failed";
          }
          if (terminal) return;
        }
      } catch {
        yield makeEvent("task.failed", {
          terminalStatus: "interrupted",
          error: { code: "LEGACY_STREAM_INTERRUPTED", message: "PPT 事件流意外中断", retryable: true },
        });
        return;
      }

      yield makeEvent("task.failed", {
        terminalStatus: "interrupted",
        error: { code: "LEGACY_STREAM_INTERRUPTED", message: "PPT 事件流未正常结束", retryable: true },
      });
    } finally {
      this.activeConnections.delete(taskId);
    }
  }

  disconnect(taskId: string): void {
    this.activeConnections.get(taskId)?.abort();
  }

  async download(artifact: PptExportArtifact, fallbackTitle: string): Promise<DownloadedPptFile> {
    const token = await this.options.getAccessToken();
    if (!token) {
      await this.options.onUnauthorized?.();
      const error = new Error("会话已失效，请重新选择角色") as Error & { code: string };
      error.code = "AUTHENTICATION_REQUIRED";
      throw error;
    }

    const downloadUrl = absoluteDownloadUrl(this.options.baseUrl, artifact.downloadUrl);
    if (!downloadUrl) {
      throw new LegacyDownloadError("LEGACY_DOWNLOAD_ORIGIN_FORBIDDEN", "PPT 下载地址未通过安全校验");
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
}
