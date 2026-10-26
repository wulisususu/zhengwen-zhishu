import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import WelcomePage from './views/WelcomePage.vue'
import WorkspacePage from './views/WorkspacePage.vue'
import ChatPage from './views/ChatPage.vue'
import DocumentPage from './views/DocumentPage.vue'
import PptHostPage from './views/PptHostPage.vue'
import LoginPage from './views/LoginPage.vue'
import AgentDirectoryPage from './views/AgentDirectoryPage.vue'
import PediatricQAPage from './views/PediatricQAPage.vue'
import SettingsPage from './views/SettingsPage.vue'
import { hasSessionToken } from './stores/auth.js'
import { govOfficeRoutes } from './features/gov-office/routes'
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
  { path: '/', redirect: '/gov' },
  { path: '/welcome', component: WelcomePage },
  { path: '/workspace', component: WorkspacePage },
  { path: '/knowledge', component: WorkspacePage },
  { path: '/chat', component: ChatPage },
  { path: '/chat/:id', component: ChatPage },
  { path: '/document', component: DocumentPage },
  { path: '/document/:id', component: DocumentPage },
  { path: '/ppt', redirect: () => `/ppt/${createPptProjectId()}` },
  { path: '/ppt/:projectId', component: PptHostPage },
  { path: '/agents', component: AgentDirectoryPage },
  { path: '/agents/pediatric-medical-qa', component: PediatricQAPage },
  { path: '/agents/pediatric-medical-qa/:id', component: PediatricQAPage },
  { path: '/settings', component: SettingsPage },
  { path: '/login', component: LoginPage },
  ...govOfficeRoutes,
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
    return typeof to.query.next === 'string' ? to.query.next : '/gov'
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
