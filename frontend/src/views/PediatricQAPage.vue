<template>
  <main class="flex h-dvh flex-col overflow-hidden text-black pedia-root">
    <AppHeader title="" subtitle="中科信创（南京）" :show-logout="false" @goHome="router.push('/')" />

    <div class="flex min-h-0 flex-1">
      <aside class="pedia-sidebar hidden w-[220px] shrink-0 border-r border-[#D5E8D4] px-3 py-5 md:flex md:min-h-0 md:flex-col">
        <nav class="shrink-0 space-y-1">
          <button @click="router.push('/agents')" class="sidebar-btn sidebar-btn--back">
            <ArrowLeft class="size-[18px]" :stroke-width="1.8" />
            <span>返回智能体</span>
          </button>
          <button @click="createNewChat" class="sidebar-btn sidebar-btn--new">
            <Plus class="size-[18px]" :stroke-width="2" />
            <span>新对话</span>
          </button>
          <div class="sidebar-agent-badge">
            <span class="sidebar-agent-dot"></span>
            <span>少儿问答</span>
          </div>
        </nav>

        <section class="mt-4 flex min-h-0 flex-1 flex-col">
          <h2 class="sidebar-section-title">历史对话</h2>
          <div ref="historyScroller" class="min-h-0 flex-1 space-y-1 overflow-y-auto" @scroll="onHistoryScroll">
            <button
              v-for="c in chat.conversations"
              :key="c.id"
              @click="selectConversation(c.id)"
              :class="['history-item', chat.currentConvId === c.id ? 'history-item--active' : '']"
            >
              <span class="history-item-icon">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.2"/><path d="M7 4.5V7.5L9 9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
              </span>
              <span class="truncate">{{ c.title }}</span>
            </button>
            <div v-if="chat.conversationsLoading" class="sidebar-hint">加载中...</div>
            <div v-else-if="!chat.conversations.length" class="sidebar-hint">暂无对话记录</div>
          </div>
        </section>
      </aside>

      <section class="flex min-w-0 flex-1 flex-col">
        <div class="mobile-bar flex items-center gap-1 border-b border-[#D5E8D4] px-3 py-2 md:hidden">
          <button @click="router.push('/agents')" class="mobile-btn">返回</button>
          <button @click="createNewChat" class="mobile-btn">
            <Plus class="size-4" :stroke-width="2" />
            新对话
          </button>
          <div class="mobile-agent-badge">
            <span class="sidebar-agent-dot"></span>
            少儿问答
          </div>
        </div>

        <div class="min-h-0 flex-1 overflow-hidden p-3 md:p-4">
          <ChatMode
            workflow="pediatric_medical_qa"
            suggestion-context=""
            :route-base="routeBase"
            active-title="少儿问答"
            idle-title="少儿问答"
            empty-text=""
            class="pedia-chat"
          />
        </div>
      </section>
    </div>
  </main>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Plus } from 'lucide-vue-next'
import AppHeader from '../components/AppHeader.vue'
import ChatMode from '../components/ChatMode.vue'
import { useChatStore } from '../stores/chat.js'

const route = useRoute()
const router = useRouter()
const chat = useChatStore()
const historyScroller = ref(null)
const routeBase = '/agents/pediatric-medical-qa'

onMounted(async () => {
  await chat.loadConversations(50, 'pediatric_medical_qa')
  await syncRouteState()
})

watch(() => route.fullPath, () => {
  syncRouteState()
})

async function createNewChat() {
  if (!chat.currentConvId && !chat.messages.length) {
    if (route.path !== routeBase) router.replace(routeBase)
    return
  }
  chat.startNewConversation()
  window.dispatchEvent(new CustomEvent('mqw-workspace-reset'))
  await router.push(routeBase)
}

async function selectConversation(id) {
  const conv = chat.conversations.find((c) => c.id === id)
  const ok = await chat.selectConversation(id, conv?.workflow_type || 'pediatric_medical_qa')
  if (ok && route.path !== `${routeBase}/${id}`) await router.push(`${routeBase}/${id}`)
  if (!ok) await router.replace(routeBase)
}

function routeConversationId() {
  const raw = route.params.id
  const value = Array.isArray(raw) ? raw[0] : raw
  const id = Number(value)
  return Number.isInteger(id) && id > 0 ? id : null
}

async function syncRouteState() {
  const id = routeConversationId()
  if (id) {
    if (chat.currentConvId !== id) {
      const conv = chat.conversations.find((c) => c.id === id)
      const ok = await chat.selectConversation(id, conv?.workflow_type || 'pediatric_medical_qa')
      if (!ok) {
        chat.startNewConversation()
        window.dispatchEvent(new CustomEvent('mqw-workspace-reset'))
        await router.replace(routeBase)
      }
    }
  } else if (chat.currentConvId || chat.messages.length) {
    chat.startNewConversation()
    window.dispatchEvent(new CustomEvent('mqw-workspace-reset'))
  }
}

function onHistoryScroll(event) {
  const el = event.target
  if (!el || chat.conversationsLoading || !chat.conversationsHasMore) return
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 48) {
    chat.loadMoreConversations(20, 'pediatric_medical_qa')
  }
}
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;600;700&display=swap');

