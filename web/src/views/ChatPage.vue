<template>
  <main class="flex h-dvh flex-col overflow-hidden bg-[#e2e9f1] text-black">
    <AppHeader title="" subtitle="中科信创（南京）" :show-logout="false" @goHome="router.push('/')" />

    <div class="flex min-h-0 flex-1 p-3 gap-3">
      <aside class="hidden w-[232px] shrink-0 rounded-[12px] border border-[#dce6f1] bg-white px-4 py-3 md:flex md:min-h-0 md:flex-col">
        <nav class="shrink-0 space-y-1.5 pb-5">
          <button
            @click="createNewChat"
            class="group flex h-10 w-full items-center gap-2.5 rounded-[14px] border border-transparent px-3.5 text-left text-[14px] font-semibold text-[#475467] transition-all duration-150 hover:border-[#E6EAF2] hover:bg-[#F6F8FC] hover:text-[#111827]"
          >
            <Plus class="size-4" :stroke-width="2" />
            <span>新聊天</span>
          </button>
          <button class="flex h-10 w-full items-center gap-2.5 rounded-[14px] border border-[rgba(94,106,210,0.10)] bg-[#EEF2FF] px-3.5 text-left text-[14px] font-semibold text-[#5E6AD2] shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-all duration-150">
            <MessageSquare class="size-4" :stroke-width="2" />
            <span>聊天</span>
          </button>
          <button type="button" class="flex h-10 w-full items-center gap-2.5 rounded-[10px] bg-[#FBE9EE] px-3.5 text-left text-[15px] font-medium text-[#4B5563]" @click="router.push('/document')">
            <MessageSquare class="size-4" :stroke-width="2" />
            <span>文档</span>
          </button>
          <button
            type="button"
            @click="router.push('/ppt')"
            class="flex h-10 w-full items-center gap-2.5 rounded-[14px] border border-transparent px-3.5 text-left text-[14px] font-semibold text-[#667085] transition-all duration-150 hover:border-[#E6EAF2] hover:bg-[#F6F8FC] hover:text-[#111827]"
          >
            <Presentation class="size-4" :stroke-width="2" />
            <span>PPT生成</span>
          </button>
          <button
            type="button"
            class="flex h-10 w-full items-center gap-2.5 rounded-[14px] border border-transparent px-3.5 text-left text-[14px] font-semibold text-[#667085] transition-all duration-150 hover:border-[#E6EAF2] hover:bg-[#F6F8FC] hover:text-[#111827]"
            v-if="ff.show_agents"
            @click="router.push('/agents')"
          >
            <Bot class="size-4" :stroke-width="2" />
            <span>智能体</span>
          </button>
          <button type="button" class="flex h-10 w-full items-center gap-2.5 rounded-[14px] border border-transparent px-3.5 text-left text-[14px] font-semibold text-[#667085] transition-all duration-150 hover:border-[#E6EAF2] hover:bg-[#F6F8FC] hover:text-[#111827]" @click="router.push('/settings')">
            <Settings class="size-4" :stroke-width="2" />
            <span>设置</span>
          </button>
        </nav>

        <section class="mt-1 flex min-h-0 flex-1 flex-col">
          <h2 class="shrink-0 px-3 pb-2 text-[13px] font-semibold tracking-[0.02em] text-[#98A2B3]">最近对话</h2>
          <div ref="historyScroller" class="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1" @scroll="onHistoryScroll">
            <button
              v-for="c in chat.conversations"
              :key="c.id"
              @click="selectConversation(c.id)"
              :class="[
                'block w-full rounded-[10px] border px-2.5 py-2 text-left text-[13px] leading-6 transition-all duration-150',
                chat.currentConvId === c.id
                  ? 'border-[rgba(94,106,210,0.10)] bg-[#F4F6FF] font-semibold text-[#344054] shadow-[0_1px_2px_rgba(16,24,40,0.04)]'
                  : 'border-transparent bg-transparent font-medium text-[#475467] hover:border-[#E6EAF2] hover:bg-[#F8FAFC] hover:text-[#111827]'
              ]"
            >
              <span class="block truncate">{{ c.title }}</span>
            </button>
            <div v-if="chat.conversationsLoading" class="px-3 py-2 text-[12px] font-medium text-[#98A2B3]">加载中...</div>
            <div v-else-if="!chat.conversations.length" class="px-3 py-2 text-[13px] text-[#98A2B3]">暂无对话</div>
          </div>
        </section>

        <div ref="userMenuRef" class="relative shrink-0 border-t border-[#E6EAF2] pt-3">
          <div
            v-if="userMenuOpen"
            class="absolute bottom-[58px] left-0 right-0 z-20 overflow-hidden rounded-[14px] border border-[#E6EAF2] bg-white py-1.5 shadow-[0_14px_34px_rgba(15,23,42,0.14)]"
          >
            <button
              type="button"
              class="flex h-11 w-full items-center gap-3 px-4 text-left text-[15px] font-medium text-[#344054] transition-colors hover:bg-[#F8FAFC]"
              @click="switchAccount"
            >
              <Repeat2 class="size-4" :stroke-width="2" />
              <span>切换角色</span>
            </button>
            <button
              type="button"
              class="flex h-11 w-full items-center gap-3 px-4 text-left text-[15px] font-medium text-[#344054] transition-colors hover:bg-[#F8FAFC]"
              @click="logout"
            >
              <LogOut class="size-4" :stroke-width="2" />
              <span>退出</span>
            </button>
          </div>
          <button
            type="button"
            class="flex h-10 w-full items-center gap-2.5 rounded-[14px] px-2.5 text-left text-[#344054] transition-colors hover:bg-[#F8FAFC]"
            :aria-expanded="userMenuOpen ? 'true' : 'false'"
            @click.stop="userMenuOpen = !userMenuOpen"
          >
            <span class="flex size-9 shrink-0 items-center justify-center rounded-full bg-[#DBEAFE] text-[#7C8AA6]">
              <UserCircle class="size-5" :stroke-width="2" />
            </span>
            <span class="min-w-0 flex-1 truncate text-[14px] font-semibold">{{ displayUserName }}</span>
            <ChevronRight class="size-4 shrink-0 text-[#98A2B3]" :stroke-width="2" />
          </button>
        </div>
      </aside>

      <section class="flex min-w-0 flex-1 flex-col rounded-[12px] bg-[#eef3f9] overflow-hidden">
        <div class="flex items-center gap-2 overflow-x-auto border-b border-[#E6EAF2] bg-[rgba(255,255,255,0.9)] px-3 py-2 md:hidden">
          <button
            @click="createNewChat"
            class="h-10 shrink-0 rounded-[10px] border border-transparent bg-transparent px-3 text-[14px] font-semibold text-[#667085] hover:border-[#E6EAF2] hover:bg-[#F8FAFC] hover:text-[#111827]"
          >
            新聊天
          </button>
          <button class="h-10 shrink-0 rounded-[10px] border border-[rgba(94,106,210,0.10)] bg-[#EEF2FF] px-3 text-[14px] font-semibold text-[#5E6AD2] shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
            聊天
          </button>
          <button
            type="button"
            @click="router.push('/ppt')"
            class="h-10 shrink-0 rounded-[10px] border border-transparent bg-transparent px-3 text-[14px] font-semibold text-[#667085] hover:border-[#E6EAF2] hover:bg-[#F8FAFC] hover:text-[#111827]"
          >
            PPT生成
          </button>
          <button
            type="button"
            class="h-10 shrink-0 rounded-[10px] border border-transparent bg-transparent px-3 text-[14px] font-semibold text-[#667085] hover:border-[#E6EAF2] hover:bg-[#F8FAFC] hover:text-[#111827]"
            v-if="ff.show_agents"
            @click="router.push('/agents')"
          >
            智能体
          </button>
        </div>

        <div class="min-h-0 flex-1 overflow-hidden p-3">
          <ChatMode
            workflow="chat"
            suggestion-context="chat"
            route-base="/chat"
            active-title="当前对话"
            idle-title="聊天"
            empty-text=""
            variant="prototype"
          />
        </div>
      </section>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bot, ChevronRight, LogOut, MessageSquare, Plus, Presentation, Repeat2, Settings, UserCircle } from 'lucide-vue-next'
