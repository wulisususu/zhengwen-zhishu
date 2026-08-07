import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

const SESSION_KEY = 'mqw-session'

export function readSession() {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY) || '{}')
  } catch {
    return {}
  }
}

export function syncAuthCookie(token) {
  if (typeof document === 'undefined') return
  const secure = window.location.protocol === 'https:' ? '; Secure' : ''
  if (token) {
    document.cookie = 'mqw_token=' + encodeURIComponent(token) + '; Path=/; SameSite=Lax; Max-Age=604800' + secure
  } else {
    document.cookie = 'mqw_token=; Path=/; SameSite=Lax; Max-Age=0' + secure
  }
}

export function getSessionToken() {
  return readSession().token || ''
}

export function hasSessionToken() {
  return !!getSessionToken()
}

export function writeStoredSession(payload) {
  const token = payload?.token || payload?.access_token || ''
  const session = token ? { ...payload, token } : {}
  if (token) localStorage.setItem(SESSION_KEY, JSON.stringify(session))
  else localStorage.removeItem(SESSION_KEY)
  syncAuthCookie(token)
  return session
}

export function clearStoredSession() {
  localStorage.removeItem(SESSION_KEY)
  syncAuthCookie('')
}

export const useAuthStore = defineStore('auth', () => {
  const session = ref(readSession())
  const isAuthenticated = computed(() => !!session.value?.token)

  function refreshSession() {
    session.value = readSession()
  }

  function loadSession() {
    refreshSession()
  }

  function setSession(payload) {
    session.value = writeStoredSession(payload)
    window.dispatchEvent(new CustomEvent('mqw-auth-changed'))
  }

  function clearSession() {
    clearStoredSession()
    session.value = {}
    window.dispatchEvent(new CustomEvent('mqw-auth-changed'))
  }

  return { session, isAuthenticated, refreshSession, loadSession, setSession, clearSession }
})
