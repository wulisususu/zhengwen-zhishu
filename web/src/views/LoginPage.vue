<template>
  <main class="login-page">
    <div ref="blindsHost" class="login-gradient-blinds" aria-hidden="true"></div>
    <div class="login-vignette" aria-hidden="true"></div>

    <section class="login-card">
      <div class="login-head">
        <button type="button" class="back-link" @click="router.push('/welcome')">
          <span class="back-arrow">←</span>
          <span>返回首页</span>
        </button>

        <h1 class="login-title">登录</h1>
        <p class="login-subtitle">
          {{ expired ? '登录状态已失效，请重新登录。' : '请输入账号和密码继续使用。' }}
        </p>
      </div>

      <form class="login-form" @submit.prevent="submit">
        <label class="field">
          <span class="field-label">账号</span>
          <input
            v-model.trim="username"
            autocomplete="username"
            class="field-input"
            placeholder="请输入账号"
          />
        </label>

        <label class="field">
          <span class="field-label">密码</span>
          <input
            v-model="password"
            autocomplete="current-password"
            class="field-input"
            placeholder="请输入密码"
            type="password"
          />
        </label>

        <p v-if="error" class="error-box">{{ error }}</p>

        <button type="submit" :disabled="loading" class="submit-btn">
          {{ loading ? '登录中...' : '登录' }}
        </button>
      </form>
    </section>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../api.js'
import { useAuthStore } from '../stores/auth.js'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const blindsHost = ref(null)
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const expired = computed(() => route.query.expired === '1')

let cleanupBlinds = null

const perf = {
  reduceMotion: typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  noHover: typeof window !== 'undefined' && !window.matchMedia('(hover: hover)').matches,
  isMobile: typeof window !== 'undefined' && window.matchMedia('(max-width: 640px)').matches,
  isLowCore: typeof navigator !== 'undefined' && (navigator.hardwareConcurrency || 8) < 4,
}

const hexToRGB = (hex) => {
  const c = hex.replace('#', '').padEnd(6, '0')
  return [
    parseInt(c.slice(0, 2), 16) / 255,
    parseInt(c.slice(2, 4), 16) / 255,
    parseInt(c.slice(4, 6), 16) / 255,
  ]
}

const MAX_COLORS = 8

const prepStops = (stops) => {
  const base = (stops && stops.length ? stops : ['#5EEAD4', '#FB923C']).slice(0, MAX_COLORS)
  if (base.length === 1) base.push(base[0])
  while (base.length < MAX_COLORS) base.push(base[base.length - 1])
  const arr = base.map(hexToRGB)
  const count = Math.max(2, Math.min(MAX_COLORS, stops?.length ?? 2))
  return { arr, count }
}

async function setupGradientBlinds(container) {
  if (!container || perf.reduceMotion || perf.isLowCore) return null
  // 纯 CSS 彩色光效：不再从 CDN 加载 WebGL 库，断网也能正常显示
  container.classList.add('css-glow')
  return () => container.classList.remove('css-glow')
}

function safeNextPath(value) {
  const next = Array.isArray(value) ? value[0] : value
  if (!next || typeof next !== 'string') return '/gov'
  if (!next.startsWith('/') || next.startsWith('//') || next.startsWith('/login')) return '/gov'
  return next
}

async function submit() {
  error.value = ''
  const user = username.value.trim()
  if (!user || !password.value) {
    error.value = '请输入账号和密码'
    return
  }
  loading.value = true
  try {
    const { data } = await api.post('/auth/login', { username: user, password: password.value })
    if (data.code !== 0 || !data.data?.access_token) {
      error.value = data.message || '登录失败'
      return
    }

    auth.setSession({
      token: data.data.access_token,
      token_type: data.data.token_type || 'bearer',
      username: user,
    })

    try {
      const me = await api.get('/auth/me')
      if (me.data.code === 0) {
        auth.setSession({
          ...auth.session,
          user: me.data.data,
          username: me.data.data?.username || user,
        })
      }
    } catch {}

    await router.replace(safeNextPath(route.query.next))
  } catch (e) {
    error.value = e?.response?.data?.message || e.message || '登录失败'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  cleanupBlinds = await setupGradientBlinds(blindsHost.value)
})

onBeforeUnmount(() => {
  cleanupBlinds?.()
})
</script>

<style scoped>
.login-page {
  position: relative;
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  overflow: hidden;
  background: #0a0b0e;
  color: #ffffff;
  isolation: isolate;
}

