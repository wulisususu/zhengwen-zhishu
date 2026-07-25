<template>
  <Teleport to="body">
    <div v-if="visible" class="kb-picker-overlay" @click.self="close" @keydown.esc="close">
      <div
        ref="dialogRef"
        class="kb-picker-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="从知识库添加"
      >
        <!-- Header -->
        <div class="kb-picker-header">
          <div class="kb-picker-title">
            <Cloud class="size-5 shrink-0 text-[#5E6AD2]" :stroke-width="2" />
            <span>从知识库添加</span>
          </div>
          <button type="button" class="kb-picker-close" @click="close" aria-label="关闭">
            <X class="size-5" :stroke-width="2" />
          </button>
        </div>

        <!-- Search -->
        <div class="kb-picker-search">
          <div class="kb-picker-search-input-wrap">
            <Search class="pointer-events-none absolute left-3.5 size-4 text-[#98A2B3]" :stroke-width="2" />
            <input
              ref="searchInputRef"
              v-model="query"
              class="kb-picker-search-input"
              placeholder="搜索文件名..."
              @input="onSearchInput"
            />
            <button v-if="query" type="button" class="kb-picker-search-clear" @click="clearSearch" aria-label="清除">
              <X class="size-4" :stroke-width="2" />
            </button>
          </div>
        </div>

        <!-- Body -->
        <div class="kb-picker-body">
          <div v-if="loading && !documents.length" class="kb-picker-state">
            <div class="kb-picker-spinner"></div>
            <span>加载中...</span>
          </div>
          <div v-else-if="loadError" class="kb-picker-state kb-picker-state-error">
            <span>加载知识库失败，请稍后重试</span>
            <button type="button" class="kb-picker-retry" @click="loadDocuments">重试</button>
          </div>
          <div v-else-if="!filteredDocuments.length" class="kb-picker-state">
            <span v-if="query.trim()">{{ hasFiltered ? '没有匹配的文件' : '没有匹配的文件' }}</span>
            <span v-else>暂无文档</span>
          </div>
          <div v-else class="kb-picker-list">
            <div
              v-for="doc in filteredDocuments"
              :key="doc.id"
              class="kb-picker-row"
              :class="{ 'kb-picker-row-selected': isSelected(doc) }"
              @click="toggleDoc(doc)"
            >
              <input
                type="checkbox"
                class="kb-picker-check"
                :checked="isSelected(doc)"
                :aria-label="('选择 ' + (doc.filename || ''))"
                @click.stop="toggleDoc(doc)"
              />
              <component :is="fileIcon(doc.filename)" class="size-5 shrink-0" :class="fileIconColor(doc.filename)" :stroke-width="1.8" />
              <span class="kb-picker-name" :title="doc.filename">{{ doc.filename }}</span>
              <span class="kb-picker-type">{{ fileTypeLabel(doc.filename) }}</span>
              <span class="kb-picker-date">{{ formatDate(doc.created_at) }}</span>
              <button type="button" class="kb-picker-preview-btn" @click.stop="previewDoc(doc)">预览</button>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="kb-picker-footer">
          <span class="kb-picker-count">已选 {{ selectedIds.length }} 个文件</span>
          <div class="kb-picker-actions">
            <button type="button" class="kb-picker-cancel" @click="close">取消</button>
            <button
              type="button"
              class="kb-picker-confirm"
              :disabled="!selectedIds.length"
              @click="confirm"
            >确认添加</button>
          </div>
        </div>
      </div>

      <!-- Preview Modal -->
      <div v-if="preview.visible" class="kb-preview-overlay" @click.self="closePreview">
        <div class="kb-preview-dialog">
          <div class="kb-preview-header">
            <component :is="fileIcon(preview.filename)" class="size-5 shrink-0" :class="fileIconColor(preview.filename)" :stroke-width="1.8" />
            <span class="kb-preview-name">{{ preview.filename }}</span>
            <button type="button" class="kb-picker-close" @click="closePreview" aria-label="关闭预览">
              <X class="size-5" :stroke-width="2" />
            </button>
          </div>
          <div class="kb-preview-body">
            <div v-if="preview.loading" class="kb-picker-state">加载中...</div>
            <div v-else-if="preview.error" class="kb-picker-state kb-picker-state-error">{{ preview.error }}</div>
            <div v-else-if="preview.htmlContent" class="kb-preview-html" v-html="preview.htmlContent" />
            <iframe v-else-if="preview.pdfUrl" :src="preview.pdfUrl" class="kb-preview-iframe" />
            <div v-else-if="preview.imageUrl" class="kb-preview-image-wrap">
              <img :src="preview.imageUrl" class="kb-preview-image" />
            </div>
            <pre v-else-if="preview.textContent" class="kb-preview-text">{{ preview.textContent }}</pre>
            <div v-else class="kb-picker-state">无法预览此文件</div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { Cloud, Search, X, FileText, FileSpreadsheet, Presentation, Image } from 'lucide-vue-next'
