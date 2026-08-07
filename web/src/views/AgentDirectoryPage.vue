<template>
  <main class="agent-root flex h-dvh flex-col overflow-hidden text-black">
    <AppHeader title="" subtitle="中科信创（南京）" :show-logout="false" @goHome="router.push('/')" />

    <div class="flex min-h-0 flex-1">
      <aside class="agent-sidebar hidden w-[220px] shrink-0 border-r border-[#E8E0D8] px-3 py-5 md:flex md:min-h-0 md:flex-col">
        <nav class="shrink-0 space-y-1">
          <button
            @click="router.push('/chat')"
            class="sidebar-item"
          >
            <MessageSquare class="size-[18px]" :stroke-width="1.8" />
            <span>聊天</span>
          </button>
          <button
            type="button"
            class="sidebar-item"
          >
            <Presentation class="size-[18px]" :stroke-width="1.8" />
            <span>PPT生成</span>
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
          <button @click="router.push('/chat')" class="mobile-tab">聊天</button>
          <button class="mobile-tab mobile-tab--active">智能体</button>
        </div>

        <div class="agent-canvas min-h-0 flex-1 overflow-y-auto">
          <div class="agent-hero">
            <div class="agent-hero-inner">
              <div class="agent-hero-badge">AGENT HUB</div>
              <h1 class="agent-hero-title">智能体中心</h1>
              <p class="agent-hero-desc">探索专属 AI 助手，各司其职，精准高效</p>
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
              <span class="agent-section-text">可用智能体</span>
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
                    <span class="agent-card-emoji">{{ agent.emoji }}</span>
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
import { ArrowRight, Bot, MessageSquare, Presentation } from 'lucide-vue-next'
import AppHeader from '../components/AppHeader.vue'

const router = useRouter()

const agents = [
  {
    id: 'pediatric-medical-qa',
    name: '少儿问答',
    description: '面向儿童的健康问答助手，用温暖易懂的语言解答少儿健康问题，帮助家长获取专业参考',
    emoji: '🩺',
    bg: 'linear-gradient(145deg, #DCFCE7 0%, #BBF7D0 100%)',
    glow: 'radial-gradient(circle at 30% 70%, rgba(34,197,94,0.12) 0%, transparent 70%)',
    tag: '健康',
    tagColor: '#166534',
    tagBg: '#DCFCE7',
    model: 'Qwen2.5-1.5B',
    route: '/agents/pediatric-medical-qa',
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
  background: #FDF8F3;
}

.agent-sidebar {
  background: linear-gradient(180deg, #FDF8F3 0%, #FAF5EE 100%);
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
  background: #FDF8F3;
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
    radial-gradient(ellipse at 80% 10%, rgba(251,191,36,0.06) 0%, transparent 50%),
    radial-gradient(ellipse at 20% 90%, rgba(34,197,94,0.04) 0%, transparent 50%),
    #FDF8F3;
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
  border: 1.5px solid rgba(28,25,23,0.07);
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
  background: #D97706;
  top: 65px;
  right: 80px;
  box-shadow: 0 0 0 4px rgba(217,119,6,0.15);
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
  background: linear-gradient(90deg, rgba(28,25,23,0.08) 0%, transparent 100%);
}

.agent-section-line:last-child {
  background: linear-gradient(270deg, rgba(28,25,23,0.08) 0%, transparent 100%);
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
  border: 1px solid #E7E5E4;
  background: rgba(255,255,255,0.82);
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
  border-color: #D6D3D1;
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

.agent-card-emoji {
  font-size: 26px;
  line-height: 1;
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
  border-top: 1px solid #F5F5F4;
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
