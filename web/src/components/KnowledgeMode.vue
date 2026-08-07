<template>
  <section class="flex min-h-[560px] flex-col overflow-hidden rounded-[16px] border border-[#E6EAF2] bg-[rgba(255,255,255,0.96)] shadow-[0_8px_24px_rgba(16,24,40,0.06)]">
    <div class="border-b border-[#EEF2F6] bg-[linear-gradient(180deg,rgba(252,252,254,0.98)_0%,rgba(248,250,252,0.92)_100%)] px-5 py-4">
      <h2 class="text-[18px] font-semibold text-[#111827]">知识库模式</h2>
      <p class="mt-1 text-[13px] text-[#667085]">
        上传文档建立知识库，用于语义搜索和问答
        <span v-if="status.ready" class="ml-2 inline-block rounded-full border border-green-200 bg-green-50 px-2.5 py-0.5 text-[11px] font-medium text-green-700">
          就绪 {{ status.vector_count }} 向量 / {{ status.document_count }} 文档
        </span>
        <span v-else class="ml-2 inline-block rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-[11px] font-medium text-amber-700">
          {{ status.message || '加载中...' }}
        </span>
      </p>
    </div>

    <div v-if="status.error" class="mx-5 mt-4 rounded-[12px] border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-600">
      {{ status.error }}
    </div>
    <div v-if="loadError" class="mx-5 mt-4 rounded-[12px] border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-600">
      {{ loadError }}
    </div>

    <div class="grid flex-1 gap-4 bg-[radial-gradient(circle_at_top,rgba(238,241,255,0.45)_0%,rgba(252,252,254,0)_28%),linear-gradient(180deg,#FCFCFE_0%,#F7F8FB_100%)] p-5 md:grid-cols-[minmax(0,1fr)_300px]">
      <div class="flex min-h-0 flex-col rounded-[20px] border border-[#E6EAF2] bg-[rgba(255,255,255,0.84)] p-5 shadow-[0_10px_24px_rgba(16,24,40,0.05)]">
        <h3 class="shrink-0 text-[15px] font-semibold text-[#111827]">知识库搜索</h3>
        <div class="mt-3 flex shrink-0 gap-2">
          <input
            v-model="query"
            @keyup.enter="doSearch"
            class="flex-1 rounded-[14px] border border-[#E4E7EC] bg-[linear-gradient(180deg,#FFFFFF_0%,#FCFCFE_100%)] px-3.5 py-2.5 text-[14px] text-[#111827] outline-none transition-all duration-150 placeholder:text-[#98A2B3] focus:border-[#C7D2FE] focus:ring-4 focus:ring-[#5E6AD2]/10"
            placeholder="输入问题进行语义搜索..."
          />
          <button
            @click="doSearch"
            :disabled="searching || !status.ready"
            class="shrink-0 rounded-[14px] bg-[#111827] px-4.5 py-2.5 text-[14px] font-medium text-white shadow-[0_10px_24px_rgba(17,24,39,0.18)] transition-all duration-150 hover:bg-[#0B1220] disabled:opacity-50"
          >
            {{ searching ? '搜索中...' : '搜索' }}
          </button>
        </div>
        <div v-if="searchError" class="mt-3 rounded-[12px] border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-600">
          {{ searchError }}
        </div>
        <div class="mt-4 min-h-0 flex-1 overflow-y-auto">
          <div v-if="searchResults.length" class="space-y-3">
            <div
              v-for="(r, i) in searchResults"
              :key="i"
              class="rounded-[16px] border border-[#E6EAF2] bg-[#FCFCFD] p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]"
            >
              <div class="flex items-center justify-between gap-3">
                <span class="min-w-0 truncate text-[12px] font-medium text-[#5E6AD2]">{{ r.filename }}</span>
                <span class="shrink-0 text-[11px] text-[#98A2B3]">相关度: {{ (r.score || 0).toFixed(4) }}</span>
              </div>
              <p class="mt-2 text-[13px] leading-6 text-[#475467] whitespace-pre-wrap">{{ r.chunk_text }}</p>
            </div>
          </div>
          <div v-else-if="searched" class="flex min-h-[180px] items-center justify-center rounded-[16px] border border-[#E6EAF2] bg-[#FCFCFD] text-center text-[14px] text-[#98A2B3]">
            未找到相关结果
          </div>
          <div v-else class="flex min-h-[180px] items-center justify-center rounded-[16px] border border-[#E6EAF2] bg-[#FCFCFD] px-6 text-center text-[14px] text-[#98A2B3]">
            输入问题后点击搜索，将在知识库中检索相关文档片段
          </div>
        </div>
      </div>

      <aside class="flex min-h-0 flex-col rounded-[20px] border border-[#E6EAF2] bg-[rgba(255,255,255,0.88)] p-5 shadow-[0_10px_24px_rgba(16,24,40,0.05)]">
        <h3 class="shrink-0 text-[15px] font-semibold text-[#111827]">文档管理</h3>
        <div class="mt-3 shrink-0">
          <label class="flex h-[92px] cursor-pointer flex-col items-center justify-center rounded-[16px] border border-dashed border-[#D0D5DD] bg-[#F8FAFC] transition-all duration-150 hover:border-[#C7D2FE] hover:bg-white">
            <input type="file" class="hidden" accept=".txt,.md,.csv,.json,.log,.pdf,.docx,.xlsx" @change="onFileSelect" />
            <span class="text-[13px] font-medium text-[#475467]">点击或拖拽上传文件</span>
            <span class="mt-1 text-[11px] text-[#98A2B3]">.txt .md .csv .json .log .pdf .docx .xlsx</span>
          </label>
          <div v-if="uploading" class="mt-2 text-center text-[12px] text-[#5E6AD2]">上传中...</div>
          <div v-if="uploadMsg" class="mt-2 text-center text-[12px]" :class="uploadOk ? 'text-green-600' : 'text-red-500'">{{ uploadMsg }}</div>
        </div>
        <div class="mt-4 min-h-0 flex-1 overflow-y-auto">
          <div v-if="loading" class="py-4 text-center text-[13px] text-[#98A2B3]">加载中...</div>
          <div v-else-if="!documents.length" class="flex min-h-[180px] items-center justify-center rounded-[16px] border border-[#E6EAF2] bg-[#FCFCFD] px-4 text-center text-[13px] text-[#98A2B3]">
            暂无文档，请上传文件建立知识库
          </div>
          <div v-else class="space-y-2.5">
            <div
              v-for="doc in documents"
              :key="doc.id"
              class="flex items-center gap-3 rounded-[14px] border border-[#E6EAF2] bg-[#FCFCFD] px-3.5 py-3 shadow-[0_1px_2px_rgba(16,24,40,0.04)]"
            >
              <div class="min-w-0 flex-1">
                <div class="truncate text-[13px] font-medium text-[#111827]">{{ doc.filename }}</div>
                <div class="mt-1 text-[11px] text-[#98A2B3]">{{ doc.chunks || doc.chunk_count || 0 }} 片段</div>
              </div>
              <button
                @click="removeDoc(doc.id, doc.filename)"
                class="shrink-0 rounded-[10px] p-1.5 text-[#98A2B3] transition-colors duration-150 hover:bg-red-50 hover:text-red-500"
                title="删除"
              >
                <span class="text-[12px]">✕</span>
              </button>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </section>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import {
  getKnowledgeStatus,
  uploadKnowledgeDocument,
  listKnowledgeDocuments,
  deleteKnowledgeDocument,
  searchKnowledge,
} from '../api.js'

