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
import RoleEntryPage from './features/gov-office/pages/RoleEntryPage.vue'
import AgentDirectoryPage from './views/AgentDirectoryPage.vue'
import SettingsPage from './views/SettingsPage.vue'
import { hasSessionToken } from './stores/auth.js'
import { ENTRY_PATH, entryGuard } from './roleEntryGuard.js'
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
  { path: '/gongwen', component: GongwenPage },
  { path: '/policy', component: PolicyPage },
  { path: '/ppt', redirect: () => `/ppt/${createPptProjectId()}` },
  { path: '/ppt/:projectId', component: PptHostPage },
  { path: '/agents', component: AgentDirectoryPage },
  { path: '/settings', component: SettingsPage },
  // 不设登录页：进入时选择「起草人」或「审核人」；旧的 /login 链接统一转到角色入口
  { path: ENTRY_PATH, component: RoleEntryPage },
  { path: '/login', redirect: (to) => ({ path: ENTRY_PATH, query: to.query.expired ? { expired: '1' } : {} }) },
  ...govOfficeRoutes,
  { path: '/:pathMatch(.*)*', redirect: '/chat' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => entryGuard(to, hasSessionToken()))

if (typeof window !== 'undefined') {
  const resetGov = () => {
    setGovOfficeAdapter(null); resetGovSessionLoading();
    useGovDocumentsStore().$reset(); useGovSessionStore().$reset(); usePolicyQaStore().$reset();
  }
  window.addEventListener('mqw-auth-changed', resetGov)
  window.addEventListener('mqw-auth-expired', () => {
    resetGov()
    if (router.currentRoute.value.path === ENTRY_PATH) return
    router.replace({ path: ENTRY_PATH, query: { expired: '1' } })
  })
}

createApp(App).use(createPinia()).use(router).mount('#app')
