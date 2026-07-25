<template>
  <div class="flex h-full flex-col overflow-hidden rounded-[16px] border border-[#E6EAF2] bg-[rgba(255,255,255,0.96)] shadow-[0_8px_24px_rgba(16,24,40,0.06)]">
    <!-- Toolbar -->
    <div class="flex shrink-0 items-center gap-3 border-b border-[#EEF2F6] bg-[linear-gradient(180deg,rgba(252,252,254,0.98)_0%,rgba(248,250,252,0.92)_100%)] px-5 py-3.5">
      <button
        @click="$emit('back')"
        class="flex shrink-0 items-center gap-1.5 rounded-[10px] border border-[#E4E7EC] bg-white px-3 py-2 text-[13px] font-medium text-[#475467] transition-all duration-150 hover:border-[#D0D5DD] hover:bg-[#F9FAFB] hover:text-[#111827]"
      >
        <ArrowLeft class="size-4" :stroke-width="2" />
        <span>返回聊天</span>
      </button>

      <div class="relative flex min-w-0 flex-1 items-center">
        <Search class="pointer-events-none absolute left-3.5 size-4 text-[#98A2B3]" :stroke-width="2" />
        <input
          ref="searchInputRef"
          v-model="query"
          @keyup.enter="doSearch"
          @input="onInputChange"
          class="h-10 w-full rounded-[12px] border border-[#E4E7EC] bg-white pl-10 pr-10 text-[14px] text-[#111827] outline-none transition-all duration-150 placeholder:text-[#98A2B3] focus:border-[#C7D2FE] focus:ring-4 focus:ring-[#5E6AD2]/10"
          placeholder="搜索文件内容..."
        />
        <button
          v-if="query"
          @click="clearSearch"
          class="absolute right-3 flex size-5 items-center justify-center rounded-full text-[#98A2B3] transition-colors hover:text-[#667085]"
        >
          <X class="size-4" :stroke-width="2" />
        </button>
      </div>

      <button
        @click="doSearch"
        :disabled="searching || !query.trim()"
        class="shrink-0 rounded-[12px] bg-[#111827] px-4 py-2 text-[13px] font-medium text-white shadow-[0_4px_12px_rgba(17,24,39,0.12)] transition-all duration-150 hover:bg-[#222] disabled:opacity-40"
      >
        {{ searching ? '搜索中...' : '搜索' }}
      </button>
    </div>

    <!-- Content -->
    <div class="min-h-0 flex-1 overflow-y-auto">
      <div v-if="loading && !documents.length" class="flex h-full items-center justify-center">
        <div class="text-[14px] text-[#98A2B3]">加载中...</div>
      </div>

      <!-- Search results -->
      <div v-else-if="hasSearched" class="p-5">
        <div v-if="searching" class="flex h-[200px] items-center justify-center">
          <div class="text-[14px] text-[#98A2B3]">正在检索...</div>
        </div>
        <div v-else-if="searchError" class="flex flex-col items-center justify-center py-16">
          <div class="text-[15px] font-medium text-[#ef4444]">检索失败</div>
          <div class="mt-1 text-[13px] text-[#98A2B3]">请稍后重试</div>
        </div>
        <div v-else-if="!searchResults.length" class="flex flex-col items-center justify-center py-16">
          <div class="text-[15px] font-medium text-[#475467]">没有找到相关内容</div>
          <div class="mt-1 text-[13px] text-[#98A2B3]">可以换个关键词再试试</div>
        </div>
        <div v-else class="space-y-3">
          <div class="mb-4 text-[13px] text-[#98A2B3]">找到 {{ searchResults.length }} 条相关结果</div>
          <div
            v-for="(r, i) in searchResults"
            :key="i"
            class="rounded-[14px] border border-[#E6EAF2] bg-white px-5 py-4 transition-all duration-150 hover:border-[#D0D5DD] hover:shadow-[0_2px_8px_rgba(16,24,40,0.06)]"
          >
            <div class="flex items-center gap-3">
              <component :is="fileIcon(r.filename)" class="size-5 shrink-0" :class="fileIconColor(r.filename)" :stroke-width="1.8" />
              <span class="min-w-0 flex-1 truncate text-[14px] font-semibold text-[#111827]">{{ r.filename }}</span>
              <button
                @click="previewDoc(r)"
                class="shrink-0 rounded-[8px] border border-[#E4E7EC] bg-white px-2.5 py-1 text-[11px] font-medium text-[#475467] transition-all hover:bg-[#F9FAFB] hover:text-[#111827]"
              >预览</button>
              <span class="shrink-0 rounded-full bg-[#F2F4F7] px-2.5 py-0.5 text-[11px] font-medium text-[#667085]">
                {{ (r.score || 0).toFixed(2) }}
              </span>
            </div>
            <p class="mt-2.5 text-[13px] leading-[22px] text-[#475467]" v-html="highlightSnippet(r.chunk_text || '', query)" />
            <div class="mt-2 flex items-center gap-3 text-[11px] text-[#98A2B3]">
              <span v-if="r.page_no">第 {{ r.page_no }} 页 · </span>
              <span>{{ r.filename }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Default file list -->
      <div v-else class="p-5">
        <div class="mb-4 flex items-center gap-2">
          <span v-if="status.ready" class="inline-flex items-center gap-1.5 rounded-full border border-green-200 bg-green-50 px-2.5 py-1 text-[11px] font-medium text-green-700">
            <span class="size-1.5 rounded-full bg-green-500"></span>
            就绪 · {{ status.document_count }} 文档 · {{ status.vector_count }} 向量
          </span>
          <span v-else class="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-700">
            <span class="size-1.5 rounded-full bg-amber-500 animate-pulse"></span>
            {{ status.message || '加载中...' }}
          </span>
        </div>

        <div v-if="documents.length" class="overflow-hidden rounded-[12px] border border-[#E6EAF2]">
          <div class="flex items-center bg-[#F9FAFB] px-5 py-2.5 text-[12px] font-semibold uppercase tracking-wider text-[#98A2B3]">
            <span class="flex-1">名称</span>
            <span class="w-[80px] text-center">类型</span>
            <span class="w-[80px] text-center">状态</span>
            <span class="w-[120px] text-center">来源</span>
            <span class="w-[130px] text-center">更新时间</span>
            <span class="w-[100px] text-center">操作</span>
          </div>
          <div
            v-for="(doc, i) in documents"
            :key="doc.id"
            :class="[
              'flex items-center px-5 transition-colors duration-100',
              i % 2 === 0 ? 'bg-white' : 'bg-[#FCFCFD]',
              'hover:bg-[#F4F6FF]'
            ]"
            style="height: 64px;"
          >
            <div class="flex min-w-0 flex-1 items-center gap-2.5">
              <component :is="fileIcon(doc.filename)" class="size-5 shrink-0" :class="fileIconColor(doc.filename)" :stroke-width="1.8" />
              <span class="truncate text-[13px] font-medium text-[#111827]">{{ doc.filename }}</span>
            </div>
            <span class="w-[80px] text-center text-[12px] text-[#667085]">{{ fileTypeLabel(doc.filename) }}</span>
            <span class="w-[80px] text-center">
              <span class="inline-block rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-[11px] font-medium text-green-700">已索引</span>
            </span>
            <span class="w-[120px] text-center text-[12px] text-[#98A2B3]">本地知识库</span>
            <span class="w-[130px] text-center text-[12px] text-[#98A2B3]">{{ formatDate(doc.created_at) }}</span>
            <span class="w-[100px] text-center">
              <button
                @click="previewDoc(doc)"
                class="rounded-[8px] px-2 py-1 text-[12px] font-medium text-[#5E6AD2] transition-all hover:bg-[#EEF2FF]"
              >预览</button>
              <button
                @click="downloadDoc(doc)"
                class="ml-1 rounded-[8px] px-2 py-1 text-[12px] font-medium text-[#667085] transition-all hover:bg-[#F2F4F7] hover:text-[#111827]"
              >下载</button>
            </span>
          </div>
        </div>
        <div v-else class="flex flex-col items-center justify-center py-16">
          <div class="text-[15px] font-medium text-[#475467]">暂无文档</div>
          <div class="mt-1 text-[13px] text-[#98A2B3]">上传文件后将自动索引</div>
        </div>
      </div>
    </div>

    <!-- Preview Modal -->
    <Teleport to="body">
      <div v-if="preview.visible" class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-[2px]" @click.self="closePreview">
        <div class="relative flex h-[85vh] w-[90vw] max-w-[960px] flex-col overflow-hidden rounded-[16px] border border-[#E6EAF2] bg-white shadow-[0_24px_48px_rgba(0,0,0,0.18)]">
          <!-- Preview header -->
          <div class="flex shrink-0 items-center gap-3 border-b border-[#EEF2F6] px-5 py-3">
            <component :is="fileIcon(preview.filename)" class="size-5 shrink-0" :class="fileIconColor(preview.filename)" :stroke-width="1.8" />
            <span class="min-w-0 flex-1 truncate text-[14px] font-semibold text-[#111827]">{{ preview.filename }}</span>
            <button @click="closePreview" class="rounded-[8px] p-1.5 text-[#98A2B3] transition-colors hover:bg-[#F2F4F7] hover:text-[#667085]">
              <X class="size-5" :stroke-width="2" />
            </button>
          </div>
          <!-- Preview body -->
          <div class="min-h-0 flex-1 overflow-y-auto">
            <div v-if="preview.loading" class="flex h-full items-center justify-center text-[14px] text-[#98A2B3]">加载中...</div>
            <div v-else-if="preview.error" class="flex h-full flex-col items-center justify-center text-[14px]">
              <div class="font-medium text-[#ef4444]">{{ preview.error }}</div>
            </div>
            <!-- DOCX rendered as HTML -->
            <div v-else-if="preview.htmlContent" class="prose prose-sm max-w-none px-8 py-6" v-html="preview.htmlContent" />
            <!-- PDF in iframe -->
            <iframe v-else-if="preview.pdfUrl" :src="preview.pdfUrl" class="h-full w-full border-0" />
            <!-- Image -->
            <div v-else-if="preview.imageUrl" class="flex h-full items-center justify-center bg-[#F5F5F5] p-4">
              <img :src="preview.imageUrl" class="max-h-full max-w-full object-contain" />
            </div>
            <!-- Text -->
            <pre v-else-if="preview.textContent" class="whitespace-pre-wrap px-8 py-6 text-[13px] leading-6 text-[#344054]">{{ preview.textContent }}</pre>
            <!-- Fallback -->
            <div v-else class="flex h-full items-center justify-center text-[14px] text-[#98A2B3]">无法预览此文件</div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ArrowLeft, Search, X, FileText, FileSpreadsheet, Presentation, File, Image } from 'lucide-vue-next'