import api, { listKnowledgeDocuments, getKnowledgeDocumentFileUrl } from '../api.js'

const props = defineProps({
  visible: { type: Boolean, default: false },
  selectedDocIds: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'confirm'])

const query = ref('')
const documents = ref([])
const loading = ref(false)
const loadError = ref(false)
const selectedIds = ref([])
const searchInputRef = ref(null)
const dialogRef = ref(null)

const preview = reactive({
  visible: false,
  loading: false,
  filename: '',
  htmlContent: '',
  textContent: '',
  pdfUrl: '',
  imageUrl: '',
  error: '',
})

const filteredDocuments = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return documents.value
  return documents.value.filter((d) => String(d.filename || '').toLowerCase().includes(q))
})
const hasFiltered = computed(() => query.value.trim().length > 0)

watch(
  () => props.visible,
  (val) => {
    if (val) {
      // snapshot already-attached docs so they appear checked and aren't lost
      selectedIds.value = [...new Set((props.selectedDocIds || []).map(Number).filter((n) => n > 0))]
      query.value = ''
      if (!documents.value.length) loadDocuments()
      nextTick(() => {
        searchInputRef.value?.focus()
        dialogRef.value?.focus()
      })
    }
  },
  { immediate: true },
)

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  cleanupPreviewUrls()
})

function onKeydown(event) {
  if (!props.visible) return
  if (event.key === 'Escape') {
    if (preview.visible) closePreview()
    else close()
  }
}

