<template>
  <main class="flex h-dvh flex-col overflow-hidden bg-[#eef3f9] text-black">
    <AppHeader title="" subtitle="政务办公智能体" :show-logout="false" @goHome="router.push('/')" />

    <div class="flex min-h-0 flex-1 gap-3 p-3">
      <!-- ================= 左：政策库 ================= -->
      <aside class="hidden w-[300px] shrink-0 flex-col overflow-hidden rounded-[12px] border border-[#dce6f1] bg-white md:flex">
        <div class="flex items-center gap-2 border-b border-[#EEF2F7] px-3.5 py-2.5">
          <span class="text-[14px] font-semibold text-[#344054]">政策库</span>
          <span class="text-[12px] text-[#98A2B3]">{{ docs.length }} 件 / {{ stats.clauses || 0 }} 条</span>
          <button type="button" class="gov-icon-btn ml-auto" @click="showUpload = !showUpload">
            <Plus class="size-4" :stroke-width="2" />
          </button>
        </div>

        <!-- 上传表单 -->
        <div v-if="showUpload" class="border-b border-[#EEF2F7] bg-[#F8FBFF] px-3.5 py-3">
          <div class="mb-2 flex items-center gap-1 rounded-[8px] bg-[#EDF3FA] p-0.5">
            <button type="button" :class="['gov-tab', mode === 'file' ? 'gov-tab--on' : '']"
              @click="mode = 'file'">上传文件</button>
            <button type="button" :class="['gov-tab', mode === 'text' ? 'gov-tab--on' : '']"
              @click="mode = 'text'">粘贴正文</button>
          </div>

          <template v-if="mode === 'file'">
            <input ref="fileInput" type="file" accept=".pdf,.docx,.txt,.md" class="hidden" @change="onFileChange" />
            <button type="button" class="gov-upload" @click="fileInput?.click()">
              <Upload class="size-4" :stroke-width="2" />
              <span class="truncate">{{ file ? file.name : '选择政策原文（PDF/DOCX/TXT）' }}</span>
            </button>
            <p class="mt-1.5 text-[11px] leading-4 text-[#A8B2C1]">
              扫描件 / 截图打印件会自动 OCR，识别结果需人工核对
            </p>
          </template>

          <template v-else>
            <textarea v-model="pasteText" rows="7" class="gov-input gov-textarea"
              placeholder="把政策正文整段粘贴到这里（含「第一条 第二条…」或「一、二、」编号）" />
            <p class="mt-1.5 text-[11px] leading-4 text-[#A8B2C1]">
              网页政策或 OCR 识别不可靠时用这条通道，文字最干净
            </p>
          </template>

          <input v-model="meta.title" class="gov-input mt-2" placeholder="政策标题（留空自动提取）" />
          <div class="mt-2 grid grid-cols-2 gap-2">
            <input v-model="meta.doc_no" class="gov-input" placeholder="文号" />
            <input v-model="meta.issuer" class="gov-input" placeholder="发文机关" />
            <input v-model="meta.effective_date" class="gov-input" placeholder="生效日期" />
            <input v-model="meta.expire_date" class="gov-input" placeholder="失效日期" />
          </div>
          <button type="button" class="gov-primary mt-2 w-full"
            :disabled="(mode === 'file' ? !file : !pasteText.trim()) || uploading" @click="submit">
            <Loader2 v-if="uploading" class="size-4 animate-spin" :stroke-width="2" />
            {{ uploading ? '解析入库中…' : (mode === 'file' ? '上传并解析' : '解析入库') }}
          </button>
          <p class="mt-1.5 text-[11.5px] leading-4 text-[#A8B2C1]">按「第X条」切分，保留页码与原文校验值</p>
        </div>

        <!-- 结果提示：不用 alert，避免挡住页面也避免把失败显示成成功 -->
        <div v-if="notice" :class="['mx-3.5 mt-2 rounded-[8px] border px-2.5 py-2 text-[11.5px] leading-4',
          notice.type === 'error' ? 'border-[#F3D6D4] bg-[#FDF4F3] text-[#A8322D]' : 'border-[#D7E6D8] bg-[#F4FBF5] text-[#2F6E3B]']">
          <div class="flex items-start gap-1.5">
            <span class="flex-1 whitespace-pre-line">{{ notice.text }}</span>
            <button type="button" class="shrink-0 opacity-60 hover:opacity-100" @click="notice = null">
              <X class="size-3" :stroke-width="2" />
            </button>
          </div>
        </div>

        <!-- 政策列表 -->
        <div class="min-h-0 flex-1 overflow-y-auto">
          <button v-for="d in docs" :key="d.id" type="button"
            :class="['gov-doc', focusPolicy === d.id ? 'gov-doc--on' : '']"
            @click="focusPolicy = focusPolicy === d.id ? null : d.id">
            <div class="flex items-start gap-1.5">
              <span class="line-clamp-2 flex-1 text-[13px] font-medium leading-5 text-[#344054]">{{ d.title }}</span>
              <span :class="['gov-status', statusClass(d.status)]">{{ d.status }}</span>
            </div>
            <div class="mt-1 truncate text-[11.5px] text-[#98A2B3]">
              {{ d.doc_no || '无文号' }} · {{ d.clause_count }} 条
            </div>
            <div v-if="focusPolicy === d.id" class="mt-1.5 space-y-0.5 text-[11.5px] text-[#667085]">
              <div>机关：{{ d.issuer || '—' }}</div>
              <div>生效：{{ d.effective_date || '—' }}</div>
              <div>失效：{{ d.expire_date || '—' }}</div>
              <div>校验：{{ d.checksum.slice(0, 12) }}</div>
            </div>
          </button>
          <p v-if="!docs.length" class="px-3.5 py-6 text-center text-[12.5px] text-[#98A2B3]">
            暂无政策，点右上角 + 上传
          </p>
        </div>
      </aside>

      <!-- ================= 右：问答 ================= -->
      <section class="flex min-w-0 flex-1 flex-col overflow-hidden rounded-[12px] border border-[#dce6f1] bg-white">
        <div class="flex flex-wrap items-center gap-2 border-b border-[#EEF2F7] px-4 py-2.5">
          <span class="text-[13.5px] font-semibold text-[#344054]">政策解读</span>
          <span class="text-[12px] text-[#98A2B3]">仅依据已入库政策作答，结论附条款依据</span>
          <div class="ml-auto flex items-center gap-1.5">
            <select v-model="scope" class="gov-select">
              <option value="current">全部现行政策</option>
              <option value="all">全部政策（含已废止）</option>
              <option value="policy" :disabled="!focusPolicy">仅选中政策</option>
            </select>
            <label class="gov-check">
              <input v-model="excludeDeprecated" type="checkbox" />
              不引用已废止
            </label>
            <button v-if="turns.length" type="button" class="gov-ghost" @click="clearTurns">
              清空对话（{{ turns.length }}）
            </button>
          </div>
        </div>

        <div ref="scroller" class="min-h-0 flex-1 overflow-y-auto bg-[#f7f9fc] px-4 py-4">
          <!-- 空态 -->
          <div v-if="!turns.length && !asking" class="flex h-full flex-col items-center justify-center text-center">
            <BookMarked class="size-10 text-[#C7CFDB]" :stroke-width="1.4" />
            <p class="mt-3 text-[14px] text-[#667085]">输入政策问题，例如「小微企业首次贷款贴息的补贴比例是多少」</p>
            <p class="mt-1 text-[12.5px] text-[#98A2B3]">每条结论都会标注引用条款；依据不足时不生成结论</p>
          </div>

          <!-- 历史问答：每轮都保留在页面上，后一次提问不覆盖前一次 -->
          <div v-for="(t, ti) in turns" :key="t.id" class="gov-turn">
            <div class="gov-q">
              <span class="gov-q-index">{{ ti + 1 }}</span>
              <p class="min-w-0 flex-1 text-[13px] leading-6 text-[#344054]">{{ t.question }}</p>
              <button type="button" class="gov-q-del" title="删除这一轮" @click="removeTurn(ti)">
                <X class="size-3" :stroke-width="2" />
              </button>
            </div>

            <!-- 检索中：还没拿到证据 -->
            <div v-if="!t.data" class="gov-loading">
              <Loader2 class="size-4 animate-spin text-[#2563A8]" :stroke-width="2" />
              <span>{{ t.stage }}，已等待 {{ elapsed }} 秒</span>
            </div>

            <!-- 有依据 -->
            <div v-else-if="t.data.status === 'answered'" class="gov-answer">
              <div class="mb-2 flex flex-wrap items-center gap-2">
                <span v-if="t.streaming" class="gov-badge gov-badge--warn">生成中</span>
                <span v-else :class="['gov-badge', t.data.sufficiency === 'full' ? 'gov-badge--ok' : 'gov-badge--warn']">
                  {{ t.data.sufficiency === 'full' ? '依据充分' : '含待核实依据' }}
                </span>
                <span class="text-[11.5px] text-[#98A2B3]">
                  引用 {{ t.data.citations.length }} 条 · 候选 {{ t.data.meta.candidates }} 条
                  <template v-if="t.data.meta.excluded_deprecated"> · 已排除已废止 {{ t.data.meta.excluded_deprecated }} 条</template>
                  · {{ t.streaming ? '生成中' : sourceLabel(t.data.meta.generated_by) }}
                </span>
              </div>

              <p class="gov-conclusion">
                <template v-for="(seg, i) in segments(t.data.conclusion)" :key="i">
                  <button v-if="seg.cite" type="button" class="gov-cite"
                    @click="openCite(seg.cite, t.data.citations)">
                    [{{ seg.cite }}]
                  </button>
                  <span v-else>{{ seg.text }}</span>
                </template>
                <span v-if="t.streaming" class="gov-cursor"></span>
              </p>

              <div v-if="t.data.supplement" class="gov-supplement">
                <span class="font-semibold">补充说明　</span>{{ t.data.supplement }}
              </div>

              <ul v-if="t.data.manual_confirm?.length" class="gov-manual">
                <li v-for="(m, i) in t.data.manual_confirm" :key="i">待人工确认：{{ m }}</li>
              </ul>

              <!-- 引用卡片 -->
              <div class="mt-3 flex items-center gap-2">
                <span class="text-[12.5px] font-semibold text-[#475467]">
                  {{ t.streaming ? '检索到的依据（生成中）' : '本次回答的引用依据' }}
                </span>
                <span class="text-[11.5px] text-[#98A2B3]">{{ t.data.citations.length }} 条</span>
              </div>
              <div class="mt-1.5 space-y-1.5">
                <button v-for="c in t.data.citations" :key="c.clause_id" type="button" class="gov-cite-card"
                  @click="openCite(c.index, t.data.citations)">
                  <div class="flex items-center gap-2">
                    <span class="gov-cite-no">[{{ c.index }}]</span>
                    <span class="truncate text-[12.5px] font-semibold text-[#344054]">《{{ c.policy_title }}》{{ c.clause_no }}</span>
                    <span :class="['gov-status ml-auto', statusClass(c.status)]">{{ c.status }}</span>
                  </div>
                  <p class="mt-1 line-clamp-2 text-[12px] leading-5 text-[#667085]">
                    …{{ c.excerpt.hl }}…
                  </p>
                  <p class="mt-0.5 text-[11px] text-[#A8B2C1]">
                    {{ c.doc_no || '无文号' }} · {{ c.issuer || '—' }} · 第 {{ c.page }} 页 · 相关度 {{ c.score }}
                  </p>
                </button>
              </div>

              <div v-if="!t.streaming" class="mt-3 flex flex-wrap gap-2">
                <button type="button" class="gov-ghost" @click="copyAnswer(t)">
                  <Copy class="size-3.5" :stroke-width="2" />复制回答
                </button>
                <button type="button" class="gov-ghost" @click="toDraft(t)">
                  <FileSignature class="size-3.5" :stroke-width="2" />加入公文起草依据
                </button>
              </div>
            </div>

            <div v-if="t.error" class="gov-nobasis mt-2">
              <div class="flex items-start gap-2">
                <AlertTriangle class="mt-0.5 size-4 shrink-0 text-[#B7791F]" :stroke-width="2" />
                <p class="text-[12.5px] leading-6 text-[#6B5A3E]">回答中断：{{ t.error }}</p>
              </div>
            </div>

            <!-- 无依据 -->
            <div v-else-if="t.data && t.data.status !== 'answered'" class="gov-nobasis">
              <div class="flex items-start gap-2">
                <AlertTriangle class="mt-0.5 size-4 shrink-0 text-[#B7791F]" :stroke-width="2" />
                <div>
                  <p class="text-[13.5px] font-semibold text-[#7A4E10]">未找到足够依据，不生成结论</p>
                  <p class="mt-1 text-[12.5px] leading-6 text-[#6B5A3E]">{{ t.data.reason }}</p>
                </div>
              </div>

              <div v-if="t.data.candidates?.length" class="mt-3">
                <p class="text-[12px] font-semibold text-[#667085]">检索到的候选条款（未达可信阈值，不作为依据）</p>
                <div class="mt-1.5 space-y-1">
                  <div v-for="c in t.data.candidates.slice(0, 5)" :key="c.clause_id" class="gov-cand">
                    <span class="truncate">《{{ c.policy_title }}》{{ c.clause_no }}</span>
                    <span class="ml-auto shrink-0 text-[11px] text-[#98A2B3]">相关度 {{ c.score }}</span>
                  </div>
                </div>
              </div>

              <div class="mt-3 flex flex-wrap gap-2">
                <button type="button" class="gov-ghost" @click="showUpload = true">前往政策库补充</button>
                <button type="button" class="gov-ghost" @click="question = ''">换个问法</button>
              </div>
            </div>
          </div>

        </div>

        <!-- 输入区 -->
        <div class="shrink-0 border-t border-[#EEF2F7] px-4 py-3">
          <div class="flex items-end gap-2">
            <textarea v-model="question" rows="2" class="gov-composer-input"
              placeholder="输入政策问题，例如：小微企业的贴息比例和上限是多少"
              @keydown.enter.exact.prevent="ask" />
            <button type="button" class="gov-send" :disabled="asking || !question.trim()" @click="ask">
              <Send class="size-4" :stroke-width="2" />
            </button>
          </div>
          <p class="mt-1.5 text-[11.5px] text-[#A8B2C1]">
            结论仅基于已入库政策，不含模型自身知识；依据不足时系统拒绝作答。
          </p>
        </div>
      </section>

      <!-- ================= 原文详情抽屉 ================= -->
      <transition name="slide">
        <aside v-if="activeCite" class="hidden w-[360px] shrink-0 flex-col overflow-hidden rounded-[12px] border border-[#dce6f1] bg-white lg:flex">
          <div class="flex items-center gap-2 border-b border-[#EEF2F7] px-3.5 py-2.5">
            <span class="text-[13.5px] font-semibold text-[#344054]">原文详情</span>
            <span class="gov-cite-no">[{{ activeCite.index }}]</span>
            <button type="button" class="gov-icon-btn ml-auto" @click="activeCite = null">
              <X class="size-3.5" :stroke-width="2" />
            </button>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto px-3.5 py-3">
            <p class="text-[13px] font-semibold leading-6 text-[#111827]">《{{ activeCite.policy_title }}》</p>
            <dl class="mt-2 space-y-1 text-[12px] text-[#667085]">
              <div class="flex gap-2"><dt class="w-[64px] shrink-0 text-[#98A2B3]">文号</dt><dd>{{ activeCite.doc_no || '—' }}</dd></div>
              <div class="flex gap-2"><dt class="w-[64px] shrink-0 text-[#98A2B3]">发布机关</dt><dd>{{ activeCite.issuer || '—' }}</dd></div>
              <div class="flex gap-2"><dt class="w-[64px] shrink-0 text-[#98A2B3]">发布日期</dt><dd>{{ activeCite.publish_date || '—' }}</dd></div>
              <div class="flex gap-2"><dt class="w-[64px] shrink-0 text-[#98A2B3]">生效日期</dt><dd>{{ activeCite.effective_date || '—' }}</dd></div>
              <div class="flex gap-2"><dt class="w-[64px] shrink-0 text-[#98A2B3]">失效日期</dt><dd>{{ activeCite.expire_date || '—' }}</dd></div>
              <div class="flex gap-2"><dt class="w-[64px] shrink-0 text-[#98A2B3]">状态</dt>
                <dd><span :class="['gov-status', statusClass(activeCite.status)]">{{ activeCite.status }}</span></dd>
              </div>
              <div class="flex gap-2"><dt class="w-[64px] shrink-0 text-[#98A2B3]">位置</dt><dd>第 {{ activeCite.page }} 页 · {{ activeCite.clause_no }}</dd></div>
            </dl>

            <p class="mt-4 text-[12px] font-semibold text-[#667085]">条款原文</p>
            <p class="gov-origin mt-1">
              {{ activeCite.excerpt.pre }}<mark>{{ activeCite.excerpt.hl }}</mark>{{ activeCite.excerpt.post }}
            </p>

            <div class="mt-5 flex flex-wrap gap-2">
              <button type="button" class="gov-ghost" @click="toDraftFromCite">加入起草依据</button>
              <a v-if="usableSource(activeCite.source_url)" :href="activeCite.source_url"
                 target="_blank" rel="noreferrer" class="gov-ghost">查看来源</a>
              <span v-else class="self-center text-[11.5px] text-[#A8B2C1]">未登记可访问的来源链接</span>
            </div>
          </div>
        </aside>
      </transition>
    </div>
  </main>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertTriangle, BookMarked, Copy, FileSignature, Loader2, Plus, Send, Upload, X,
} from 'lucide-vue-next'
import AppHeader from '../components/AppHeader.vue'
import api from '../api.js'
import { getSessionToken } from '../stores/auth.js'

