<template>
  <main class="agent-root flex h-dvh flex-col overflow-hidden text-black">
    <AppHeader title="" subtitle="政务办公智能体" :show-logout="false" @goHome="router.push('/')" />

    <div class="flex min-h-0 flex-1">
      <aside class="agent-sidebar hidden w-[220px] shrink-0 border-r border-[#E8E0D8] px-3 py-5 md:flex md:min-h-0 md:flex-col">
        <nav class="shrink-0 space-y-1">
          <button
            @click="router.push('/chat')"
            class="sidebar-item"
          >
            <MessageSquare class="size-[18px]" :stroke-width="1.8" />
            <span>通用对话</span>
          </button>
          <button
            @click="router.push('/document')"
            class="sidebar-item"
          >
            <FileText class="size-[18px]" :stroke-width="1.8" />
            <span>文档</span>
          </button>
          <button
            @click="router.push('/knowledge')"
            class="sidebar-item"
          >
            <BookMarked class="size-[18px]" :stroke-width="1.8" />
            <span>知识库</span>
          </button>
          <button
            type="button"
            class="sidebar-item sidebar-item--active"
          >
            <Bot class="size-[18px]" :stroke-width="1.8" />
            <span>智能体</span>
          </button>
        </nav>
      </aside>

      <section class="flex min-w-0 flex-1 flex-col">
        <div class="mobile-tabs flex items-center gap-1 border-b border-[#E8E0D8] px-3 py-2 md:hidden">
          <button @click="router.push('/chat')" class="mobile-tab">对话</button>
          <button @click="router.push('/knowledge')" class="mobile-tab">知识库</button>
          <button class="mobile-tab mobile-tab--active">智能体</button>
        </div>

        <div class="agent-canvas min-h-0 flex-1 overflow-y-auto">
          <div class="agent-hero">
            <div class="agent-hero-inner">
              <div class="agent-hero-badge">GOV AGENT HUB</div>
              <h1 class="agent-hero-title">政务智能体中心</h1>
              <p class="agent-hero-desc">四类政务办公任务，请求全程留痕；模型接入方式以系统配置为准</p>
            </div>
            <div class="agent-hero-deco" aria-hidden="true">
              <div class="deco-ring deco-ring--1"></div>
              <div class="deco-ring deco-ring--2"></div>
              <div class="deco-dot"></div>
            </div>
          </div>

          <div class="agent-body">
            <div class="agent-section-label">
              <span class="agent-section-line"></span>
              <span class="agent-section-text">政务业务智能体</span>
              <span class="agent-section-line"></span>
            </div>

            <div class="agent-grid">
              <button
                v-for="(agent, idx) in agents"
                :key="agent.id"
                class="agent-card"
                :style="{ animationDelay: (idx * 80) + 'ms' }"
                @click="openAgent(agent)"
              >
                <div class="agent-card-glow" :style="{ background: agent.glow }" aria-hidden="true"></div>
                <div class="agent-card-head">
                  <div class="agent-card-icon" :style="{ background: agent.bg }">
                    <component :is="agent.icon" class="size-[22px]" :style="{ color: agent.tagColor }" :stroke-width="1.7" />
                  </div>
                  <div class="agent-card-tag" :style="{ color: agent.tagColor, background: agent.tagBg }">
                    {{ agent.tag }}
                  </div>
                </div>
                <div class="agent-card-name">{{ agent.name }}</div>
                <div class="agent-card-desc">{{ agent.description }}</div>
                <div class="agent-card-footer">
                  <span class="agent-card-model">{{ agent.model }}</span>
                  <span class="agent-card-enter">
                    进入
                    <ArrowRight class="size-4" :stroke-width="2" />
                  </span>
                </div>
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  </main>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { ArrowRight, BookMarked, Bot, FileSignature, FileText, ListChecks, MessageSquare, PenLine } from 'lucide-vue-next'
import AppHeader from '../components/AppHeader.vue'

const router = useRouter()