/* --- Root: soft garden gradient --- */
.pedia-root {
  background: #F6FBF4;
}

/* --- Sidebar --- */
.pedia-sidebar {
  background:
    linear-gradient(180deg, #F0FAED 0%, #F6FBF4 100%);
}

.sidebar-btn {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 9px;
  height: 42px;
  border-radius: 10px;
  padding: 0 13px;
  font-size: 13.5px;
  font-weight: 500;
  color: #5C6B5C;
  border: none;
  background: transparent;
  cursor: pointer;
  transition: all 0.18s ease;
}

.sidebar-btn:hover {
  background: rgba(34,197,94,0.08);
  color: #3B5C3B;
}

.sidebar-btn--back {
  color: #7A8B7A;
  font-size: 13px;
}

.sidebar-btn--new {
  border: 1px dashed #C8DFC6;
  color: #3B7A3B;
  font-weight: 600;
  margin-top: 2px;
}

.sidebar-btn--new:hover {
  background: rgba(34,197,94,0.10);
  border-color: #86C486;
}

.sidebar-agent-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 40px;
  padding: 0 14px;
  border-radius: 10px;
  background: #22C55E;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  margin-top: 6px;
  box-shadow: 0 2px 10px rgba(34,197,94,0.25);
}

.sidebar-agent-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(255,255,255,0.3);
  animation: pulse-dot 2s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { box-shadow: 0 0 0 3px rgba(255,255,255,0.3); }
  50% { box-shadow: 0 0 0 6px rgba(255,255,255,0.1); }
}

.sidebar-section-title {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #8FA88F;
  padding: 0 8px;
  margin-bottom: 8px;
}

/* --- History Items --- */
.history-item {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  color: #5C6B5C;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: all 0.18s ease;
}

.history-item:hover {
  background: rgba(34,197,94,0.07);
  color: #3B5C3B;
}

.history-item--active {
  background: rgba(34,197,94,0.12);
  color: #166534;
  font-weight: 600;
}

.history-item-icon {
  flex-shrink: 0;
  color: #8FA88F;
}

.history-item--active .history-item-icon {
  color: #22C55E;
}

.sidebar-hint {
  padding: 10px 10px;
  font-size: 12px;
  color: #8FA88F;
}

/* --- Mobile --- */
.mobile-bar {
  background: #F0FAED;
}

.mobile-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 34px;
  border-radius: 8px;
  padding: 0 12px;
  font-size: 13px;
  font-weight: 500;
  color: #5C6B5C;
  border: none;
  background: transparent;
  cursor: pointer;
  transition: all 0.15s ease;
}

.mobile-btn:hover {
  background: rgba(34,197,94,0.08);
}

.mobile-agent-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  border-radius: 8px;
  padding: 0 12px;
  background: #22C55E;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  margin-left: auto;
}

/* --- ChatMode Deep Overrides --- */
.pedia-chat :deep(.empty-prompt-title) {
  color: #166534;
  font-family: 'Noto Sans SC', system-ui, sans-serif;
}

.pedia-chat :deep(section) {
  border-color: #C8DFC6;
  background: rgba(255,255,255,0.95);
}

.pedia-chat :deep(.composer-wrap) {
  border-color: #C8DFC6;
  background: #FAFDF9;
}

.pedia-chat :deep(.composer-wrap:focus-within) {
  border-color: #86C486;
  box-shadow: 0 0 0 4px rgba(34,197,94,0.10), 0 8px 24px rgba(0,0,0,0.04);
}

.pedia-chat :deep(.composer-textarea) {
  font-family: 'Noto Sans SC', system-ui, sans-serif;
}

.pedia-chat :deep(.send-btn) {
  background: #22C55E;
  box-shadow: 0 4px 14px rgba(34,197,94,0.22);
}

.pedia-chat :deep(.send-btn:hover) {
  background: #16A34A;
}

.pedia-chat :deep(.typing-dot) {
  background: #22C55E;
}

.pedia-chat :deep(.user-text-bubble) {
  background: linear-gradient(135deg, #DCFCE7 0%, #D1FAE5 100%);
  color: #14532D;
  border-radius: 18px 18px 4px 18px;
}

.pedia-chat :deep(.assistant-content) {
  font-family: 'Noto Sans SC', system-ui, sans-serif;
}

.pedia-chat :deep(.message-action-button) {
  border-color: rgba(34,197,94,0.12);
}

.pedia-chat :deep(.message-action-button:hover:not(:disabled)) {
  border-color: rgba(34,197,94,0.3);
  box-shadow: 0 8px 20px rgba(15,23,42,0.10), 0 0 0 5px rgba(34,197,94,0.08);
}

.pedia-chat :deep(.streaming-status-note) {
  border-color: rgba(34,197,94,0.15);
  background: rgba(240,250,237,0.9);
}

.pedia-chat :deep(.message-thread) {
  gap: 22px;
}

/* --- Mobile responsive --- */
@media (max-width: 640px) {
  .pedia-sidebar {
    display: none;
  }
}
</style>