const router = useRouter()

const docs = ref([])
const stats = ref({})
const showUpload = ref(false)
const uploading = ref(false)
const mode = ref('file')
const pasteText = ref('')
const notice = ref(null)
const file = ref(null)
const fileInput = ref(null)
const meta = reactive({ title: '', doc_no: '', issuer: '', effective_date: '', expire_date: '' })

const scope = ref('current')
const excludeDeprecated = ref(true)
const question = ref('')
const asking = ref(false)
const elapsed = ref(0)
const turns = ref([])
const turnSeq = ref(0)
const activeCite = ref(null)
const focusPolicy = ref(null)
const scroller = ref(null)
let timer = null

const statusStyle = {
  现行有效: 'gov-status--ok',
  已废止: 'gov-status--bad',
  已修订: 'gov-status--warn',
  待核实: 'gov-status--warn',
  尚未生效: 'gov-status--info',
}

//: 演示/占位域名，点开必然 404，不如不显示
const PLACEHOLDER_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', 'example.com', 'example.org',
  'example.net', 'example.gov.cn', 'test.gov.cn', 'demo.gov.cn']

function usableSource(url) {
  const raw = (url || '').trim()
  if (!/^https?:\/\//i.test(raw)) return false
  try {
    const host = new URL(raw).hostname.toLowerCase()
    if (!host.includes('.')) return false
    return !(PLACEHOLDER_HOSTS.includes(host) || host.startsWith('example.') || host.endsWith('.example.com'))
  } catch {
    return false
  }
}

function statusClass(status) {
  return statusStyle[status] || 'gov-status--info'
}

function sourceLabel(by) {
  if (by === 'llm') return '本地模型生成'
  if (by === 'extractive') return '原文摘录（未采用模型表述）'
  if (by === 'extractive_after_error') return '原文摘录（模型不可用）'
  if (by === 'extractive_numeric') return '原文摘录（数值直引原文）'
  if (by === 'extractive_ungrounded') return '原文摘录（模型数值无法核对）'
  return '未生成'
}

// 把「…[1]…」切成 文本/引用 片段，便于渲染成可点击标签
function segments(text) {
  const out = []
  // 小模型常带 markdown 强调符，正文里直接显示 ** 很难看，先清掉
  const clean = (text || '').replace(/\*\*/g, '').replace(/^#{1,6}\s*/gm, '')
  const re = /\[(\d+)\]/g
  let last = 0
  let m
  while ((m = re.exec(clean)) !== null) {
    if (m.index > last) out.push({ text: clean.slice(last, m.index) })
    out.push({ cite: Number(m[1]) })
    last = m.index + m[0].length
  }
  if (last < clean.length) out.push({ text: clean.slice(last) })
  return out
}

function onFileChange(e) {
  const f = e.target.files?.[0]
  file.value = f || null
  const base = f ? f.name.replace(/\.[^.]+$/, '') : ''
  // 哈希命名（如 3d2b1f1a32a2488bbe856ce7058538a5）不是政策标题，交给后端从原文首部提取
  if (f && !meta.title && /[\u4e00-\u9fa5]/.test(base)) meta.title = base
}

async function loadDocs() {
  try {
    const [{ data: list }, { data: st }] = await Promise.all([
      api.get('/policy/documents', { params: { limit: 100 } }),
      api.get('/policy/stats'),
    ])
    docs.value = list.data.items || []
    stats.value = st.data || {}
  } catch {
    /* 未登录或服务未就绪时不打断页面 */
  }
}

function showError(prefix, err) {
  const res = err?.response?.data
  const detail = res?.data
  let text = `${prefix}：${res?.message || err.message || '未知错误'}`
  if (detail?.preview) {
    text += `\n识别到的开头：${detail.preview}`
  }
  notice.value = { type: 'error', text }
}

function resetForm() {
  file.value = null
  pasteText.value = ''
  Object.keys(meta).forEach((k) => { meta[k] = '' })
}

async function submit() {
  if (mode.value === 'text') return uploadText()
  return upload()
}

async function uploadText() {
  const text = pasteText.value.trim()
  if (!text || uploading.value) return
  uploading.value = true
  notice.value = null
  try {
    const { data } = await api.post('/policy/documents/text', { ...meta, text })
    if (data?.code !== 0) {
      notice.value = { type: 'error', text: `入库失败：${data?.message || '未知错误'}` }
      return
    }
    const body = data.data || {}
    await loadDocs()
    resetForm()
    showUpload.value = false
    notice.value = {
      type: 'ok',
      text: `已入库：《${body.document?.title || ''}》，切分 ${body.document?.clause_count || 0} 条`
        + ((body.parse_warnings || []).length ? `\n提示：${body.parse_warnings.join('；')}` : ''),
    }
  } catch (err) {
    showError('入库失败', err)
  } finally {
    uploading.value = false
  }
}

async function upload() {
  if (!file.value || uploading.value) return
  uploading.value = true
  notice.value = null
  try {
    const form = new FormData()
    form.append('file', file.value)
    Object.entries(meta).forEach(([k, v]) => form.append(k, v ?? ''))
    const { data } = await api.post('/policy/documents', form)
    // 业务错误码走的是 HTTP 200，必须显式判断，否则失败会被当成成功
    if (data?.code !== 0) {
      notice.value = { type: 'error', text: `上传失败：${data?.message || '未知错误'}` }
      return
    }
    const body = data.data || {}
    await loadDocs()
    resetForm()
    showUpload.value = false
    const tip = [`已入库：《${body.document?.title || ''}》，切分 ${body.document?.clause_count || 0} 条`]
    if (body.ocr_used) tip.push('该文件无文字层，已用 OCR 识别，请核对条款编号与数字')
    if ((body.parse_warnings || []).length) tip.push('解析提示：' + body.parse_warnings.join('；'))
    const issues = body.lifecycle_issues || []
    if (issues.length) tip.push('元数据体检：' + issues.map((i) => i.message).join('；'))
    notice.value = { type: 'ok', text: tip.join('\n') }
  } catch (err) {
    showError('上传失败', err)
  } finally {
    uploading.value = false
  }
}

function nearBottom() {
  const el = scroller.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 120
}

function applyStreamEvent(rawChunk, turn) {
  for (const line of rawChunk.split('\n')) {
    if (!line.startsWith('data:')) continue
    const body = line.slice(5).trim()
    if (!body || body === '[DONE]') continue
    let ev
    try {
      ev = JSON.parse(body)
    } catch {
      continue
    }
    if (ev.type === 'stage') {
      turn.stage = ev.text || ''
    } else if (ev.type === 'evidence') {
      // 先拿到依据，边生成边展示引用卡
      turn.data = {
        status: 'answered',
        sufficient: true,
        sufficiency: 'partial',
        conclusion: '',
        supplement: '',
        reason: '',
        manual_confirm: [],
        citations: ev.citations || [],
        candidates: [],
        meta: { ...(ev.meta || {}), cited: (ev.citations || []).length, generated_by: 'stream' },
      }
    } else if (ev.type === 'delta') {
      if (turn.data) turn.data.conclusion = (turn.data.conclusion || '') + (ev.text || '')
    } else if (ev.type === 'replace') {
      if (turn.data) turn.data.conclusion = ev.text || ''
    } else if (ev.type === 'final') {
      turn.data = ev.data
    } else if (ev.type === 'error') {
      turn.error = ev.message || '生成失败'
    }
  }
}

async function ask() {
  const q = question.value.trim()
  if (!q || asking.value) return
  asking.value = true
  activeCite.value = null
  elapsed.value = 0
  timer = setInterval(() => { elapsed.value += 1 }, 1000)

  const turn = reactive({
    id: ++turnSeq.value,
    question: q,
    data: null,
    streaming: true,
    stage: '正在检索政策库',
    error: '',
  })
  turns.value.push(turn)
  question.value = ''
  scrollToBottom()

  const payload = {
    question: q,
    scope: scope.value === 'policy' && focusPolicy.value ? 'policy' : scope.value,
    include_deprecated: !excludeDeprecated.value,
    policy_ids: focusPolicy.value ? [focusPolicy.value] : undefined,
  }

  try {
    const resp = await fetch('/api/v1/policy/qa/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + getSessionToken(),
      },
      body: JSON.stringify(payload),
    })

    if (!resp.ok || !resp.body) {
      let msg = `HTTP ${resp.status}`
      try {
        const j = await resp.json()
        msg = j?.message || msg
      } catch { /* 保留状态码 */ }
      throw new Error(msg)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let cut = buffer.indexOf('\n\n')
      while (cut >= 0) {
        applyStreamEvent(buffer.slice(0, cut), turn)
        buffer = buffer.slice(cut + 2)
        cut = buffer.indexOf('\n\n')
      }
      if (nearBottom()) scrollToBottom()
    }
    if (buffer.trim()) applyStreamEvent(buffer, turn)
  } catch (err) {
    turn.error = err?.message || '网络异常，请确认后端服务在运行'
  } finally {
    turn.streaming = false
    clearInterval(timer)
    timer = null
    asking.value = false
    scrollToBottom()
  }
}

