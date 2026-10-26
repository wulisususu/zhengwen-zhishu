// Role entry: the visitor picks 起草人 or 审核人 instead of logging in.
// The backend (POST /api/v1/gov/entry) issues a session for a dedicated role
// account that has gov workflow rights only (never admin). This is role
// selection, not authentication, and the UI must say so.
import { readSession } from "../../stores/auth.js";

export type EntryRole = "drafter" | "reviewer";

export interface EntryRoleOption {
  role: EntryRole;
  label: string;
  description: string;
}

export interface EntryOptions {
  enabled: boolean;
  roles: EntryRoleOption[];
}

/** Where each role's workflow starts. */
export const ROLE_HOME: Record<EntryRole, string> = {
  drafter: "/gov/draft",
  reviewer: "/gov/review-center",
};

export const ROLE_LABEL: Record<EntryRole, string> = { drafter: "起草人", reviewer: "审核人" };

const DEMO = import.meta.env.VITE_GOV_OFFICE_MODE === "demo";
const DEMO_OPTIONS: EntryOptions = {
  enabled: true,
  roles: [
    { role: "drafter", label: "起草人", description: "起草通知、保存草稿、提交审核、查看审核结果" },
    { role: "reviewer", label: "审核人", description: "审核他人送审的文稿、批准或退回、维护政策库" },
  ],
};

async function call<T>(method: "GET" | "POST", body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch("/api/v1/gov/entry", {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error("连接后端失败，请稍后重试");
  }
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(payload.detail || payload.message || `进入失败（${res.status}）`);
  if (payload.code !== 0) throw new Error(payload.message || "进入失败");
  return payload.data as T;
}

export function fetchEntryOptions(): Promise<EntryOptions> {
  return DEMO ? Promise.resolve(DEMO_OPTIONS) : call<EntryOptions>("GET");
}

/** Session payload for useAuthStore().setSession: {access_token|token, role, ...}. */
export async function enterRole(role: EntryRole): Promise<Record<string, unknown>> {
  if (DEMO) return { token: `demo-${role}`, role };
  const data = await call<Record<string, unknown>>("POST", { role });
  if (!data.access_token) throw new Error("后端没有返回会话");
  return data;
}

/** Role chosen at the entry for the current session, if any. */
export function currentEntryRole(): EntryRole | null {
  const role = readSession().role;
  return role === "drafter" || role === "reviewer" ? role : null;
}