.login-gradient-blinds {
  position: absolute;
  inset: 0;
  z-index: -2;
  opacity: 0;
  transition: opacity 1.2s ease-out;
}

.login-gradient-blinds.is-ready {
  opacity: 1;
}

.login-gradient-blinds.css-glow {
  opacity: 1;
}

.login-gradient-blinds.css-glow::before {
  animation: loginGlowDrift 18s ease-in-out infinite;
  will-change: transform, opacity;
}

@keyframes loginGlowDrift {
  0%   { transform: translate3d(0, 0, 0) scale(1); opacity: 0.85; }
  50%  { transform: translate3d(-2.5%, 1.6%, 0) scale(1.09); opacity: 1; }
  100% { transform: translate3d(0, 0, 0) scale(1); opacity: 0.85; }
}

.login-gradient-blinds canvas {
  display: block;
  width: 100%;
  height: 100%;
}

.login-gradient-blinds::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(60% 50% at 30% 30%, rgba(94, 234, 212, 0.22), transparent 65%),
    radial-gradient(50% 42% at 75% 55%, rgba(251, 146, 60, 0.18), transparent 60%),
    radial-gradient(45% 40% at 50% 90%, rgba(168, 139, 250, 0.12), transparent 60%);
  z-index: -1;
}

.login-gradient-blinds.is-ready::before {
  opacity: 0;
  transition: opacity 0.8s;
}

.login-vignette {
  position: absolute;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  background:
    radial-gradient(ellipse 80% 60% at 50% 110%, #0a0b0e 0%, transparent 60%),
    linear-gradient(180deg, rgba(10, 11, 14, 0.2) 0%, transparent 20%, transparent 70%, rgba(10, 11, 14, 0.9) 100%);
}

.login-card {
  position: relative;
  z-index: 2;
  width: 100%;
  max-width: 420px;
  padding: 28px;
  border-radius: 28px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0.05));
  backdrop-filter: blur(26px);
  -webkit-backdrop-filter: blur(26px);
  box-shadow: 0 30px 120px rgba(0, 0, 0, 0.46);
}

.login-head {
  margin-bottom: 24px;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 0;
  padding: 0;
  color: rgba(255, 255, 255, 0.55);
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  line-height: 1.5;
  transition: color 0.18s ease;
}

.back-link:hover {
  color: rgba(255, 255, 255, 0.8);
}

.back-arrow {
  color: rgba(255, 255, 255, 0.35);
}

.login-title {
  margin: 24px 0 0;
  font-size: 34px;
  line-height: 1;
  font-weight: 700;
  letter-spacing: -0.04em;
}

.login-subtitle {
  margin: 12px 0 0;
  color: rgba(255, 255, 255, 0.62);
  font-size: 14px;
  line-height: 1.7;
}

.login-form {
  display: grid;
  gap: 16px;
}

.field {
  display: grid;
  gap: 8px;
}

.field-label {
  color: rgba(255, 255, 255, 0.68);
  font-size: 13px;
  line-height: 1.5;
}

.field-input {
  height: 44px;
  width: 100%;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(0, 0, 0, 0.18);
  padding: 0 16px;
  color: #ffffff;
  font-size: 14px;
  outline: none;
  transition: border-color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease;
}

.field-input::placeholder {
  color: rgba(255, 255, 255, 0.28);
}

.field-input:focus {
  border-color: rgba(126, 242, 223, 0.72);
  background: rgba(0, 0, 0, 0.28);
  box-shadow: 0 0 0 4px rgba(126, 242, 223, 0.12);
}

.error-box {
  margin: 0;
  border-radius: 14px;
  border: 1px solid rgba(252, 165, 165, 0.18);
  background: rgba(239, 68, 68, 0.12);
  padding: 12px 16px;
  color: #fee2e2;
  font-size: 13px;
  line-height: 1.5;
}

.submit-btn {
  height: 44px;
  width: 100%;
  border: 0;
  border-radius: 14px;
  background: linear-gradient(135deg, #63ead8 0%, #91f0df 38%, #ffd27a 100%);
  color: #041018;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, opacity 0.18s ease;
  box-shadow: 0 14px 36px rgba(94, 234, 212, 0.26);
}

.submit-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 18px 44px rgba(94, 234, 212, 0.32);
}

.submit-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
  transform: none;
}

@media (max-width: 640px) {
  .login-card {
    padding: 24px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .login-gradient-blinds {
    display: none;
  }
}
</style>