const agents = [
  {
    id: 'gongwen-draft',
    name: '公文起草智能体',
    description: '承接通知、请示、报告、函、会议纪要五类文种，按机关行文规范成文，可直接导出 DOCX 继续核稿',
    icon: FileSignature,
    bg: 'linear-gradient(145deg, #E0EAFA 0%, #C7DAF2 100%)',
    glow: 'radial-gradient(circle at 30% 70%, rgba(37,99,168,0.12) 0%, transparent 70%)',
    tag: '核心业务',
    tagColor: '#173F6B',
    tagBg: '#E0EAFA',
    model: '模型以系统配置为准',
    route: '/gongwen',
  },
  {
    id: 'policy-interpret',
    name: '政策解读智能体',
    description: '上传政策原文，按条款逐条解读适用对象、办理条件、时限与材料，每句结论可回溯到原文条款',
    icon: BookMarked,
    bg: 'linear-gradient(145deg, #E6EEF8 0%, #D2E2F3 100%)',
    glow: 'radial-gradient(circle at 30% 70%, rgba(23,63,107,0.10) 0%, transparent 70%)',
    tag: '重点业务',
    tagColor: '#1E4E79',
    tagBg: '#E6EEF8',
    model: '模型以系统配置为准',
    route: '/policy',
  },
  {
    id: 'manuscript-write',
    name: '文稿撰写智能体',
    description: '领导讲话、汇报材料、工作总结，按场合与时长成文，遵循开场—形势—成绩—问题—部署—要求的结构',
    icon: PenLine,
    bg: 'linear-gradient(145deg, #EDEFF7 0%, #DCE1F0 100%)',
    glow: 'radial-gradient(circle at 30% 70%, rgba(79,91,213,0.10) 0%, transparent 70%)',
    tag: '常用',
    tagColor: '#3B4699',
    tagBg: '#EDEFF7',
    model: '模型以系统配置为准',
    route: '/document?scene=manuscript',
  },
  {
    id: 'summarize',
    name: '提炼总结智能体',
    description: '上传会议记录、调研报告或长文，提炼议题、决议、责任人与时限，输出纪要表格与待办清单',
    icon: ListChecks,
    bg: 'linear-gradient(145deg, #E8F1EC 0%, #D5E7DC 100%)',
    glow: 'radial-gradient(circle at 30% 70%, rgba(44,107,79,0.10) 0%, transparent 70%)',
    tag: '高频',
    tagColor: '#2C6B4F',
    tagBg: '#E8F1EC',
    model: '模型以系统配置为准',
    route: '/chat?scene=summary',
  },
]

function openAgent(agent) {
  router.push(agent.route)
}
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@500;700;900&display=swap');

/* --- Root & Sidebar --- */
.agent-root {
  background: #F5F9FD;
}

.agent-sidebar {
  background: linear-gradient(180deg, #F8FBFF 0%, #F1F6FC 100%);
}

.sidebar-item {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 10px;
  height: 44px;
  border-radius: 10px;
  padding: 0 14px;
  font-size: 14px;
  font-weight: 500;
  color: #78716C;
  border: none;
  background: transparent;
  cursor: pointer;
  transition: all 0.18s ease;
}

.sidebar-item:hover {
  background: rgba(0,0,0,0.04);
  color: #44403C;
}

.sidebar-item--active {
  background: #1C1917;
  color: #FAFAF9;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(28,25,23,0.18);
}

.sidebar-item--active:hover {
  background: #292524;
  color: #FAFAF9;
}

/* --- Mobile Tabs --- */
.mobile-tabs {
  background: #F5F9FD;
}

.mobile-tab {
  height: 36px;
  border-radius: 8px;
  padding: 0 14px;
  font-size: 14px;
  font-weight: 500;
  color: #78716C;
  border: none;
  background: transparent;
  cursor: pointer;
  transition: all 0.18s ease;
}

.mobile-tab:hover {
  color: #44403C;
}

.mobile-tab--active {
  background: #1C1917;
  color: #FAFAF9;
  font-weight: 600;
}

/* --- Canvas --- */
.agent-canvas {
  background:
    radial-gradient(ellipse at 80% 10%, rgba(37,99,168,0.05) 0%, transparent 50%),
    radial-gradient(ellipse at 20% 90%, rgba(23,63,107,0.03) 0%, transparent 50%),
    #F5F9FD;
}

/* --- Hero --- */
.agent-hero {
  position: relative;
  padding: 56px 40px 40px;
  overflow: hidden;
}

.agent-hero-inner {
  position: relative;
  z-index: 1;
  max-width: 560px;
}

.agent-hero-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 4px;
  background: #1C1917;
  color: #F5F0EB;
  font-family: 'SF Mono', 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.12em;
  margin-bottom: 20px;
}