async function loadDocuments() {
  loading.value = true
  loadError.value = false
  try {
    const res = await listKnowledgeDocuments()
    if (res.code === 0 && res.data) {
      documents.value = (res.data.documents || []).slice(0, 500)
    } else {
      documents.value = []
      loadError.value = true
    }
  } catch (err) {
    console.error('Load knowledge documents failed:', err)
    documents.value = []
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function onSearchInput() {
  // client-side filename filter — no network round-trip
}

function clearSearch() {
  query.value = ''
  searchInputRef.value?.focus()
}

function isSelected(doc) {
  return selectedIds.value.includes(Number(doc.id))
}

function toggleDoc(doc) {
  const id = Number(doc.id)
  const idx = selectedIds.value.indexOf(id)
  if (idx >= 0) selectedIds.value.splice(idx, 1)
  else selectedIds.value.push(id)
}

function confirm() {
  const chosen = documents.value.filter((d) => selectedIds.value.includes(Number(d.id)))
  const docs = chosen.map((d) => ({
    doc_id: d.id,
    filename: d.filename || '',
    file_type: d.file_type || '',
    file_size: d.file_size || 0,
    created_at: d.created_at || '',
    download_url: getKnowledgeDocumentFileUrl(d.id),
  }))
  emit('confirm', docs)
}

function close() {
  cleanupPreviewUrls()
  emit('close')
}

function previewDoc(doc) {
  const docId = doc.id || doc.doc_id
  if (!docId) return
  const filename = doc.filename || doc.file_name || ''
  const ext = filename.split('.').pop().toLowerCase()
  const fileUrl = '/knowledge/documents/' + docId + '/file'

  cleanupPreviewUrls()
  preview.visible = true
  preview.loading = true
  preview.filename = filename
  preview.htmlContent = ''
  preview.textContent = ''
  preview.pdfUrl = ''
  preview.imageUrl = ''
  preview.error = ''

  if (['doc', 'docx'].includes(ext)) {
    api.get(fileUrl, { responseType: 'arraybuffer' })
      .then((res) => {
        import('mammoth').then((mammoth) => {
          mammoth.convertToHtml({ arrayBuffer: res.data }).then((result) => {
            preview.htmlContent = result.value || '<p>（空文档）</p>'
            preview.loading = false
          }).catch((e) => {
            preview.error = '文档转换失败: ' + (e.message || '')
            preview.loading = false
          })
        }).catch(() => {
          preview.error = '文档预览组件加载失败'
          preview.loading = false
        })
      }).catch((e) => {
        const s = e.response ? e.response.status : 0
        preview.error = s === 404 ? '文件已失效，原始文件可能已被清理' : '文件加载失败'
        preview.loading = false
      })
  } else if (ext === 'pdf') {
    api.get(fileUrl, { responseType: 'blob' })
      .then((res) => {
        preview.pdfUrl = URL.createObjectURL(res.data)
        preview.loading = false
      }).catch((e) => {
        const s = e.response ? e.response.status : 0
        preview.error = s === 404 ? '文件已失效，原始文件可能已被清理' : '文件加载失败'
        preview.loading = false
      })
  } else if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'].includes(ext)) {
    api.get(fileUrl, { responseType: 'blob' })
      .then((res) => {
        preview.imageUrl = URL.createObjectURL(res.data)
        preview.loading = false
      }).catch(() => {
        preview.error = '文件加载失败'
        preview.loading = false
      })
  } else if (['txt', 'md', 'csv', 'json', 'log', 'py', 'js', 'ts', 'html', 'xml', 'yaml', 'yml'].includes(ext)) {
    api.get(fileUrl, { responseType: 'text', transformResponse: [(data) => data] })
      .then((res) => {
        preview.textContent = typeof res.data === 'string' ? res.data : JSON.stringify(res.data, null, 2)
        preview.loading = false
      }).catch(() => {
        preview.error = '文件加载失败'
        preview.loading = false
      })
  } else {
    preview.error = '暂不支持预览此文件格式'
    preview.loading = false
  }
}

function closePreview() {
  cleanupPreviewUrls()
  preview.visible = false
}

function cleanupPreviewUrls() {
  if (preview.pdfUrl) {
    URL.revokeObjectURL(preview.pdfUrl)
    preview.pdfUrl = ''
  }
  if (preview.imageUrl) {
    URL.revokeObjectURL(preview.imageUrl)
    preview.imageUrl = ''
  }
}

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
    const d = new Date(String(s).replace(' ', 'T'))
    const now = new Date()
    if (d.toDateString() === now.toDateString()) return '今天 ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
    return (d.getMonth() + 1) + '月' + d.getDate() + '日'
  } catch {
    return s
  }
}
</script>

