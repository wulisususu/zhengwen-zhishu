<template>
  <main class="flex h-dvh flex-col overflow-hidden bg-[#eef3f9] text-black">
    <AppHeader title="" subtitle="政务办公智能体" :show-logout="false" @goHome="router.push('/')" />

    <div class="flex min-h-0 flex-1 gap-3 p-3">
      <!-- ============ 左：起草表单 ============ -->
      <aside class="hidden w-[358px] shrink-0 flex-col overflow-y-auto rounded-[12px] border border-[#dce6f1] bg-white p-4 md:flex">
        <div class="mb-3">
          <h1 class="text-[17px] font-semibold text-[#111827]">公文起草</h1>
          <p class="mt-1 text-[12.5px] leading-5 text-[#98A2B3]">
            填写要素后由端侧模型生成正文，按 GB/T 9704 版式成文
          </p>
        </div>

        <div class="gov-field">
          <label class="gov-label">文种</label>
          <div class="flex flex-wrap gap-1.5">
            <button v-for="t in docTypes" :key="t" type="button"
              :class="['gov-chip', form.doc_type === t ? 'gov-chip--on' : '']"
              @click="form.doc_type = t">{{ t }}</button>
          </div>
        </div>

        <div class="gov-field">
          <label class="gov-label">事由 <span class="text-[#a8322d]">*</span></label>
          <textarea v-model="form.subject" rows="2" class="gov-input"
            placeholder="如：加强政务服务中心窗口作风建设" />
          <p class="gov-hint">「关于」「的{{ form.doc_type }}」由系统补全，不必手写</p>
        </div>

        <div class="gov-field">
          <label class="gov-label">主送机关</label>
          <input v-model="form.recipients" class="gov-input" placeholder="各县（市、区）政务服务管理局" />
          <p v-if="form.doc_type === '请示'" class="gov-hint gov-hint--warn">请示只能主送一个机关</p>
        </div>

        <div class="gov-field">
          <label class="gov-label">发文机关</label>
          <input v-model="form.issuer_org" class="gov-input" placeholder="XX市政务服务管理局" />
        </div>

        <div class="grid grid-cols-2 gap-2">
          <div class="gov-field">
            <label class="gov-label">成文日期</label>
            <input v-model="form.sign_date" class="gov-input" placeholder="2026年10月24日" />
          </div>
          <div class="gov-field">
            <label class="gov-label">紧急程度</label>
            <select v-model="form.urgency" class="gov-input">
              <option value="">普通</option>
              <option value="急件">急件</option>
              <option value="特急">特急</option>
            </select>
          </div>
        </div>

        <div class="gov-field">
          <label class="gov-label">发文字号</label>
          <input v-model="form.doc_number" class="gov-input" placeholder="X政服发〔2026〕12号" />
        </div>

        <div class="gov-field">
          <label class="gov-label">抄送机关</label>
          <input v-model="form.cc" class="gov-input" placeholder="市委办公室、市政府办公室" />
        </div>

        <div class="gov-field">
          <label class="gov-label">补充要求</label>
          <textarea v-model="form.extra" rows="2" class="gov-input"
            placeholder="如：突出考核问责，字数控制在一页内" />
        </div>

        <div v-if="references.length" class="mb-3 rounded-[10px] border border-[#DCE7F4] bg-[#F6FAFF] p-2.5">
          <div class="mb-1.5 flex items-center gap-1.5">
            <BookMarked class="size-3.5 text-[#2563A8]" :stroke-width="2" />
            <span class="text-[12px] font-semibold text-[#344054]">起草依据 {{ references.length }} 条</span>
            <button type="button" class="ml-auto text-[11.5px] text-[#98A2B3] hover:text-[#475467]"
              @click="references = []">清空</button>
          </div>
          <div class="space-y-1">
            <div v-for="(r, i) in references" :key="i" class="flex items-start gap-1.5">
              <span class="mt-[3px] shrink-0 rounded bg-[#EAF2FB] px-1 text-[10.5px] font-bold text-[#1D4E89]">{{ i + 1 }}</span>
              <span class="line-clamp-2 flex-1 text-[11.5px] leading-4 text-[#667085]">
                《{{ r.policy_title }}》{{ r.clause_no }}：{{ r.content }}
              </span>
              <button type="button" class="mt-[1px] shrink-0 text-[#C7CFDB] hover:text-[#A8322D]"
                @click="references.splice(i, 1)">
                <X class="size-3" :stroke-width="2" />
              </button>
            </div>
          </div>
        </div>

        <button type="button" class="gov-submit" :disabled="loading || !form.subject.trim()" @click="generate">
          <Loader2 v-if="loading" class="size-4 animate-spin" :stroke-width="2" />
          <Sparkles v-else class="size-4" :stroke-width="2" />
          {{ loading ? `生成中 ${elapsed}s` : (result ? '重新生成' : '生成正文') }}
        </button>
        <p class="mt-2 text-center text-[11.5px] leading-4 text-[#A8B2C1]">
          端侧推理，正文不出设备
        </p>
      </aside>

      <!-- ============ 右：成文预览 ============ -->
      <section class="flex min-w-0 flex-1 flex-col overflow-hidden rounded-[12px] border border-[#dce6f1] bg-white">
        <div class="flex flex-wrap items-center gap-2 border-b border-[#E6EAF2] px-4 py-2.5">
          <span class="text-[13.5px] font-semibold text-[#344054]">成文预览</span>
          <span v-if="result" class="gov-tag" :class="result.meta.generated_by === 'template' ? 'gov-tag--warn' : 'gov-tag--ok'">
            {{ sourceLabel }}
          </span>
          <span v-if="result" class="text-[12px] text-[#98A2B3]">
            {{ result.summary.char_count }} 字 · 用时 {{ (result.meta.elapsed_ms / 1000).toFixed(1) }}s
          </span>
          <button type="button" class="gov-ghost ml-auto" :disabled="!result || exporting" @click="exportDocx">
            <Download class="size-4" :stroke-width="2" />
            {{ exporting ? '导出中…' : '导出 DOCX' }}
          </button>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto bg-[#f6f8fb] p-4">
          <!-- 空态 -->
          <div v-if="!result && !loading" class="flex h-full flex-col items-center justify-center text-center">
            <FileSignature class="size-10 text-[#C7CFDB]" :stroke-width="1.4" />
            <p class="mt-3 text-[14px] text-[#667085]">填写左侧要素后生成正文</p>
            <p class="mt-1 text-[12.5px] text-[#98A2B3]">生成结果可直接导出为符合公文格式的 Word</p>
          </div>

          <div v-else-if="loading" class="flex h-full flex-col items-center justify-center">
            <Loader2 class="size-8 animate-spin text-[#2563A8]" :stroke-width="1.6" />
            <p class="mt-3 text-[13.5px] text-[#475467]">模型正在成文，已等待 {{ elapsed }} 秒</p>
            <p class="mt-1 text-[12px] text-[#98A2B3]">端侧 NPU 推理，通常 15–30 秒</p>
          </div>

          <!-- A4 纸张预览 -->
          <div v-else class="gov-paper mx-auto">
            <template v-if="ir.issuer_org">
              <p class="gov-paper-red">{{ ir.issuer_org }}{{ ir.doc_type === '纪要' ? '纪要' : '文件' }}</p>
              <p class="gov-paper-no">{{ ir.doc_number || '　' }}</p>
              <div class="gov-paper-line"></div>
            </template>
            <h2 class="gov-paper-title">{{ ir.title }}</h2>
            <p v-if="ir.recipients && ir.recipients.length" class="gov-paper-to">
              {{ ir.recipients.join('、') }}：
            </p>
            <p v-for="(p, i) in ir.body" :key="i" :class="paraClass(p)">
              {{ p.text }}
            </p>
            <p v-if="ir.signer_org" class="gov-paper-signer">{{ ir.signer_org }}</p>
            <p v-if="ir.sign_date" class="gov-paper-date">{{ ir.sign_date }}</p>
          </div>
        </div>

        <!-- 校核结果 -->
        <div v-if="result && issues.length" class="max-h-[168px] shrink-0 overflow-y-auto border-t border-[#E6EAF2] px-4 py-3">
          <div class="mb-1.5 flex items-center gap-2">
            <span class="text-[13px] font-semibold text-[#344054]">公文校核</span>
            <span class="text-[12px] text-[#98A2B3]">
              错误 {{ result.stats.error }} · 提示 {{ result.stats.warn }} · 建议 {{ result.stats.info }}
            </span>
          </div>
          <ul class="space-y-1">
            <li v-for="(it, i) in issues" :key="i" class="flex items-start gap-2 text-[12.5px] leading-5">
              <component :is="issueIcon(it.level)" :class="['mt-[3px] size-3.5 shrink-0', issueColor(it.level)]" :stroke-width="2" />
              <span class="text-[#475467]">
                {{ it.message }}
                <span v-if="it.hint" class="text-[#98A2B3]">—— {{ it.hint }}</span>
              </span>
            </li>
          </ul>
        </div>
      </section>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertTriangle, BookMarked, CheckCircle2, Download, FileSignature, Info,
  Loader2, Sparkles, X, XCircle,
} from 'lucide-vue-next'
import AppHeader from '../components/AppHeader.vue'
import api from '../api.js'