import AppHeader from '../components/AppHeader.vue'
import ChatMode from '../components/ChatMode.vue'
import { useChatStore } from '../stores/chat.js'
import { useAuthStore } from '../stores/auth.js'
import { useFeatureFlags } from '../composables/useFeatureFlags.js'

const route = useRoute()
const { flags: ff, load: loadFF } = useFeatureFlags()
loadFF()

const router = useRouter()
const chat = useChatStore()
const auth = useAuthStore()
const historyScroller = ref(null)
const userMenuRef = ref(null)
const userMenuOpen = ref(false)
const rightPanelMode = ref('chat')

const displayUserName = computed(() => {
  const session = auth.session || {}
  return session.username || session.name || session.user?.username || session.user?.name || '用户'
})

onMounted(async () => {
  window.addEventListener('pointerdown', handleWindowPointerDown)
  await chat.loadConversations(50, 'chat')
  await syncRouteState()
})

onUnmounted(() => {
  window.removeEventListener('pointerdown', handleWindowPointerDown)
})

watch(() => route.fullPath, () => {
  syncRouteState()
})

async function createNewChat() {
  rightPanelMode.value = 'chat'
  if (!chat.currentConvId && !chat.messages.length) {
    if (route.path !== '/chat') router.replace('/chat')
    return
  }
  chat.startNewConversation()
  window.dispatchEvent(new CustomEvent('mqw-workspace-reset'))
  await router.push('/chat')
}

async function selectConversation(id) {
  rightPanelMode.value = 'chat'
  const conv = chat.conversations.find((c) => c.id === id)
  const ok = await chat.selectConversation(id, conv?.workflow_type || 'chat')
  if (ok && route.path !== `/chat/${id}`) await router.push(`/chat/${id}`)
  if (!ok) await router.replace('/chat')
}

function handleWindowPointerDown(event) {
  if (!userMenuOpen.value) return
  const el = userMenuRef.value
  if (el && event.target instanceof Node && el.contains(event.target)) return
  userMenuOpen.value = false
}

function switchAccount() {
  logout()
}

function logout() {
  auth.clearSession()
  router.push('/entry')
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
      const ok = await chat.selectConversation(id, conv?.workflow_type || 'chat')
      if (!ok) {
        chat.startNewConversation()
        window.dispatchEvent(new CustomEvent('mqw-workspace-reset'))
        await router.replace('/chat')
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
    chat.loadMoreConversations(20, 'chat')
  }
}
</script>