<style scoped>
.kb-picker-overlay {
  position: fixed; inset: 0; z-index: 9000;
  display: flex; align-items: center; justify-content: center;
  background: rgba(16, 24, 40, 0.42);
  backdrop-filter: blur(2px);
}
.kb-picker-dialog {
  width: min(720px, 92vw);
  max-height: min(640px, 88vh);
  display: flex; flex-direction: column;
  background: #fff;
  border-radius: 16px;
  border: 1px solid #E6EAF2;
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.18);
  overflow: hidden;
  outline: none;
}
.kb-picker-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #EEF2F6;
}
.kb-picker-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 16px; font-weight: 600; color: #111827;
}
.kb-picker-close {
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: 8px; padding: 6px; color: #98A2B3; background: transparent; border: 0; cursor: pointer;
}
.kb-picker-close:hover { background: #F2F4F7; color: #667085; }
.kb-picker-search {
  padding: 12px 20px;
  border-bottom: 1px solid #EEF2F6;
}
.kb-picker-search-input-wrap {
  position: relative; display: flex; align-items: center;
}
.kb-picker-search-input {
  height: 40px; width: 100%;
  border: 1px solid #E4E7EC; border-radius: 12px;
  background: #fff; padding: 0 40px 0 40px;
  font-size: 14px; color: #111827; outline: none;
}
.kb-picker-search-input::placeholder { color: #98A2B3; }
.kb-picker-search-input:focus { border-color: #C7D2FE; box-shadow: 0 0 0 4px rgba(94, 106, 210, 0.1); }
.kb-picker-search-clear {
  position: absolute; right: 8px;
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: 9999px; color: #98A2B3;
  background: transparent; border: 0; cursor: pointer;
}
.kb-picker-search-clear:hover { color: #667085; }
.kb-picker-body {
  flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 12px 16px;
}
.kb-picker-list { display: flex; flex-direction: column; gap: 6px; }
.kb-picker-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 12px; border: 1px solid #E6EAF2;
  background: #fff; cursor: pointer; transition: background-color .12s, border-color .12s;
}
.kb-picker-row:hover { background: #F4F6FF; border-color: #D0D5DD; }
.kb-picker-row-selected { background: #EEF2FF; border-color: #C7D2FE; }
.kb-picker-check {
  width: 16px; height: 16px; accent-color: #5E6AD2; cursor: pointer; flex-shrink: 0;
}
.kb-picker-name {
  flex: 1 1 auto; min-width: 0; font-size: 13px; font-weight: 500; color: #111827;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.kb-picker-type {
  flex-shrink: 0; width: 64px; text-align: center; font-size: 12px; color: #667085;
}
.kb-picker-date {
  flex-shrink: 0; width: 72px; text-align: right; font-size: 12px; color: #98A2B3;
}
.kb-picker-preview-btn {
  flex-shrink: 0; border: 1px solid #E4E7EC; background: #fff; border-radius: 8px;
  padding: 4px 8px; font-size: 12px; font-weight: 500; color: #475467; cursor: pointer;
}
.kb-picker-preview-btn:hover { background: #F9FAFB; color: #111827; }
.kb-picker-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;
  padding: 48px 16px; font-size: 14px; color: #98A2B3; text-align: center;
}
.kb-picker-state-error { color: #ef4444; }
.kb-picker-retry {
  margin-top: 4px; border: 1px solid #E4E7EC; background: #fff; border-radius: 8px;
  padding: 6px 14px; font-size: 13px; color: #475467; cursor: pointer;
}
.kb-picker-retry:hover { background: #F9FAFB; }
.kb-picker-spinner {
  width: 22px; height: 22px; border-radius: 9999px;
  border: 2px solid #E4E7EC; border-top-color: #5E6AD2;
  animation: kb-picker-spin .8s linear infinite;
}
@keyframes kb-picker-spin { to { transform: rotate(360deg); } }
.kb-picker-footer {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 20px; border-top: 1px solid #EEF2F6; background: #FCFCFD;
}
.kb-picker-count { font-size: 13px; color: #475467; font-weight: 500; }
.kb-picker-actions { display: flex; align-items: center; gap: 10px; }
.kb-picker-cancel {
  border: 1px solid #E4E7EC; background: #fff; border-radius: 10px;
  padding: 8px 16px; font-size: 13px; font-weight: 500; color: #475467; cursor: pointer;
}
.kb-picker-cancel:hover { background: #F9FAFB; color: #111827; }
.kb-picker-confirm {
  border: 0; border-radius: 10px; padding: 8px 18px;
  font-size: 13px; font-weight: 600; color: #fff; cursor: pointer;
  background: #5E6AD2; box-shadow: 0 4px 12px rgba(94, 106, 210, 0.2);
}
.kb-picker-confirm:hover { background: #4F5AC0; }
.kb-picker-confirm:disabled { background: #C7CAD1; box-shadow: none; cursor: not-allowed; }

.kb-preview-overlay {
  position: fixed; inset: 0; z-index: 9100;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0, 0, 0, 0.4); backdrop-filter: blur(2px);
}
.kb-preview-dialog {
  display: flex; flex-direction: column;
  height: 85vh; width: 90vw; max-width: 960px;
  background: #fff; border-radius: 16px; border: 1px solid #E6EAF2;
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.18); overflow: hidden;
}
.kb-preview-header {
  display: flex; align-items: center; gap: 10px; padding: 12px 20px;
  border-bottom: 1px solid #EEF2F6;
}
.kb-preview-name { flex: 1 1 auto; min-width: 0; font-size: 14px; font-weight: 600; color: #111827; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kb-preview-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
.kb-preview-html { padding: 24px 32px; max-width: none; }
.kb-preview-iframe { width: 100%; height: 100%; border: 0; }
.kb-preview-image-wrap { display: flex; align-items: center; justify-content: center; height: 100%; background: #F5F5F5; padding: 16px; }
.kb-preview-image { max-height: 100%; max-width: 100%; object-fit: contain; }
.kb-preview-text { white-space: pre-wrap; padding: 24px 32px; font-size: 13px; line-height: 1.6; color: #344054; }
</style>