const router = useRouter()

const docTypes = ['通知', '请示', '报告', '函', '纪要']
const today = new Date()
const defaultDate = `${today.getFullYear()}年${today.getMonth() + 1}月${today.getDate()}日`

const form = reactive({
  doc_type: '通知',
  subject: '',
  recipients: '',
  issuer_org: '',
  sign_date: defaultDate,
  urgency: '',
  doc_number: '',
  cc: '',
  extra: '',
})

const loading = ref(false)
const exporting = ref(false)
const elapsed = ref(0)
const result = ref(null)
const references = ref([])
let timer = null

const ir = computed(() => result.value?.ir || {})
const issues = computed(() => result.value?.issues || [])

const sourceLabel = computed(() => {
  const by = result.value?.meta?.generated_by
  if (by === 'template') return '骨架稿 · 需补充'
  if (by === 'llm_repaired') return '模型生成（含补写）'
  return '模型生成'
})

function paraClass(p) {
  if (p.level === 1) return 'gov-paper-h1'
  if (p.level === 2) return 'gov-paper-h2'
  if (p.level === 3) return 'gov-paper-h3'
  return 'gov-paper-p'
}

function issueIcon(level) {
  if (level === 'error') return XCircle
  if (level === 'warn') return AlertTriangle
  if (level === 'ok') return CheckCircle2
  return Info
}

