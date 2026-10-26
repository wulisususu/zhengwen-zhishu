<template>
  <main class="gov-home flex h-dvh flex-col overflow-hidden bg-white text-black">
    <div class="gov-home-bg" aria-hidden="true"></div>

    <AppHeader title="政务办公智能体" subtitle="端侧可信 · 数据不出域" @goHome="router.push('/')" @logout="router.push('/login')" />

    <section class="relative z-10 flex flex-1 flex-col items-center overflow-y-auto px-5 py-8 sm:justify-center sm:py-10">
      <div class="w-full max-w-[1080px]">

        <div class="mb-7">
          <div class="gov-badge">
            <span class="gov-badge-dot"></span>
            端侧本地推理 · 材料不出单位
          </div>
          <h1 class="mt-4 text-[30px] font-semibold leading-[40px] tracking-[-0.02em] text-[#111827] sm:text-[38px] sm:leading-[48px]">
            政务办公智能体
          </h1>
          <p class="mt-2.5 text-[16px] leading-7 text-[#475467] sm:text-[17px]">
            公文起草 · 政策解读 · 文稿撰写 · 提炼总结
          </p>
          <p class="mt-1.5 text-[13.5px] leading-6 text-[#98A2B3]">
            模型运行在本机 NPU，文本不出设备；每一次生成全程留痕，可核可溯。
          </p>
        </div>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <button v-for="item in businesses" :key="item.key" @click="goScene(item.key)" class="gov-card group">
            <span class="gov-card-icon">
              <component :is="item.icon" class="size-[19px] text-[#2563A8]" :stroke-width="2" />
            </span>
            <span class="min-w-0 flex-1">
              <span class="block text-[15px] font-semibold leading-6 text-[#111827]">{{ item.title }}</span>
              <span class="mt-1 block text-[12.5px] leading-[1.55] text-[#98A2B3]">{{ item.desc }}</span>
            </span>
            <ArrowRight class="gov-card-arrow size-4 shrink-0 text-[#C7CFDB]" :stroke-width="2" />
          </button>
        </div>

        <div class="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px] text-[#98A2B3]">
          <span class="font-medium text-[#667085]">另可直达</span>
          <button v-for="link in quickLinks" :key="link.path" @click="router.push(link.path)"
            class="transition-colors hover:text-[#2563A8]">{{ link.label }}</button>
        </div>

        <form @submit.prevent="submitRequest" class="gov-composer">
          <div class="flex flex-col gap-3 sm:flex-row">
            <label class="gov-select">
              <span class="shrink-0 text-[13.5px] leading-6 text-[#667085]">类型</span>
              <select v-model="requestType" class="h-full min-w-0 flex-1 appearance-none bg-transparent pr-6 text-[13.5px] leading-6 outline-none">
                <option value="word">公文 / 文稿</option>
                <option value="ppt">汇报 PPT</option>
              </select>
              <ChevronDown class="pointer-events-none absolute right-3 top-1/2 size-3.5 -translate-y-1/2 text-[#98A2B3]" :stroke-width="2" />
            </label>
            <textarea v-model="requestText" rows="2"
              placeholder="一句话说明需求，例如：以市政务服务管理局名义，起草一份关于加强窗口作风建设的通知"
              class="min-h-[76px] flex-1 resize-none rounded-[12px] border border-[#E4E7EC] bg-white px-3.5 py-2.5 text-[14.5px] leading-6 outline-none placeholder:text-[#98A2B3] focus:border-[#8FB3DB] focus:ring-4 focus:ring-[#2563A8]/10" />
          </div>
          <div class="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" class="gov-ghost-btn" @click="router.push('/chat?scene=summary')">
              <Upload class="size-4" :stroke-width="2" />上传文件提炼
            </button>
            <button type="submit" class="gov-primary-btn ml-auto">
              <Send class="size-4" :stroke-width="2" />开始起草
            </button>
          </div>
        </form>

        <p class="mt-3 text-[12.5px] leading-5 text-[#A8B2C1]">
          本系统输出为拟稿参考，须经核稿、签发流程后方可正式行文。
        </p>
      </div>
    </section>
  </main>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight, ChevronDown, Upload, Send,
  FileSignature, BookMarked, PenLine, ListChecks,
} from 'lucide-vue-next'
import AppHeader from '../components/AppHeader.vue'

const router = useRouter()
const requestType = ref('word')
const requestText = ref('')

const businesses = [
  { key: 'gongwen', title: '公文起草', desc: '通知·请示·报告·函·纪要', icon: FileSignature },
  { key: 'policy', title: '政策解读', desc: '条款级解读，逐句回溯原文', icon: BookMarked },
  { key: 'manuscript', title: '文稿撰写', desc: '讲话稿·汇报材料·工作总结', icon: PenLine },
  { key: 'summary', title: '提炼总结', desc: '纪要·调研·待办清单', icon: ListChecks },
]