const status = reactive({ ready: false, vector_count: 0, document_count: 0, message: '', error: null })
const query = ref('')
const searching = ref(false)
const searched = ref(false)
const searchResults = ref([])
const searchError = ref('')
const documents = ref([])
const loading = ref(false)
const uploading = ref(false)
const uploadMsg = ref('')
const uploadOk = ref(false)
const loadError = ref('')
let pollTimer = null
let pollCount = 0
const MAX_POLL = 40

onMounted(async () => {
  await loadStatus()
  await loadDocuments()
})

onBeforeUnmount(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})

async function loadStatus() {
  try {
    const res = await getKnowledgeStatus()
    if (res.code === 0 && res.data) {
      Object.assign(status, res.data)
      loadError.value = ''
      if (!status.ready && !pollTimer) {
        startPolling()
      }
    }
  } catch (err) {
    loadError.value = (err.response && err.response.data && err.response.data.message) || '知识库状态获取失败，请检查网络'
  }
}

function startPolling() {
  pollCount = 0
  pollTimer = setInterval(async () => {
    pollCount++
    await loadStatus()
    if (status.ready) {
      clearInterval(pollTimer)
      pollTimer = null
      await loadDocuments()
      return
    }
    if (status.error) {
      clearInterval(pollTimer)
      pollTimer = null
      return
    }
    if (pollCount >= MAX_POLL) {
      clearInterval(pollTimer)
      pollTimer = null
      loadError.value = '知识库初始化超时，请刷新页面重试'
    }
  }, 3000)
}

async function loadDocuments() {
  loading.value = true
  try {
    const res = await listKnowledgeDocuments()
    if (res.code === 0 && res.data) {
      documents.value = res.data.documents || []
    }
  } catch (err) {
    loadError.value = (err.response && err.response.data && err.response.data.message) || '文档列表加载失败'
  }
  loading.value = false
}

async function onFileSelect(e) {
  const file = e.target.files && e.target.files[0]
  if (!file) return
  uploading.value = true
  uploadMsg.value = ''
  try {
    const res = await uploadKnowledgeDocument(file)
    if (res.code === 0) {
      uploadOk.value = true
      uploadMsg.value = '已上传: ' + res.data.filename + ' (' + res.data.chunks + ' 个片段)'
      await loadDocuments()
      await loadStatus()
    } else {
      uploadOk.value = false
      uploadMsg.value = res.message || '上传失败'
    }
  } catch (err) {
    uploadOk.value = false
    const detail = err.response && err.response.data && err.response.data.detail
    uploadMsg.value = detail || (err.response && err.response.data && err.response.data.message) || '上传失败'
  }
  uploading.value = false
  e.target.value = ''
  setTimeout(() => { uploadMsg.value = '' }, 4000)
}

async function removeDoc(id, filename) {
  if (!confirm('确定删除文档 "' + filename + '"？')) return
  try {
    const res = await deleteKnowledgeDocument(id)
    if (res.code === 0) {
      await loadDocuments()
      await loadStatus()
    }
  } catch (err) {
    loadError.value = (err.response && err.response.data && err.response.data.message) || '删除失败'
  }
}

async function doSearch() {
  const q = query.value.trim()
  if (!q || searching.value || !status.ready) return
  searching.value = true
  searched.value = false
  searchResults.value = []
  searchError.value = ''
  try {
    const res = await searchKnowledge(q)
    if (res.code === 0 && res.data) {
      searchResults.value = res.data.results || []
    }
    searched.value = true
  } catch (err) {
    const detail = err.response && err.response.data && err.response.data.detail
    searchError.value = detail || (err.response && err.response.data && err.response.data.message) || '搜索请求失败'
  }
  searching.value = false
}
</script>
