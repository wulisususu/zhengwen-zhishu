<template>
  <main class="login-page">
    <div ref="blindsHost" class="login-gradient-blinds" aria-hidden="true"></div>
    <div class="login-vignette" aria-hidden="true"></div>

    <section class="login-card">
      <div class="login-head">
        <button type="button" class="back-link" @click="router.push('/')">
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

  const { Renderer, Program, Mesh, Triangle } = await import(
    /* @vite-ignore */ 'https://esm.sh/ogl@1.0.11'
  )

  const params = {
    gradientColors: ['#5EEAD4', '#8B5CF6', '#FB923C', '#5EEAD4'],
    angle: 25,
    noise: 0.18,
    blindCount: 14,
    blindMinWidth: 80,
    mouseDampening: 0.04,
    mirrorGradient: true,
    spotlightRadius: 0.55,
    spotlightSoftness: 1,
    spotlightOpacity: 0.9,
    distortAmount: 1.6,
    shineDirection: 'left',
    mixBlendMode: 'lighten',
  }

  let renderer
  let gl
  let program
  let mesh
  let canvas
  let raf = 0
  let mouseTarget = [0, 0]
  let lastTime = 0
  let firstResize = true
  let running = true

  const vertex = `
    attribute vec2 position;
    attribute vec2 uv;
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = vec4(position, 0.0, 1.0); }
  `

  const fragment = `
    #ifdef GL_ES
    precision mediump float;
    #endif
    uniform vec3 iResolution; uniform vec2 iMouse; uniform float iTime;
    uniform float uAngle; uniform float uNoise; uniform float uBlindCount;
    uniform float uSpotlightRadius; uniform float uSpotlightSoftness; uniform float uSpotlightOpacity;
    uniform float uMirror; uniform float uDistort; uniform float uShineFlip;
    uniform vec3 uColor0; uniform vec3 uColor1; uniform vec3 uColor2; uniform vec3 uColor3;
    uniform vec3 uColor4; uniform vec3 uColor5; uniform vec3 uColor6; uniform vec3 uColor7;
    uniform int uColorCount;
    varying vec2 vUv;

    float rand(vec2 co){ return fract(sin(dot(co, vec2(12.9898,78.233))) * 43758.5453); }
    vec2 rotate2D(vec2 p, float a){ float c = cos(a); float s = sin(a); return mat2(c, -s, s, c) * p; }

    vec3 getGradientColor(float t){
      float tt = clamp(t, 0.0, 1.0);
      int count = uColorCount; if (count < 2) count = 2;
      float scaled = tt * float(count - 1);
      float seg = floor(scaled); float f = fract(scaled);
      if (seg < 1.0) return mix(uColor0, uColor1, f);
      if (seg < 2.0 && count > 2) return mix(uColor1, uColor2, f);
      if (seg < 3.0 && count > 3) return mix(uColor2, uColor3, f);
      if (seg < 4.0 && count > 4) return mix(uColor3, uColor4, f);
      if (seg < 5.0 && count > 5) return mix(uColor4, uColor5, f);
      if (seg < 6.0 && count > 6) return mix(uColor5, uColor6, f);
      if (seg < 7.0 && count > 7) return mix(uColor6, uColor7, f);
      if (count > 7) return uColor7; if (count > 6) return uColor6;
      if (count > 5) return uColor5; if (count > 4) return uColor4;
      if (count > 3) return uColor3; if (count > 2) return uColor2;
      return uColor1;
    }

    void mainImage(out vec4 fragColor, in vec2 fragCoord){
      vec2 uv0 = fragCoord.xy / iResolution.xy;
      float aspect = iResolution.x / iResolution.y;
      vec2 p = uv0 * 2.0 - 1.0; p.x *= aspect;
      vec2 pr = rotate2D(p, uAngle); pr.x /= aspect;
      vec2 uv = pr * 0.5 + 0.5;

      vec2 uvMod = uv;
      if (uDistort > 0.0) {
        float a = uvMod.y * 6.0; float b = uvMod.x * 6.0;
        float w = 0.01 * uDistort;
        uvMod.x += sin(a) * w; uvMod.y += cos(b) * w;
      }
      float t = uvMod.x;
      if (uMirror > 0.5) t = 1.0 - abs(1.0 - 2.0 * fract(t));
      vec3 base = getGradientColor(t);

      vec2 offset = vec2(iMouse.x/iResolution.x, iMouse.y/iResolution.y);
      float d = length(uv0 - offset);
      float r = max(uSpotlightRadius, 1e-4);
      float dn = d / r;
      float spot = (1.0 - 2.0 * pow(dn, uSpotlightSoftness)) * uSpotlightOpacity;
      vec3 cir = vec3(spot);
      float stripe = fract(uvMod.x * max(uBlindCount, 1.0));
      if (uShineFlip > 0.5) stripe = 1.0 - stripe;
      vec3 ran = vec3(stripe);

      vec3 col = cir + base - ran;
      col += (rand(gl_FragCoord.xy + iTime) - 0.5) * uNoise;
      fragColor = vec4(col, 1.0);
    }

    void main() { vec4 color; mainImage(color, vUv * iResolution.xy); gl_FragColor = color; }
  `

  const dprCap = perf.isMobile || perf.isLowCore ? 1 : 1.5
  renderer = new Renderer({
    dpr: Math.min(window.devicePixelRatio || 1, dprCap),
    alpha: true,
    antialias: !perf.isMobile,
  })

  gl = renderer.gl
  canvas = gl.canvas
  canvas.style.width = '100%'
  canvas.style.height = '100%'
  canvas.style.display = 'block'
  canvas.style.mixBlendMode = params.mixBlendMode
  container.appendChild(canvas)

  const { arr, count } = prepStops(params.gradientColors)
  const uniforms = {
    iResolution: { value: [gl.drawingBufferWidth, gl.drawingBufferHeight, 1] },
    iMouse: { value: [0, 0] },
    iTime: { value: 0 },
    uAngle: { value: (params.angle * Math.PI) / 180 },
    uNoise: { value: params.noise },
    uBlindCount: { value: Math.max(1, params.blindCount) },
    uSpotlightRadius: { value: params.spotlightRadius },
    uSpotlightSoftness: { value: params.spotlightSoftness },
    uSpotlightOpacity: { value: params.spotlightOpacity },
    uMirror: { value: params.mirrorGradient ? 1 : 0 },
    uDistort: { value: params.distortAmount },
    uShineFlip: { value: params.shineDirection === 'right' ? 1 : 0 },
    uColor0: { value: arr[0] }, uColor1: { value: arr[1] },
    uColor2: { value: arr[2] }, uColor3: { value: arr[3] },
    uColor4: { value: arr[4] }, uColor5: { value: arr[5] },
    uColor6: { value: arr[6] }, uColor7: { value: arr[7] },
    uColorCount: { value: count },
  }

  program = new Program(gl, { vertex, fragment, uniforms })
  mesh = new Mesh(gl, { geometry: new Triangle(gl), program })

  const resize = () => {
    const rect = container.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    renderer.setSize(rect.width, rect.height)
    uniforms.iResolution.value = [gl.drawingBufferWidth, gl.drawingBufferHeight, 1]
    if (params.blindMinWidth > 0) {
      const maxByMinWidth = Math.max(1, Math.floor(rect.width / params.blindMinWidth))
      uniforms.uBlindCount.value = Math.max(1, Math.min(params.blindCount, maxByMinWidth))
    }
    if (firstResize) {
      firstResize = false
      uniforms.iMouse.value = [gl.drawingBufferWidth / 2, gl.drawingBufferHeight / 2]
      mouseTarget = [...uniforms.iMouse.value]
    }
  }

  resize()
  const ro = new ResizeObserver(resize)
  ro.observe(container)

  let pmRaf = 0
  const onPointerMove = (event) => {
    if (pmRaf) return
    pmRaf = requestAnimationFrame(() => {
      const rect = canvas.getBoundingClientRect()
      const scale = renderer.dpr || 1
      mouseTarget = [
        (event.clientX - rect.left) * scale,
        (rect.height - (event.clientY - rect.top)) * scale,
      ]
      pmRaf = 0
    })
  }

  const host = container.parentElement || container
  host.addEventListener('pointermove', onPointerMove, { passive: true })

  const io = new IntersectionObserver(([entry]) => {
    running = entry.isIntersecting
  }, { threshold: 0 })
  io.observe(container)

  const loop = (time) => {
    raf = requestAnimationFrame(loop)
    if (!running) return
    uniforms.iTime.value = time * 0.001
    if (params.mouseDampening > 0) {
      if (!lastTime) lastTime = time
      const dt = (time - lastTime) / 1000
      lastTime = time
      const factor = Math.min(1, 1 - Math.exp(-dt / Math.max(1e-4, params.mouseDampening)))
      const cur = uniforms.iMouse.value
      cur[0] += (mouseTarget[0] - cur[0]) * factor
      cur[1] += (mouseTarget[1] - cur[1]) * factor
    } else {
      uniforms.iMouse.value = mouseTarget
    }
    renderer.render({ scene: mesh })
  }

  raf = requestAnimationFrame(loop)
  requestAnimationFrame(() => container.classList.add('is-ready'))

  return () => {
    cancelAnimationFrame(raf)
    host.removeEventListener('pointermove', onPointerMove)
    ro.disconnect()
    io.disconnect()
    if (canvas.parentElement === container) container.removeChild(canvas)
  }
}

function safeNextPath(value) {
  const next = Array.isArray(value) ? value[0] : value
  if (!next || typeof next !== 'string') return '/chat'
  if (!next.startsWith('/') || next.startsWith('//') || next.startsWith('/login')) return '/chat'
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
