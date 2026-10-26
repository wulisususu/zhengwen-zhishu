import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import WelcomePage from './views/WelcomePage.vue'
import WorkspacePage from './views/WorkspacePage.vue'
import ChatPage from './views/ChatPage.vue'
import DocumentPage from './views/DocumentPage.vue'
import GongwenPage from './views/GongwenPage.vue'
import PolicyPage from './views/PolicyPage.vue'
import PptHostPage from './views/PptHostPage.vue'
import LoginPage from './views/LoginPage.vue'
import AgentDirectoryPage from './views/AgentDirectoryPage.vue'
import SettingsPage from './views/SettingsPage.vue'
import { hasSessionToken } from './stores/auth.js'
// 说明：gov-office 那套页面（/gov/*）的入口本次不并入，文件保留在 features/gov-office 下，
// 需要启用时把下一行 import 与 routes 里的 ...govOfficeRoutes 一起放开即可。
// import { govOfficeRoutes } from './features/gov-office/routes'
import './style.css'
import { setGovOfficeAdapter } from './features/gov-office/adapters'
import { useGovDocumentsStore } from './features/gov-office/stores/govDocuments'
import { useGovSessionStore, resetGovSessionLoading } from './features/gov-office/stores/govSession'
import { usePolicyQaStore } from './features/gov-office/stores/policyQa'

function createPptProjectId() {
  return globalThis.crypto?.randomUUID?.()
    || `ppt-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

const routes = [
  { path: '/', component: WelcomePage },
  { path: '/welcome', component: WelcomePage },
  { path: '/workspace', component: WorkspacePage },
  { path: '/knowledge', component: WorkspacePage },
  { path: '/chat', component: ChatPage },
  { path: '/chat/:id', component: ChatPage },
  { path: '/document', component: DocumentPage },
  { path: '/gongwen', component: GongwenPage },
  { path: '/policy', component: PolicyPage },
  { path: '/document/:id', component: DocumentPage },
  { path: '/ppt', redirect: () => `/ppt/${createPptProjectId()}` },
  { path: '/ppt/:projectId', component: PptHostPage },
  { path: '/agents', component: AgentDirectoryPage },
  { path: '/settings', component: SettingsPage },
  { path: '/login', component: LoginPage },
  { path: '/:pathMatch(.*)*', redirect: '/chat' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

const publicPaths = new Set(['/welcome', '/login'])

router.beforeEach((to) => {
  if (!publicPaths.has(to.path) && !hasSessionToken()) {
    return { path: '/login', query: { next: to.fullPath } }
  }
  if (to.path === '/login' && hasSessionToken()) {
    return typeof to.query.next === 'string' ? to.query.next : '/'
  }
})

if (typeof window !== 'undefined') {
  const resetGov = () => {
    setGovOfficeAdapter(null); resetGovSessionLoading();
    useGovDocumentsStore().$reset(); useGovSessionStore().$reset(); usePolicyQaStore().$reset();
  }
  window.addEventListener('mqw-auth-changed', resetGov)
  window.addEventListener('mqw-auth-expired', () => {
    resetGov()
    const current = router.currentRoute.value
    if (current.path === '/login') return
    router.replace({ path: '/login', query: { expired: '1', next: current.fullPath } })
  })
}

createApp(App).use(createPinia()).use(router).mount('#app')
