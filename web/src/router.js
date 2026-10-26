import { createRouter, createWebHistory } from 'vue-router'
import LoginPage from './views/LoginPage.vue'
import WelcomePage from './views/WelcomePage.vue'
import WorkspacePage from './views/WorkspacePage.vue'
import ChatPage from './views/ChatPage.vue'
import GongwenPage from './views/GongwenPage.vue'
import PolicyPage from './views/PolicyPage.vue'
import AgentDirectoryPage from './views/AgentDirectoryPage.vue'

const routes = [
  { path: '/login', name: 'login', component: LoginPage },
  { path: '/', name: 'welcome', component: WelcomePage, meta: { auth: true } },
  { path: '/workspace', name: 'workspace', component: WorkspacePage, meta: { auth: true } },
  { path: '/knowledge', name: 'knowledge', component: WorkspacePage, meta: { auth: true } },
  { path: '/chat', name: 'chat', component: ChatPage, meta: { auth: true } },
  { path: '/chat/:id', name: 'chat-detail', component: ChatPage, meta: { auth: true } },
  { path: '/gongwen', name: 'gongwen', component: GongwenPage, meta: { auth: true } },
  { path: '/policy', name: 'policy', component: PolicyPage, meta: { auth: true } },
  { path: '/agents', name: 'agents', component: AgentDirectoryPage, meta: { auth: true } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const s = localStorage.getItem('mqw-session')
  if (to.meta.auth && !s) return { name: 'login' }
})

export default router