const quickLinks = [
  { label: '通用对话', path: '/chat' },
  { label: '知识库', path: '/knowledge' },
  { label: '汇报演示', path: '/ppt' },
  { label: '智能体中心', path: '/agents' },
  { label: '系统设置', path: '/settings' },
]

// 四项政务业务的落点：公文/文稿进文档生成，政策解读进知识库，提炼总结进通用对话（可直接传附件）
const SCENE_ROUTE = {
  gongwen: '/gongwen',
  manuscript: '/document?scene=manuscript',
  policy: '/policy',
  summary: '/chat?scene=summary',
}

function goScene(key) {
  router.push(SCENE_ROUTE[key] || '/document')
}

function submitRequest() {
  const text = requestText.value.trim()
  if (text) {
    sessionStorage.setItem('mqw-pending-request', JSON.stringify({ type: requestType.value, text }))
  }
  if (requestType.value === 'ppt') router.push('/ppt')
  else router.push('/document')
}
</script>

<style scoped>
.gov-home {
  position: relative;
  isolation: isolate;
}

/* 纯 CSS 背景：无外部依赖，断网可用 */
.gov-home-bg {
  position: absolute;
  inset: 0;
  z-index: -1;
  background:
    radial-gradient(1200px 520px at 50% -120px, #E7F0FA 0%, rgba(231, 240, 250, 0) 70%),
    linear-gradient(180deg, #FAFCFF 0%, #F3F7FC 52%, #EEF3F9 100%);
}

.gov-home-bg::after {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(to right, rgba(23, 63, 107, 0.045) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(23, 63, 107, 0.045) 1px, transparent 1px);
  background-size: 56px 56px;
  mask-image: radial-gradient(ellipse 78% 62% at 50% 34%, #000 0%, transparent 78%);
  -webkit-mask-image: radial-gradient(ellipse 78% 62% at 50% 34%, #000 0%, transparent 78%);
}

.gov-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 11px 4px 9px;
  border-radius: 999px;
  border: 1px solid #D8E4F2;
  background: rgba(255, 255, 255, 0.78);
  font-size: 12.5px;
  font-weight: 600;
  color: #2563A8;
  letter-spacing: 0.01em;
}

.gov-badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #2C6B4F;
  box-shadow: 0 0 0 3px rgba(44, 107, 79, 0.14);
}

.gov-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px 15px;
  border-radius: 14px;
  border: 1px solid #E4EAF2;
  background: rgba(255, 255, 255, 0.9);
  text-align: left;
  box-shadow: 0 1px 3px rgba(16, 24, 40, 0.05);
  transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease;
}

.gov-card:hover {
  border-color: #B9D0E8;
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(23, 63, 107, 0.10);
}

.gov-card-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  border-radius: 10px;
  background: #EDF3FA;
  border: 1px solid #DCE7F4;
}

.gov-card-arrow {
  margin-top: 2px;
  transition: color .16s ease, transform .16s ease;
}

.gov-card:hover .gov-card-arrow {
  color: #2563A8;
  transform: translateX(2px);
}

.gov-composer {
  margin-top: 18px;
  padding: 16px;
  border-radius: 14px;
  border: 1px solid #E1E8F1;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 6px 20px rgba(23, 63, 107, 0.06);
}

.gov-select {
  position: relative;
  display: flex;
  height: 44px;
  align-items: center;
  gap: 8px;
  border-radius: 10px;
  border: 1px solid #E4E7EC;
  padding: 0 12px;
}

.gov-select:focus-within {
  border-color: #8FB3DB;
  box-shadow: 0 0 0 4px rgba(37, 99, 168, 0.10);
}

.gov-ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 38px;
  padding: 0 13px;
  border-radius: 10px;
  border: 1px solid #E4E7EC;
  background: #fff;
  font-size: 13.5px;
  font-weight: 500;
  color: #475467;
  transition: background .15s ease, border-color .15s ease;
}

.gov-ghost-btn:hover {
  background: #F8FAFC;
  border-color: #D0D5DD;
}

.gov-primary-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 38px;
  padding: 0 18px;
  border-radius: 10px;
  background: #173F6B;
  font-size: 13.5px;
  font-weight: 600;
  color: #fff;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.10);
  transition: background .15s ease;
}

.gov-primary-btn:hover {
  background: #1E5288;
}

@media (max-width: 640px) {
  .gov-composer {
    padding: 13px;
  }
}
</style>
