<template>
  <section class="flex h-full min-h-0 flex-col overflow-hidden rounded-[16px] border border-[#E6EAF2] bg-[rgba(255,255,255,0.96)] shadow-[0_8px_24px_rgba(16,24,40,0.06)]">
    <div class="flex flex-col gap-3 border-b border-[#EEF2F6] bg-[linear-gradient(180deg,rgba(252,252,254,0.98)_0%,rgba(248,250,252,0.92)_100%)] px-5 py-4 sm:flex-row sm:items-center">
      <div>
        <h2 class="text-[18px] font-semibold text-[#111827]">文档管理库</h2>
        <p class="mt-1 text-[13px] leading-5 text-[#667085]">沿用聊天页的圆角、描边和层次阴影，只保留当前文档列表功能</p>
      </div>
      <div class="relative sm:ml-auto sm:w-[280px]">
        <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#98A2B3]" />
        <input
          v-model="query"
          placeholder="搜索文档"
          class="h-11 w-full rounded-[14px] border border-[#E4E7EC] bg-[linear-gradient(180deg,#FFFFFF_0%,#FCFCFE_100%)] pl-10 pr-3 text-[14px] text-[#111827] outline-none transition-all duration-150 placeholder:text-[#98A2B3] focus:border-[#C7D2FE] focus:ring-4 focus:ring-[#5E6AD2]/10"
        />
      </div>
      <button
        @click="loadFiles"
        :disabled="loading"
        class="flex h-11 items-center justify-center gap-2 rounded-[14px] bg-[#111827] px-4.5 text-[14px] font-medium text-white shadow-[0_10px_24px_rgba(17,24,39,0.18)] transition-all duration-150 hover:bg-[#0B1220] disabled:opacity-50"
      >
        <RefreshCw class="size-4" :class="loading ? 'animate-spin' : ''" :stroke-width="1.9" />刷新
      </button>
    </div>

    <div class="flex-1 overflow-auto bg-[radial-gradient(circle_at_top,rgba(238,241,255,0.45)_0%,rgba(252,252,254,0)_28%),linear-gradient(180deg,#FCFCFE_0%,#F7F8FB_100%)] p-5">
      <div v-if="filteredFiles.length" class="overflow-hidden rounded-[20px] border border-[#E6EAF2] bg-[rgba(255,255,255,0.84)] shadow-[0_10px_24px_rgba(16,24,40,0.05)]">
        <table class="w-full min-w-[620px] border-collapse text-left text-[14px]">
          <thead>
            <tr class="border-b border-[#E6EAF2] text-[#98A2B3]">
              <th class="px-4 py-3 font-medium">文件名</th>
              <th class="px-4 py-3 font-medium">类型</th>
              <th class="px-4 py-3 font-medium">大小</th>
              <th class="px-4 py-3 font-medium">生成时间</th>
              <th class="px-4 py-3 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="file in filteredFiles" :key="file.id" class="border-b border-[#EEF2F6] bg-[rgba(255,255,255,0.88)] last:border-0">
              <td class="max-w-[280px] truncate px-4 py-4 font-medium text-[#111827]">{{ file.filename }}</td>
              <td class="px-4 py-4 text-[#667085]">{{ file.type || file.filetype || '-' }}</td>
              <td class="px-4 py-4 text-[#667085]">{{ formatFileSize(file.size || file.filesize) }}</td>
              <td class="px-4 py-4 text-[#667085]">{{ formatDate(file.created_at) }}</td>
              <td class="px-4 py-4 text-right">
                <button
                  @click="downloadFile(file)"
                  class="inline-flex h-9 items-center gap-1.5 rounded-[12px] px-3 text-[#667085] transition-colors duration-150 hover:bg-white hover:text-[#111827]"
                >
                  <Download class="size-4" :stroke-width="1.9" />下载
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div
        v-else
        class="flex min-h-[260px] items-center justify-center rounded-[20px] border border-[#E6EAF2] bg-[rgba(255,255,255,0.82)] text-[14px] text-[#98A2B3] shadow-[0_10px_24px_rgba(16,24,40,0.05)]"
      >
        {{ loading ? '正在读取文档...' : '暂无文档' }}
      </div>
      <p v-if="error" class="mt-3 rounded-[12px] border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-600">{{ error }}</p>
      <div v-if="filteredFiles.length" class="mt-4 text-[13px] text-[#98A2B3]">共 {{ filteredFiles.length }} 个文档</div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Download, RefreshCw, Search } from 'lucide-vue-next'
import api from '../api.js'
import { useAuthStore } from '../stores/auth.js'

const auth = useAuthStore()
const files = ref([])
const query = ref('')
const loading = ref(false)
const error = ref('')
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'tif', 'tiff', 'ico', 'heic', 'heif'])

const filteredFiles = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  const documentFiles = files.value.filter(isDocumentFile)
  if (!keyword) return documentFiles
  return documentFiles.filter((file) => String(file.filename || '').toLowerCase().includes(keyword))
})

onMounted(() => {
  window.addEventListener('mqw-workspace-reset', resetFiles)
  loadFiles()
})

onUnmounted(() => {
  window.removeEventListener('mqw-workspace-reset', resetFiles)
})

watch(() => auth.session?.token, (token, previousToken) => {
  if (token === previousToken) return
  resetFiles()
  if (token) loadFiles()
})

function resetFiles() {
  files.value = []
  query.value = ''
  loading.value = false
  error.value = ''
}

async function loadFiles() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get('/files')
    files.value = data.code === 0 ? (data.data || []) : []
    if (data.code !== 0) error.value = data.message || '文档列表读取失败'
  } catch (e) {
    error.value = '文档列表读取失败：' + e.message
  } finally {
    loading.value = false
  }
}

function isDocumentFile(file) {
  const filename = String(file.filename || '').toLowerCase()
  const rawType = String(file.type || file.filetype || '').toLowerCase().replace(/^\./, '')
  const type = rawType.startsWith('image/') ? rawType.slice('image/'.length) : rawType
  const extFromName = filename.includes('.') ? filename.split('.').pop() : ''
  const ext = type || extFromName
  return !IMAGE_EXTENSIONS.has(ext)
}

function formatFileSize(size) {
  if (!size) return '-'
  if (size < 1024 * 1024) return Math.max(1, Math.round(size / 1024)) + 'KB'
  return (size / 1024 / 1024).toFixed(1) + 'MB'
}

function formatDate(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN')
}

async function downloadFile(file) {
  error.value = ''
  try {
    const response = await api.get('/files/' + file.id + '/download', { responseType: 'blob' })
    const blob = new Blob([response.data], { type: response.headers['content-type'] || 'application/octet-stream' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = file.filename || 'document.docx'
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (e) {
    error.value = '下载失败：' + e.message
  }
}
</script>