.agent-hero-title {
  font-family: 'Noto Serif SC', Georgia, 'Times New Roman', serif;
  font-size: clamp(32px, 5vw, 48px);
  font-weight: 900;
  line-height: 1.15;
  color: #1C1917;
  letter-spacing: -0.02em;
  margin: 0 0 12px;
}

.agent-hero-desc {
  font-size: 16px;
  line-height: 1.7;
  color: #78716C;
  margin: 0;
  max-width: 440px;
}

.agent-hero-deco {
  position: absolute;
  top: 30px;
  right: 40px;
  width: 180px;
  height: 180px;
  pointer-events: none;
}

.deco-ring {
  position: absolute;
  border-radius: 50%;
  border: 1.5px solid rgba(23,63,107,0.08);
}

.deco-ring--1 {
  width: 140px;
  height: 140px;
  top: 0;
  right: 0;
  animation: spin-slow 28s linear infinite;
}

.deco-ring--2 {
  width: 90px;
  height: 90px;
  top: 40px;
  right: 40px;
  border-style: dashed;
  animation: spin-slow 20s linear infinite reverse;
}

.deco-dot {
  position: absolute;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #2563A8;
  top: 65px;
  right: 80px;
  box-shadow: 0 0 0 4px rgba(37,99,168,0.14);
}

@keyframes spin-slow {
  to { transform: rotate(360deg); }
}

/* --- Body --- */
.agent-body {
  padding: 0 40px 60px;
  max-width: 840px;
}

.agent-section-label {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 28px;
}

.agent-section-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, rgba(23,63,107,0.10) 0%, transparent 100%);
}

.agent-section-line:last-child {
  background: linear-gradient(270deg, rgba(23,63,107,0.10) 0%, transparent 100%);
}

.agent-section-text {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #A8A29E;
  white-space: nowrap;
}

/* --- Grid --- */
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
}

/* --- Card --- */
.agent-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 24px;
  border-radius: 16px;
  border: 1px solid #E4EAF2;
  background: rgba(255,255,255,0.88);
  backdrop-filter: blur(8px);
  text-align: left;
  cursor: pointer;
  overflow: hidden;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  animation: card-enter 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

@keyframes card-enter {
  from {
    opacity: 0;
    transform: translateY(16px) scale(0.97);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.agent-card:hover {
  border-color: #BFD3E7;
  transform: translateY(-4px);
  box-shadow:
    0 20px 40px rgba(28,25,23,0.08),
    0 0 0 1px rgba(28,25,23,0.03);
}

.agent-card-glow {
  position: absolute;
  inset: 0;
  opacity: 0;
  transition: opacity 0.35s ease;
  pointer-events: none;
}

.agent-card:hover .agent-card-glow {
  opacity: 1;
}

.agent-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}

.agent-card-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: 14px;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}

.agent-card-tag {
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.agent-card-name {
  font-family: 'Noto Serif SC', Georgia, serif;
  font-size: 20px;
  font-weight: 700;
  color: #1C1917;
  margin-bottom: 8px;
  line-height: 1.3;
}

.agent-card-desc {
  font-size: 13.5px;
  line-height: 1.65;
  color: #78716C;
  flex: 1;
}

.agent-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #EEF2F7;
}

.agent-card-model {
  font-family: 'SF Mono', 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 500;
  color: #A8A29E;
  letter-spacing: 0.02em;
}

.agent-card-enter {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  font-weight: 600;
  color: #44403C;
  transition: all 0.2s ease;
}

.agent-card:hover .agent-card-enter {
  color: #1C1917;
  gap: 8px;
}

/* --- Responsive --- */
@media (max-width: 640px) {
  .agent-hero {
    padding: 32px 20px 28px;
  }

  .agent-hero-deco {
    display: none;
  }

  .agent-body {
    padding: 0 20px 40px;
  }

  .agent-grid {
    grid-template-columns: 1fr;
  }

  .agent-hero-title {
    font-size: 28px;
  }
}
</style>
