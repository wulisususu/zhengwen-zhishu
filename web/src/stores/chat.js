import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api.js'

export const useChatStore = defineStore('chat', () => {
  const conversations = ref([])
  const currentConvId = ref(null)
  const messages = ref([])
  const loading = ref(false)
  const conversationsOffset = ref(0)
  const conversationsHasMore = ref(true)
  const conversationsLoading = ref(false)

  function reset() {
    conversations.value = []
    currentConvId.value = null
    messages.value = []
    loading.value = false
    conversationsOffset.value = 0
    conversationsHasMore.value = true
    conversationsLoading.value = false
  }

  function mergeConversations(items, append = false) {
    const next = append ? [...conversations.value] : []
    for (const item of items || []) {
      const idx = next.findIndex((c) => c.id === item.id)
      if (idx >= 0) next[idx] = { ...next[idx], ...item }
      else next.push(item)
    }
    conversations.value = next
  }

  async function loadConversations(limit = 50, workflowType = 'chat') {
    conversationsLoading.value = true
    try {
      const { data } = await api.get('/conversations', { params: { limit, offset: 0, workflow_type: workflowType } })
      if (data.code === 0) {
        const payload = data.data || {}
        const items = Array.isArray(payload) ? payload : (payload.items || [])
        mergeConversations(items, false)
        conversationsOffset.value = Array.isArray(payload) ? conversations.value.length : (payload.next_offset || items.length)
        conversationsHasMore.value = Array.isArray(payload) ? false : !!payload.has_more
        if (currentConvId.value && !conversations.value.some((c) => c.id === currentConvId.value)) {
          currentConvId.value = null
          messages.value = []
        }
      }
    } catch {
      reset()
    } finally {
      conversationsLoading.value = false
    }
  }

  async function loadMoreConversations(limit = 20, workflowType = 'chat') {
    if (conversationsLoading.value || !conversationsHasMore.value) return
    conversationsLoading.value = true
    try {
      const { data } = await api.get('/conversations', { params: { limit, offset: conversationsOffset.value, workflow_type: workflowType } })
      if (data.code === 0) {
        const payload = data.data || {}
        const items = payload.items || []
        mergeConversations(items, true)
        conversationsOffset.value = payload.next_offset || (conversationsOffset.value + items.length)
        conversationsHasMore.value = !!payload.has_more
      }
    } finally {
      conversationsLoading.value = false
    }
  }

  async function createConversation(title, workflowType = 'chat') {
    const { data } = await api.post('/conversations', { title: title || 'new', workflow_type: workflowType })
    if (data.code === 0) {
      mergeConversations([data.data], true)
      conversations.value = [data.data, ...conversations.value.filter((c) => c.id !== data.data.id)]
      currentConvId.value = data.data.id
      messages.value = []
      return data.data
    }
  }

  function startNewConversation() {
    currentConvId.value = null
    messages.value = []
  }

  async function selectConversation(id, workflowType = '') {
    currentConvId.value = id
    messages.value = []
    try {
      const params = workflowType ? { workflow_type: workflowType } : {}
      const { data } = await api.get('/conversations/' + id + '/messages', { params })
      if (data.code === 0) {
        if (workflowType) {
          const conv = conversations.value.find((c) => c.id === id)
          if (conv?.workflow_type && conv.workflow_type !== workflowType) {
            currentConvId.value = null
            messages.value = []
            return false
          }
        }
        messages.value = data.data || []
        return true
      }
      currentConvId.value = null
      messages.value = []
      return false
    } catch {
      currentConvId.value = null
      messages.value = []
      return false
    }
  }

  async function sendMessage(content, workflowType = 'chat') {
    loading.value = true
    try {
      if (!currentConvId.value) await createConversation(content.slice(0, 20), workflowType)
      const { data } = await api.post('/conversations/' + currentConvId.value + '/messages', { content, workflow_type: workflowType })
      if (data.code === 0) {
        if (Array.isArray(data.data)) messages.value.push(...data.data)
        else {
          messages.value.push(...(data.data.messages || []))
          if (data.data.conversation) {
            const idx = conversations.value.findIndex((c) => c.id === data.data.conversation.id)
            if (idx >= 0) conversations.value[idx] = { ...conversations.value[idx], ...data.data.conversation }
          }
        }
      }
    } finally { loading.value = false }
  }

  return {
    conversations,
    currentConvId,
    messages,
    loading,
    conversationsHasMore,
    conversationsLoading,
    reset,
    loadConversations,
    loadMoreConversations,
    createConversation,
    startNewConversation,
    selectConversation,
    sendMessage,
  }
})
