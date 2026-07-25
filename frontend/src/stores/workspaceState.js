import { useChatStore } from './chat.js'

export function resetWorkspaceState() {
  try {
    useChatStore().reset()
  } catch {}

  try {
    sessionStorage.removeItem('mqw-pending-request')
  } catch {}

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('mqw-workspace-reset'))
  }
}
