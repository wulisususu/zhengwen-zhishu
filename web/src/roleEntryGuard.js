// No login page: without a role session every page leads to the role entry,
// where the visitor picks 起草人 or 审核人 (role selection, not authentication).
export const ENTRY_PATH = '/entry'
export const PUBLIC_PATHS = new Set(['/welcome', ENTRY_PATH])

export function entryGuard(to, hasSession) {
  if (PUBLIC_PATHS.has(to.path) || hasSession) return true
  return { path: ENTRY_PATH }
}