import api, { getKnowledgeStatus, listKnowledgeDocuments, searchKnowledge, getKnowledgeDocumentFileUrl } from '../api.js'

defineEmits(['back'])

const query = ref('')
const searchInputRef = ref(null)
const searching = ref(false)
const hasSearched = ref(false)
const searchResults = ref([])
const searchError = ref('')
const documents = ref([])
const loading = ref(false)
const status = reactive({ ready: false, vector_count: 0, document_count: 0, message: '' })
const preview = reactive({ visible: false, loading: false, filename: '', htmlContent: '', textContent: '', pdfUrl: '', imageUrl: '', error: '' })

onMounted(async () => {
  await loadStatus()
  await loadDocuments()
})

async function loadStatus() {
  try {
    const res = await getKnowledgeStatus()
    if (res.code === 0 && res.data) Object.assign(status, res.data)
  } catch {}
}

async function loadDocuments() {
  loading.value = true
  try {
    const res = await listKnowledgeDocuments()
    if (res.code === 0 && res.data) documents.value = (res.data.documents || []).slice(0, 200)
  } catch {}
  loading.value = false
}

async function doSearch() {
  const q = query.value.trim()
  if (!q || searching.value) return
  searching.value = true
  hasSearched.value = true
  searchResults.value = []
  searchError.value = ''
  try {
    const res = await searchKnowledge(q, 20)
    if (res.code === 0 && res.data) searchResults.value = res.data.results || []
    else searchError.value = res.message || '检索失败'
  } catch { searchError.value = '检索失败，请稍后重试' }
  searching.value = false
}