function openCite(idx, citations) {
  const target = (citations || []).find((c) => c.index === idx)
  if (target) activeCite.value = target
}

function scrollToBottom() {
  nextTick(() => {
    const el = scroller.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function removeTurn(index) {
  const removed = turns.value[index]
  turns.value.splice(index, 1)
  if (removed && activeCite.value) {
    const stillUsed = turns.value.some((t) =>
      (t.data.citations || []).some((c) => c.clause_id === activeCite.value.clause_id))
    if (!stillUsed) activeCite.value = null
  }
}

function clearTurns() {
  turns.value = []
  activeCite.value = null
}

async function copyAnswer(turn) {
  const text = turn?.data?.conclusion || ''
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    window.alert('复制失败，请手动选择文本')
  }
}

function toDraftFromCite() {
  const c = activeCite.value
  if (!c) return
  sessionStorage.setItem('mqw-gongwen-references', JSON.stringify([{
    policy_title: c.policy_title,
    doc_no: c.doc_no,
    clause_no: c.clause_no,
    content: c.excerpt?.hl || c.content,
  }]))
  router.push('/gongwen')
}

function toDraft(turn) {
  const cites = turn?.data?.citations || []
  const refs = cites.map((c) => ({
    policy_title: c.policy_title,
    doc_no: c.doc_no,
    clause_no: c.clause_no,
    content: c.excerpt?.hl || c.content,
  }))
  sessionStorage.setItem('mqw-gongwen-references', JSON.stringify(refs))
  router.push('/gongwen')
}

onMounted(() => {
  loadDocs()
  // 支持从其他页面带入上一次问答结果（例如从审核中心回看）
  try {
    const raw = sessionStorage.getItem('mqw-policy-answer')
    if (raw) {
      sessionStorage.removeItem('mqw-policy-answer')
      const payload = JSON.parse(raw)
      const items = Array.isArray(payload) ? payload : (payload?.status ? [payload] : [])
      if (items.length) {
        turns.value = items.map((item, i) => ({
          id: ++turnSeq.value,
          question: item.question || item.__question || `历史问答 ${i + 1}`,
          data: item,
        }))
        scrollToBottom()
      }
    }
  } catch {
    /* 忽略损坏的缓存 */
  }
})
</script>

<style scoped>
.gov-icon-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 26px; height: 26px; border-radius: 7px; border: 1px solid #E4E7EC;
  background: #fff; color: #667085;
}
.gov-icon-btn:hover { background: #F8FAFC; }

.gov-upload {
  display: flex; width: 100%; align-items: center; gap: 6px;
  border-radius: 8px; border: 1px dashed #C7D7E8; background: #fff;
  padding: 8px 10px; font-size: 12.5px; color: #475467;
  overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
}
.gov-upload:hover { border-color: #8FB3DB; }

.gov-input {
  width: 100%; border-radius: 8px; border: 1px solid #E4E7EC; background: #fff;
  padding: 6px 9px; font-size: 12.5px; line-height: 1.6; color: #111827; outline: none;
}
.gov-input:focus { border-color: #8FB3DB; box-shadow: 0 0 0 3px rgba(37, 99, 168, .1); }

.gov-textarea {
  resize: vertical; max-height: 220px; min-height: 96px;
  font-family: inherit; line-height: 1.7;
}

.gov-tab {
  flex: 1; border-radius: 6px; padding: 4px 0;
  font-size: 12px; font-weight: 500; color: #667085;
  transition: background .15s, color .15s;
}
.gov-tab--on { background: #fff; color: #173F6B; box-shadow: 0 1px 2px rgba(16, 24, 40, .08); }

.gov-primary {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  height: 34px; border-radius: 8px; background: #173F6B; color: #fff;
  font-size: 13px; font-weight: 600;
}
.gov-primary:disabled { opacity: .45; cursor: not-allowed; }

.gov-doc {
  display: block; width: 100%; text-align: left; padding: 9px 14px;
  border-bottom: 1px solid #F4F6F9; background: transparent;
}
.gov-doc:hover { background: #F8FBFF; }
.gov-doc--on { background: #F1F7FE; box-shadow: inset 3px 0 0 #2563A8; }

.gov-status {
  flex-shrink: 0; border-radius: 4px; padding: 0 5px;
  font-size: 10.5px; font-weight: 600; line-height: 16px;
}
.gov-status--ok { background: #E8F1EC; color: #2C6B4F; }
.gov-status--bad { background: #FBEEEC; color: #A8322D; }
.gov-status--warn { background: #FDF3E2; color: #9A6A13; }
.gov-status--info { background: #EEF2F7; color: #667085; }

.gov-select {
  height: 28px; border-radius: 7px; border: 1px solid #E4E7EC; background: #fff;
  padding: 0 6px; font-size: 12px; color: #475467; outline: none;
}
.gov-check {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 12px; color: #667085; white-space: nowrap;
}

.gov-turn {
  border-radius: 12px;
  border: 1px solid #E4EBF4;
  background: #fff;
  padding: 12px 14px 13px;
  margin-bottom: 12px;
}

.gov-q {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding-bottom: 9px;
  margin-bottom: 10px;
  border-bottom: 1px dashed #EDF1F7;
}

.gov-q-index {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 20px; height: 20px; border-radius: 6px;
  background: #EAF2FB; color: #1D4E89;
  font-size: 11px; font-weight: 700;
  margin-top: 2px;
}

.gov-q-del { color: #C7CFDB; padding: 2px; transition: color .15s; }
.gov-q-del:hover { color: #A8322D; }

.gov-cursor {
  display: inline-block;
  width: 7px; height: 15px;
  margin-left: 2px;
  vertical-align: -2px;
  background: #2563A8;
  animation: govBlink 1s step-end infinite;
}

@keyframes govBlink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.gov-loading {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  border-radius: 10px; border: 1px dashed #C7D7E8; background: #fff;
  padding: 12px; margin-bottom: 12px;
  font-size: 13px; color: #475467;
}

.gov-answer,
.gov-nobasis {
  max-width: 760px; margin: 0 auto; border-radius: 12px; border: 1px solid #E4EAF2;
  background: #fff; padding: 16px 18px; box-shadow: 0 2px 10px rgba(23, 63, 107, .05);
}
.gov-nobasis { border-color: #F0DCAE; background: #FFFCF5; }

.gov-badge {
  border-radius: 6px; padding: 1px 8px; font-size: 11.5px; font-weight: 600;
}
.gov-badge--ok { background: #E8F1EC; color: #2C6B4F; }
.gov-badge--warn { background: #FDF3E2; color: #9A6A13; }

.gov-conclusion {
  font-size: 14.5px; line-height: 1.9; color: #1F2A37; white-space: pre-wrap;
}

.gov-cite {
  display: inline-block; margin: 0 1px; padding: 0 4px;
  border-radius: 4px; background: #EAF2FB; color: #1D4E89;
  font-size: 12px; font-weight: 700; vertical-align: 1px;
}
.gov-cite:hover { background: #D7E7F8; }

.gov-supplement {
  margin-top: 10px; padding: 8px 10px; border-radius: 8px;
  background: #F8FAFC; font-size: 12.5px; line-height: 1.8; color: #475467;
}

.gov-manual {
  margin-top: 8px; padding: 8px 10px 8px 24px; border-radius: 8px;
  background: #FDF3E2; font-size: 12.5px; line-height: 1.8; color: #7A4E10;
  list-style: disc;
}

.gov-cite-card {
  display: block; width: 100%; text-align: left; border-radius: 9px;
  border: 1px solid #E9EEF5; background: #fff; padding: 9px 11px;
}
.gov-cite-card:hover { border-color: #B9D0E8; background: #FBFDFF; }

.gov-cite-no {
  flex-shrink: 0; border-radius: 4px; background: #EAF2FB; color: #1D4E89;
  padding: 0 5px; font-size: 11px; font-weight: 700;
}

.gov-cand {
  display: flex; align-items: center; gap: 8px; border-radius: 7px;
  background: #fff; border: 1px solid #F0E6D2; padding: 6px 10px;
  font-size: 12px; color: #6B5A3E;
}

.gov-ghost {
  display: inline-flex; align-items: center; gap: 5px;
  height: 30px; padding: 0 11px; border-radius: 8px;
  border: 1px solid #E4E7EC; background: #fff;
  font-size: 12.5px; color: #344054;
}
.gov-ghost:hover { background: #F8FAFC; }

.gov-composer-input {
  flex: 1; resize: none; border-radius: 10px; border: 1px solid #E4E7EC;
  background: #fff; padding: 8px 11px; font-size: 13.5px; line-height: 1.7;
  color: #111827; outline: none;
}
.gov-composer-input:focus { border-color: #8FB3DB; box-shadow: 0 0 0 3px rgba(37, 99, 168, .1); }

.gov-send {
  display: inline-flex; height: 40px; width: 44px; align-items: center; justify-content: center;
  border-radius: 10px; background: #173F6B; color: #fff;
}
.gov-send:disabled { opacity: .4; cursor: not-allowed; }

.gov-origin {
  border-radius: 8px; background: #F8FAFC; padding: 10px 12px;
  font-size: 12.5px; line-height: 1.9; color: #344054;
}
.gov-origin mark { background: #FFF1B8; color: #7A4E10; padding: 0 1px; }

.slide-enter-active, .slide-leave-active { transition: all .18s ease; }
.slide-enter-from, .slide-leave-to { opacity: 0; transform: translateX(12px); }
</style>
