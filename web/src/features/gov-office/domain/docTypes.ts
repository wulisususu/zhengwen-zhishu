// Document types and their letterhead layouts.
//
// Only types with a real template are `supported`. The others are listed so
// the picker can show them as "待支持" instead of pretending they work; flip
// `supported` only when the backend ships the matching template.
//
// Letterheads use a generic, configurable sample organization. Never put a
// real agency name, emblem or seal here.

import type { DocTypeId } from "../types";

export type LetterheadKind = "file_red" | "letter" | "minutes" | "plain";

export interface LetterheadConfig {
  kind: LetterheadKind;
  /** Text shown in the letterhead, e.g. "示例单位文件". */
  orgText: string;
  showDocNumber: boolean;
}

export interface DocTypeConfig {
  id: DocTypeId;
  label: string;
  supported: boolean;
  template: string;
  letterhead: LetterheadConfig;
}

/** Sample organization used for letterheads until a deployment configures its own. */
export const SAMPLE_ORG_NAME = "示例单位";

export const DOC_TYPES: DocTypeConfig[] = [
  {
    id: "notice",
    label: "通知",
    supported: true,
    template: "通知 · 标准版",
    letterhead: { kind: "file_red", orgText: `${SAMPLE_ORG_NAME}文件`, showDocNumber: true },
  },
  {
    id: "request",
    label: "请示",
    supported: false,
    template: "请示（待支持）",
    letterhead: { kind: "file_red", orgText: `${SAMPLE_ORG_NAME}文件`, showDocNumber: true },
  },
  {
    id: "report",
    label: "报告",
    supported: false,
    template: "报告（待支持）",
    letterhead: { kind: "file_red", orgText: `${SAMPLE_ORG_NAME}文件`, showDocNumber: true },
  },
  {
    id: "letter",
    label: "函",
    supported: false,
    template: "函 · 信函格式（待支持）",
    letterhead: { kind: "letter", orgText: SAMPLE_ORG_NAME, showDocNumber: true },
  },
  {
    id: "minutes",
    label: "会议纪要",
    supported: false,
    template: "纪要（待支持）",
    letterhead: { kind: "minutes", orgText: `${SAMPLE_ORG_NAME}会议纪要`, showDocNumber: false },
  },
  {
    id: "interpretation",
    label: "政策解读稿",
    supported: false,
    template: "解读稿（待支持）",
    letterhead: { kind: "plain", orgText: "", showDocNumber: false },
  },
];

export function docTypeConfig(id: DocTypeId): DocTypeConfig {
  return DOC_TYPES.find((t) => t.id === id) ?? DOC_TYPES[DOC_TYPES.length - 1];
}

/** Unsupported types are previewed with a plain layout, never with a fake template. */
export function previewLetterhead(id: DocTypeId): LetterheadConfig {
  const config = docTypeConfig(id);
  return config.supported ? config.letterhead : { kind: "plain", orgText: "", showDocNumber: false };
}

export const FIELD_LABELS = {
  recipient: "主送机关",
  issuer: "发文机关",
  undertaker: "承办部门",
} as const;

export const STATUS_LABELS = {
  draft: "草稿",
  pending: "待审核",
  returned: "退回修改",
  approved: "审核通过",
} as const;

export const STATUS_TONES = {
  draft: "neutral",
  pending: "info",
  returned: "danger",
  approved: "success",
} as const;

export const POLICY_STATUS_LABELS = {
  current: "现行有效",
  abolished: "已废止",
  unverified: "状态待核实",
} as const;

export const POLICY_STATUS_TONES = {
  current: "success",
  abolished: "danger",
  unverified: "warning",
} as const;

export const SEVERITY_LABELS = { critical: "严重", warning: "警告", hint: "提示" } as const;
export const SEVERITY_TONES = { critical: "danger", warning: "warning", hint: "info" } as const;
export const SOURCE_LABELS = { rule: "规则检查", ai: "AI 语义审查" } as const;