function clearSearch() {
  query.value = ''
  hasSearched.value = false
  searchResults.value = []
  searchError.value = ''
}

function onInputChange() {
  if (!query.value.trim() && hasSearched.value) clearSearch()
}

function highlightSnippet(text, q) {
  if (!q || !text) return escapeHtml(text || '')
  let result = escapeHtml(text)
  for (const kw of q.trim().split(/\s+/).filter(Boolean)) {
    const safe = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    result = result.replace(new RegExp(safe, 'gi'), m => `<mark style="background:#FEF3C7;padding:1px 2px;border-radius:2px">${m}</mark>`)
  }
  return result
}

function escapeHtml(s) { return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') }

function fileIcon(name) {
  const ext = (name || '').split('.').pop().toLowerCase()
  if (['ppt', 'pptx'].includes(ext)) return Presentation
  if (['xls', 'xlsx', 'csv'].includes(ext)) return FileSpreadsheet
  if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'].includes(ext)) return Image
  return FileText
}

function fileIconColor(name) {
  const ext = (name || '').split('.').pop().toLowerCase()
  if (['ppt', 'pptx'].includes(ext)) return 'text-orange-500'
  if (['xls', 'xlsx', 'csv'].includes(ext)) return 'text-green-600'
  if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'].includes(ext)) return 'text-purple-500'
  return 'text-blue-500'
}

function fileTypeLabel(name) {
  const ext = (name || '').split('.').pop().toLowerCase()
  const map = { doc: 'Word', docx: 'Word', pdf: 'PDF', ppt: 'PPT', pptx: 'PPT', xls: 'Excel', xlsx: 'Excel', csv: 'CSV', md: 'Markdown', txt: '文本' }
  return map[ext] || (ext || '文件').toUpperCase()
}

function formatDate(s) {
  if (!s) return ''
  try {
    const d = new Date(s.replace(' ', 'T'))
    const now = new Date()
    if (d.toDateString() === now.toDateString()) return '今天 ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
    return (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
  } catch { return s }
}

function previewDoc(doc) {
  const docId = doc.doc_id || doc.id
  if (!docId) return
  const filename = doc.filename || doc.file_name || ''
  const ext = filename.split('.').pop().toLowerCase()
  const fileUrl = '/knowledge/documents/' + docId + '/file'

  preview.visible = true
  preview.loading = true
  preview.filename = filename
  preview.htmlContent = ''
  preview.textContent = ''
  preview.pdfUrl = ''
  preview.imageUrl = ''
  preview.error = ''

  if (['doc', 'docx'].includes(ext)) {
    api.get(fileUrl, { responseType: 'arraybuffer' }).then(res => {
      import('mammoth').then(mammoth => {
        mammoth.convertToHtml({ arrayBuffer: res.data }).then(result => {
          preview.htmlContent = result.value || '<p>（空文档）</p>'
          preview.loading = false
        }).catch(e => { preview.error = '文档转换失败: ' + (e.message || ''); console.error('Mammoth convert error:', e); preview.loading = false })
      }).catch((e) => { preview.error = '文档预览组件加载失败'; console.error('Mammoth import error:', e); preview.loading = false })
    }).catch((e) => { const s = e.response ? e.response.status : 0; preview.error = s === 404 ? '文件已失效，原始文件可能已被清理' : '文件加载失败: ' + (s || e.message); preview.loading = false })
  } else if (ext === 'pdf') {
    api.get(fileUrl, { responseType: 'blob' }).then(res => {
      preview.pdfUrl = URL.createObjectURL(res.data)
      preview.loading = false
    }).catch((e) => { const s = e.response ? e.response.status : 0; preview.error = s === 404 ? '文件已失效，原始文件可能已被清理' : '文件加载失败: ' + (s || e.message); preview.loading = false })
  } else if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'].includes(ext)) {
    api.get(fileUrl, { responseType: 'blob' }).then(res => {
      preview.imageUrl = URL.createObjectURL(res.data)
      preview.loading = false
    }).catch((e) => { const s = e.response ? e.response.status : 0; preview.error = s === 404 ? '文件已失效，原始文件可能已被清理' : '文件加载失败: ' + (s || e.message); preview.loading = false })
  } else if (['txt', 'md', 'csv', 'json', 'log', 'py', 'js', 'ts', 'html', 'xml', 'yaml', 'yml'].includes(ext)) {
    api.get(fileUrl, { responseType: 'text', transformResponse: [data => data] }).then(res => {
      preview.textContent = typeof res.data === 'string' ? res.data : JSON.stringify(res.data, null, 2)
      preview.loading = false
    }).catch((e) => { const s = e.response ? e.response.status : 0; preview.error = s === 404 ? '文件已失效，原始文件可能已被清理' : '文件加载失败: ' + (s || e.message); preview.loading = false })
  } else {
    preview.error = '暂不支持预览此文件格式'
    preview.loading = false
  }
}

function downloadDoc(doc) {
  const docId = doc.doc_id || doc.id
  if (!docId) return
  const filename = doc.filename || doc.file_name || 'download'
  const url = api.defaults.baseURL + '/knowledge/documents/' + docId + '/file'
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  // Add auth header via fetch + blob
  api.get('/knowledge/documents/' + docId + '/file', { responseType: 'blob' }).then(res => {
    const blobUrl = URL.createObjectURL(res.data)
    a.href = blobUrl
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000)
  }).catch(() => { window.open(url, '_blank') })
}

function closePreview() {
  if (preview.pdfUrl) URL.revokeObjectURL(preview.pdfUrl)
  preview.visible = false
}
</script>