function issueColor(level) {
  if (level === 'error') return 'text-[#c0392b]'
  if (level === 'warn') return 'text-[#B7791F]'
  if (level === 'ok') return 'text-[#2C6B4F]'
  return 'text-[#98A2B3]'
}

function splitList(value) {
  return String(value || '')
    .split(/[、,，;；\n]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

async function generate() {
  if (!form.subject.trim() || loading.value) return
  loading.value = true
  result.value = null
  elapsed.value = 0
  timer = setInterval(() => { elapsed.value += 1 }, 1000)
  try {
    const { data } = await api.post('/gongwen/draft', {
      doc_type: form.doc_type,
      subject: form.subject.trim(),
      recipients: splitList(form.recipients),
      issuer_org: form.issuer_org.trim(),
      sign_date: form.sign_date.trim(),
      urgency: form.urgency,
      doc_number: form.doc_number.trim(),
      cc: splitList(form.cc),
      extra: form.extra.trim(),
      references: references.value,
    })
    result.value = data.data
  } catch (err) {
    result.value = null
    window.alert(err?.response?.data?.message || err.message || '生成失败')
  } finally {
    clearInterval(timer)
    timer = null
    loading.value = false
  }
}

async function exportDocx() {
  if (!result.value || exporting.value) return
  exporting.value = true
  try {
    const res = await api.post('/gongwen/render', { ir: result.value.ir }, { responseType: 'blob' })
    const encoded = res.headers['x-filename'] || ''
    const filename = encoded
      ? decodeURIComponent(encoded)
      : `${ir.value.title || ir.value.doc_type}_${Date.now()}.docx`
    const url = URL.createObjectURL(new Blob([res.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch (err) {
    window.alert('导出失败：' + (err.message || '未知错误'))
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  // 政策解读页「加入起草依据」带过来的条款
  try {
    const rawRefs = sessionStorage.getItem('mqw-gongwen-references')
    if (rawRefs) {
      sessionStorage.removeItem('mqw-gongwen-references')
      const parsedRefs = JSON.parse(rawRefs)
      if (Array.isArray(parsedRefs)) references.value = parsedRefs.slice(0, 6)
    }
  } catch {
    /* 忽略损坏的依据缓存 */
  }

  // 允许从其他模块带着已生成结果进入（避免重复生成）
  try {
    const raw = sessionStorage.getItem('mqw-gongwen-result')
    if (raw) {
      sessionStorage.removeItem('mqw-gongwen-result')
      const payload = JSON.parse(raw)
      if (payload?.ir) {
        result.value = payload
        Object.assign(form, {
          doc_type: payload.ir.doc_type || form.doc_type,
          subject: form.subject,
          recipients: (payload.ir.recipients || []).join('、'),
          issuer_org: payload.ir.issuer_org || '',
          sign_date: payload.ir.sign_date || form.sign_date,
          doc_number: payload.ir.doc_number || '',
          cc: (payload.ir.cc || []).join('、'),
        })
      }
    }
  } catch {
    /* 忽略损坏的缓存 */
  }
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.gov-field {
  margin-bottom: 11px;
}

.gov-label {
  display: block;
  margin-bottom: 4px;
  font-size: 12.5px;
  font-weight: 600;
  color: #475467;
}

.gov-input {
  width: 100%;
  border-radius: 9px;
  border: 1px solid #E4E7EC;
  background: #fff;
  padding: 7px 10px;
  font-size: 13px;
  line-height: 1.6;
  color: #111827;
  outline: none;
  resize: none;
}

.gov-input:focus {
  border-color: #8FB3DB;
  box-shadow: 0 0 0 3px rgba(37, 99, 168, 0.1);
}

.gov-hint {
  margin-top: 3px;
  font-size: 11.5px;
  line-height: 1.5;
  color: #A8B2C1;
}

.gov-hint--warn {
  color: #B7791F;
}

.gov-chip {
  border-radius: 8px;
  border: 1px solid #E4E7EC;
  background: #fff;
  padding: 5px 12px;
  font-size: 13px;
  color: #475467;
  transition: all 0.15s ease;
}

.gov-chip:hover {
  border-color: #BFD3E7;
}

.gov-chip--on {
  border-color: #173F6B;
  background: #173F6B;
  color: #fff;
  font-weight: 600;
}

.gov-submit {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  gap: 7px;
  height: 42px;
  margin-top: 4px;
  border-radius: 10px;
  background: #173F6B;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  transition: background 0.15s ease;
}

.gov-submit:hover:not(:disabled) {
  background: #1E5288;
}

.gov-submit:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.gov-tag {
  border-radius: 6px;
  padding: 1px 8px;
  font-size: 11.5px;
  font-weight: 600;
}

.gov-tag--ok {
  background: #E8F1EC;
  color: #2C6B4F;
}

.gov-tag--warn {
  background: #FDF3E2;
  color: #9A6A13;
}

.gov-ghost {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 13px;
  border-radius: 9px;
  border: 1px solid #E4E7EC;
  background: #fff;
  font-size: 13px;
  font-weight: 500;
  color: #344054;
}

.gov-ghost:hover:not(:disabled) {
  background: #F8FAFC;
}

.gov-ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ---------------- A4 纸张 ---------------- */
.gov-paper {
  width: 100%;
  max-width: 720px;
  background: #fff;
  padding: 44px 52px 56px;
  border-radius: 3px;
  box-shadow: 0 2px 14px rgba(23, 63, 107, 0.08);
  font-family: 'FangSong', '仿宋', 'STFangsong', 'SimSun', serif;
  color: #111827;
}

.gov-paper-red {
  text-align: center;
  font-family: 'STZhongsong', 'SimSun', serif;
  font-size: 26px;
  font-weight: 700;
  letter-spacing: 2px;
  color: #E60000;
  margin: 0 0 10px;
}

.gov-paper-no {
  text-align: center;
  font-size: 15px;
  color: #111827;
  margin: 0 0 8px;
}

.gov-paper-line {
  height: 2px;
  background: #E60000;
  margin-bottom: 26px;
}

.gov-paper-title {
  text-align: center;
  font-family: 'STZhongsong', 'SimSun', serif;
  font-size: 21px;
  font-weight: 700;
  line-height: 1.6;
  margin: 0 0 20px;
}

.gov-paper-to {
  font-size: 15.5px;
  line-height: 2;
  margin: 0 0 2px;
}

.gov-paper-p {
  font-size: 15.5px;
  line-height: 2;
  text-indent: 2em;
  margin: 0;
  text-align: justify;
}

.gov-paper-h1 {
  font-family: 'SimHei', 'Heiti SC', sans-serif;
  font-size: 15.5px;
  line-height: 2;
  text-indent: 2em;
  margin: 0;
}

.gov-paper-h2 {
  font-family: 'KaiTi', 'Kaiti SC', serif;
  font-size: 15.5px;
  line-height: 2;
  text-indent: 2em;
  margin: 0;
}

.gov-paper-h3 {
  font-size: 15.5px;
  line-height: 2;
  text-indent: 2em;
  margin: 0;
}

.gov-paper-signer {
  margin-top: 28px;
  text-align: right;
  padding-right: 2em;
  font-size: 15.5px;
  line-height: 2;
}

.gov-paper-date {
  text-align: right;
  padding-right: 4em;
  font-size: 15.5px;
  line-height: 2;
}
</style>
