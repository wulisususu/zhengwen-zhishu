<template>
  <form @submit.prevent="send" class="composer-shell">
    <div class="composer-wrap">
      <div class="composer-row">
      <div class="composer-main">
        <textarea
          ref="textareaEl"
          v-model="input"
          rows="1"
          :placeholder="displayPlaceholder"
          @keydown.enter.exact.prevent="send"
          :class="['composer-textarea', { 'composer-textarea-recording': recording }]"
        />

        <transition name="rec-fade">
          <div v-if="recording" class="rec-indicator">
            <span class="rec-dot"></span>
            <span class="rec-time">{{ recTimeDisplay }}</span>
          </div>
        </transition>
      </div>

      <div class="composer-actions">
        <transition name="btn-swap" mode="out-in">
          <div v-if="recording" key="rec-controls" class="rec-controls">
            <button
              type="button"
              @click="confirmRecord"
              class="rec-wave-btn"
              title="结束录音并发送"
            >
              <svg class="rec-wave-icon" viewBox="0 0 24 24" fill="none">
                <rect x="3" y="8" width="2" height="8" rx="1" fill="white">
                  <animate attributeName="height" values="8;14;8" dur="0.8s" repeatCount="indefinite" />
                  <animate attributeName="y" values="8;5;8" dur="0.8s" repeatCount="indefinite" />
                </rect>
                <rect x="7" y="5" width="2" height="14" rx="1" fill="white">
                  <animate attributeName="height" values="14;6;14" dur="0.6s" repeatCount="indefinite" />
                  <animate attributeName="y" values="5;9;5" dur="0.6s" repeatCount="indefinite" />
                </rect>
                <rect x="11" y="3" width="2" height="18" rx="1" fill="white">
                  <animate attributeName="height" values="18;8;18" dur="0.7s" repeatCount="indefinite" />
                  <animate attributeName="y" values="3;8;3" dur="0.7s" repeatCount="indefinite" />
                </rect>
                <rect x="15" y="6" width="2" height="12" rx="1" fill="white">
                  <animate attributeName="height" values="12;16;12" dur="0.9s" repeatCount="indefinite" />
                  <animate attributeName="y" values="6;4;6" dur="0.9s" repeatCount="indefinite" />
                </rect>
                <rect x="19" y="8" width="2" height="8" rx="1" fill="white">
                  <animate attributeName="height" values="8;12;8" dur="0.65s" repeatCount="indefinite" />
                  <animate attributeName="y" values="8;6;8" dur="0.65s" repeatCount="indefinite" />
                </rect>
              </svg>
            </button>
          </div>

          <button
            v-else
            key="mic-btn"
            type="button"
            @click="startRecord"
            class="action-btn action-mic"
            title="点击录音"
          >
            <Mic class="size-5" :stroke-width="2.1" />
          </button>
        </transition>

        <transition name="btn-swap" mode="out-in">
          <button
            v-if="!recording"
            type="submit"
            :disabled="loading"
            class="send-btn"
          >
            <Send class="size-5" :stroke-width="2.1" />
          </button>
        </transition>
      </div>
      </div>
    <div v-if="$slots['suggestion-prefix'] || suggestions.length" class="suggestion-list">
      <slot name="suggestion-prefix" />
      <button
        v-for="item in suggestions"
        :key="item.key || item.label"
        type="button"
        class="suggestion-chip"
        @click="emit('suggestion-click', item)"
      >
        {{ item.label }}
      </button>
    </div>
    </div>
  </form>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { Mic, Send, X, Check } from 'lucide-vue-next'
import api from '../api.js'
import {
  applyChunkAsrResponse,
  applyFinalAsrResponse,
  composeInputText,
  createVoiceDraftState,
} from './composerVoiceState.mjs'

const props = defineProps({
  placeholder: String,
  loading: Boolean,
  suggestions: { type: Array, default: () => [] },
})
const displayPlaceholder = computed(() => {
  if (recording.value || finalizingRecord.value) return '正在聆听并识别...'
  return props.placeholder
})
const emit = defineEmits(['send', 'suggestion-click'])
const input = ref('')
const textareaEl = ref(null)
const recording = ref(false)
const recSeconds = ref(0)
const recTimeDisplay = ref('0:00')
const finalizingRecord = ref(false)
let recTimer = null
let recordingStream = null
let recAudioCtx = null
let recProcessor = null
let recRawSamples = []
let recChunkCounter = 0
let recSampleRate = 16000
let baseInputText = ''
let confirmedText = ''
let interimText = ''
let chunkQueue = []
let chunkProcessing = false
let discardRecording = false
let voiceDraft = createVoiceDraftState()
let voiceSessionId = ''
let audioContext = null
let analyserNode = null
let sourceNode = null
let monitorTimer = null
let silenceMs = 0
let hasSpoken = false
let sentencePauseReported = false
let autoFinalizeTriggered = false
let voiceAutoSentThisSession = false

const CHUNK_INTERVAL_MS = 2000
const SILENCE_SAMPLE_MS = 120
const SENTENCE_PAUSE_MS = 600
const FINAL_PAUSE_MS = 2200
const SPEECH_THRESHOLD = 0.018
const TEXTAREA_MAX_HEIGHT = 220

function resizeComposerInput() {
  const el = textareaEl.value
  if (!el) return
  el.style.height = 'auto'
  const nextHeight = Math.min(el.scrollHeight, TEXTAREA_MAX_HEIGHT)
  el.style.height = `${nextHeight}px`
  el.style.overflowY = el.scrollHeight > TEXTAREA_MAX_HEIGHT ? 'auto' : 'hidden'
}

onMounted(() => {
  resizeComposerInput()
})

watch(input, () => {
  nextTick(resizeComposerInput)
})

onUnmounted(() => {
  stopTimer()
  stopSilenceMonitor()
  recording.value = false
  finalizingRecord.value = false
  if (recProcessor) {
    try { recProcessor.disconnect() } catch {}
    recProcessor = null
  }
  if (recAudioCtx) {
    recAudioCtx.close().catch(() => {})
    recAudioCtx = null
  }
  if (recordingStream) {
    recordingStream.getTracks().forEach((track) => track.stop())
    recordingStream = null
  }
})

function startTimer() {
  recSeconds.value = 0
  recTimeDisplay.value = '0:00'
  recTimer = window.setInterval(() => {
    recSeconds.value++
    const m = Math.floor(recSeconds.value / 60)
    const s = recSeconds.value % 60
    recTimeDisplay.value = m + ':' + (s < 10 ? '0' : '') + s
  }, 1000)
}

function stopTimer() {
  if (recTimer) {
    window.clearInterval(recTimer)
    recTimer = null
  }
}

function stopSilenceMonitor() {
  if (monitorTimer) {
    window.clearInterval(monitorTimer)
    monitorTimer = null
  }
  silenceMs = 0
  hasSpoken = false
  sentencePauseReported = false
  autoFinalizeTriggered = false
  if (sourceNode) {
    try { sourceNode.disconnect() } catch {}
    sourceNode = null
  }
  if (analyserNode) {
    try { analyserNode.disconnect() } catch {}
    analyserNode = null
  }
  if (audioContext) {
    const current = audioContext
    audioContext = null
    current.close().catch(() => {})
  }
}

function floatTo16BitPCM(view, offset, input) {
  for (let i = 0; i < input.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, input[i]))
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
}

function pcmToWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const writeString = (o, s) => {
    for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i))
  }
  writeString(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeString(8, 'WAVE')
  writeString(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeString(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  floatTo16BitPCM(view, 44, samples)
  return new Blob([buffer], { type: 'audio/wav' })
}

function syncInputWithTranscript() {
  input.value = composeInputText(baseInputText, confirmedText, interimText)
}

function promoteInterimToConfirmed() {
  if (!interimText) return
  confirmedText += interimText
  interimText = ''
  syncInputWithTranscript()
}

function resetRecordingTranscript(restoreBase = false) {
  confirmedText = ''
  interimText = ''
  chunkQueue = []
  chunkProcessing = false
  voiceDraft = createVoiceDraftState()
  recRawSamples = []
  recChunkCounter = 0
  voiceAutoSentThisSession = false
  if (restoreBase) {
    input.value = baseInputText
  }
}

async function postAudio(endpoint, wavBlob, filename) {
  const form = new FormData()
  form.append('file', wavBlob, filename)
  if (voiceSessionId) {
    form.append('session_id', voiceSessionId)
  }
  const res = await api.post(endpoint, form)
  if (res.data?.code === 0 && res.data?.data) {
    return res.data.data
  }
  return null
}

async function postPauseSignal(pauseMs) {
  if (!voiceSessionId) return
  try {
    const res = await api.post('/asr/recognize_pause', {
      session_id: voiceSessionId,
      pause_ms: pauseMs,
      explicit_finalize: false,
    })
    const data = res.data?.code === 0 ? res.data.data : null
    if (!data) return
    const next = applyChunkAsrResponse(
      {
        baseInputText,
        confirmedText,
        interimText,
        inputText: input.value,
        voiceDraft,
      },
      data,
    )
    confirmedText = next.confirmedText
    interimText = next.interimText
    voiceDraft = next.voiceDraft
    input.value = next.inputText
  } catch (err) {
    console.error('ASR pause signal failed:', err)
  }
}

function startSilenceMonitor(stream) {
  stopSilenceMonitor()
  audioContext = new AudioContext()
  sourceNode = audioContext.createMediaStreamSource(stream)
  analyserNode = audioContext.createAnalyser()
  analyserNode.fftSize = 2048
  analyserNode.smoothingTimeConstant = 0.2
  sourceNode.connect(analyserNode)
  const samples = new Float32Array(analyserNode.fftSize)
  monitorTimer = window.setInterval(() => {
    if (!recording.value || finalizingRecord.value || !analyserNode) return
    analyserNode.getFloatTimeDomainData(samples)
    let sum = 0
    for (let i = 0; i < samples.length; i++) {
      const value = samples[i]
      sum += value * value
    }
    const rms = Math.sqrt(sum / samples.length)
    if (rms >= SPEECH_THRESHOLD) {
      hasSpoken = true
      silenceMs = 0
      sentencePauseReported = false
      return
    }
    if (!hasSpoken) return
    silenceMs += SILENCE_SAMPLE_MS
    if (!sentencePauseReported && silenceMs >= SENTENCE_PAUSE_MS) {
      sentencePauseReported = true
      void postPauseSignal(silenceMs)
    }
    if (!autoFinalizeTriggered && silenceMs >= FINAL_PAUSE_MS) {
      autoFinalizeTriggered = true
      confirmRecord()
    }
  }, SILENCE_SAMPLE_MS)
}

async function processChunkQueue() {
  if (chunkProcessing) return
  chunkProcessing = true
  try {
    while (chunkQueue.length) {
      const wavBlob = chunkQueue.shift()
      if (!wavBlob || !wavBlob.size) continue
      try {
        const data = await postAudio('/asr/recognize_chunk', wavBlob, 'voice_chunk.wav')
        const next = applyChunkAsrResponse(
          {
            baseInputText,
            confirmedText,
            interimText,
            inputText: input.value,
            voiceDraft,
          },
          data || { text: '' },
        )
        confirmedText = next.confirmedText
        interimText = next.interimText
        voiceDraft = next.voiceDraft
        input.value = next.inputText
      } catch (err) {
        console.error('ASR chunk failed:', err)
      }
    }
  } finally {
    chunkProcessing = false
  }
}

function enqueueChunk(blob) {
  if (!blob || !blob.size) return
  chunkQueue.push(blob)
  void processChunkQueue()
}

function stopRealtimeRecorder() {
  if (recProcessor) {
    try { recProcessor.disconnect() } catch {}
    recProcessor = null
  }
  if (recAudioCtx) {
    recAudioCtx.close().catch(() => {})
    recAudioCtx = null
  }
  if (recordingStream) {
    recordingStream.getTracks().forEach((t) => t.stop())
    recordingStream = null
  }
}

function flushBufferedSamples() {
  let totalSamples = 0
  for (const buf of recRawSamples) totalSamples += buf.length
  if (!totalSamples) {
    recRawSamples = []
    return null
  }
  const merged = new Float32Array(totalSamples)
  let offset = 0
  for (const buf of recRawSamples) {
    merged.set(buf, offset)
    offset += buf.length
  }
  recRawSamples = []
  return pcmToWav(merged, recSampleRate)
}

async function finalizeVoiceSession() {
  try {
    const res = await api.post('/asr/recognize_pause', {
      session_id: voiceSessionId,
      pause_ms: FINAL_PAUSE_MS,
      explicit_finalize: true,
    })
    return res.data?.code === 0 ? res.data.data : null
  } catch (err) {
    console.error('ASR finalize pause failed:', err)
    return null
  }
}

async function startRecord() {
  if (!navigator.mediaDevices) {
    alert('浏览器不支持录音')
    return
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    recordingStream = stream
    baseInputText = input.value.trim()
    resetRecordingTranscript()
    voiceSessionId = `voice_session_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`
    voiceAutoSentThisSession = false
    discardRecording = false
    finalizingRecord.value = false
    recAudioCtx = new AudioContext()
    recSampleRate = recAudioCtx.sampleRate
    const source = recAudioCtx.createMediaStreamSource(stream)
    recProcessor = recAudioCtx.createScriptProcessor(4096, 1, 1)
    recProcessor.onaudioprocess = (e) => {
      if (discardRecording) return
      const inputBuf = e.inputBuffer.getChannelData(0)
      recRawSamples.push(new Float32Array(inputBuf))
      let totalSamples = 0
      for (const buf of recRawSamples) totalSamples += buf.length
      const chunkSamples = recSampleRate * (CHUNK_INTERVAL_MS / 1000)
      if (totalSamples >= chunkSamples) {
        const wavBlob = flushBufferedSamples()
        if (wavBlob) {
          enqueueChunk(wavBlob)
          recChunkCounter += 1
        }
      }
    }
    source.connect(recProcessor)
    recProcessor.connect(recAudioCtx.destination)
    recording.value = true
    startTimer()
    startSilenceMonitor(stream)
  } catch (err) {
    console.error('录音失败:', err)
    if (err.name === 'NotAllowedError') {
      alert('请在浏览器中允许使用麦克风')
    }
  }
}

function cancelRecord() {
  stopTimer()
  stopSilenceMonitor()
  recording.value = false
  discardRecording = true
  stopRealtimeRecorder()
  voiceSessionId = ''
  resetRecordingTranscript(true)
}

async function confirmRecord() {
  stopTimer()
  stopSilenceMonitor()
  recording.value = false
  stopRealtimeRecorder()
  if (discardRecording) return

  finalizingRecord.value = true
  try {
    const trailingWav = flushBufferedSamples()
    while (chunkProcessing || chunkQueue.length) {
      await new Promise((resolve) => window.setTimeout(resolve, 120))
    }

    const data = trailingWav
      ? await postAudio('/asr/recognize_final', trailingWav, 'voice_final.wav')
      : await finalizeVoiceSession()

    if (data?.text || data?.voice_event) {
      const next = applyFinalAsrResponse(
        {
          baseInputText,
          confirmedText,
          interimText,
          inputText: input.value,
          voiceDraft,
        },
        data,
      )
      confirmedText = next.confirmedText
      interimText = next.interimText
      voiceDraft = next.voiceDraft
      input.value = next.inputText
      autoSendFinalVoiceInput(next.inputText)
    } else {
      promoteInterimToConfirmed()
      syncInputWithTranscript()
      autoSendFinalVoiceInput(input.value)
    }
  } catch (err) {
    console.error('ASR final failed:', err)
    promoteInterimToConfirmed()
    syncInputWithTranscript()
  } finally {
    finalizingRecord.value = false
    confirmedText = ''
    interimText = ''
    chunkQueue = []
    chunkProcessing = false
    recRawSamples = []
    voiceSessionId = ''
  }
}

function send() {
  if (recording.value || finalizingRecord.value) return
  if (!input.value.trim()) return
  emit('send', input.value)
  input.value = ''
  nextTick(resizeComposerInput)
}

function autoSendFinalVoiceInput(text) {
  const finalText = String(text || '').trim()
  if (!finalText || voiceAutoSentThisSession) return
  voiceAutoSentThisSession = true
  emit('send', finalText)
  input.value = ''
  nextTick(resizeComposerInput)
}
</script>

<style scoped>
.composer-shell {
  border-top: none;
  padding: 10px 18px 10px;
  background: transparent;
}

.composer-wrap {
  display: flex;
  flex-direction: column;
  width: 75%;
  margin: 0 auto;
  gap: 0;
  border-radius: 18px;
  border: 2px solid #8ab4e8;
  background: #fff;
  padding: 12px 14px 12px 18px;
  box-shadow: 0 0 24px rgba(100, 180, 255, 0.25), 0 2px 8px rgba(100, 160, 240, 0.12);
  transition: border-color 0.25s ease, box-shadow 0.25s ease;
}

.composer-row {
  display: flex;
  align-items: flex-end;
  gap: 16px;
}

.composer-wrap:focus-within {
  border-color: #d7d0c7;
  box-shadow: 0 0 0 4px rgba(100, 180, 255, 0.12), 0 0 24px rgba(100, 180, 255, 0.25);
}

.composer-main {
  flex: 1;
  min-width: 0;
}

.composer-textarea {
  width: 100%;
  min-height: 32px;
  max-height: 220px;
  box-sizing: border-box;
  display: block;
  resize: none;
  background: transparent;
  padding: 0;
  font-size: 18px;
  line-height: 28px;
  outline: none;
  border: none;
  color: #181818;
  overflow-y: hidden;
  transition: opacity 0.2s ease;
}

.composer-textarea::placeholder {
  color: #8f8f8f;
}

.composer-textarea-recording {
  opacity: 0.5;
  pointer-events: none;
}

.composer-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  align-self: center;
}

.rec-controls {
  display: flex;
  align-items: center;
}

.rec-wave-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: 999px;
  border: none;
  background: #1677FF;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(22, 119, 255, 0.35);
  transition: all 0.2s ease;
}

.rec-wave-btn:hover {
  background: #0958d9;
  transform: scale(1.05);
}

.rec-wave-icon {
  width: 24px;
  height: 24px;
}

.action-btn,
.send-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: 999px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-mic {
  background: #ffffff;
  border-color: #e8e5df;
  color: rgba(24, 24, 24, 0.72);
}

.action-mic:hover {
  background: #f4f2ed;
  color: #111111;
}

/* action-cancel removed */



/* action-confirm removed */



.send-btn {
  background: #111111;
  color: #ffffff;
  box-shadow: 0 6px 18px rgba(17, 17, 17, 0.14);
}

.send-btn:hover {
  background: #222222;
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

.rec-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  width: fit-content;
  padding: 6px 12px;
  border-radius: 20px;
  background: rgba(239, 68, 68, 0.08);
}

.rec-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ef4444;
  animation: rec-pulse 1.2s ease-in-out infinite;
}

.rec-time {
  font-size: 13px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  color: #ef4444;
}

@keyframes rec-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.8); }
}

.btn-swap-enter-active {
  transition: all 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.btn-swap-leave-active {
  transition: all 0.14s ease-in;
}

.btn-swap-enter-from,
.btn-swap-leave-to {
  opacity: 0;
  transform: scale(0.7);
}

.rec-fade-enter-active {
  transition: all 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.rec-fade-leave-active {
  transition: all 0.18s ease-in;
}

.rec-fade-enter-from,
.rec-fade-leave-to {
  opacity: 0;
  transform: translateX(-10px) scale(0.9);
}

.suggestion-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 10px;
  padding-top: 10px;
  margin-top: 10px;
  border-top: 1px solid #eef1f5;
}

.suggestion-chip {
  display: inline-flex;
  align-items: center;
  height: 38px;
  padding: 0 16px;
  border-radius: 999px;
  border: 2px solid #8ab4e8;
  background: #ffffff;
  color: #4a4a4a;
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
  transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}

.suggestion-chip:hover {
  background: #f4f2ed;
  border-color: #ddd6ce;
  color: #181818;
}

@media (max-width: 640px) {
  .composer-shell {
    padding: 12px 12px 16px;
  }

  .composer-wrap {
    gap: 12px;
    border-radius: 24px;
    padding: 10px 12px 10px 16px;
  }

  .composer-textarea {
    min-height: 28px;
    max-height: 176px;
    font-size: 16px;
    line-height: 24px;
  }

  .action-btn,
  .send-btn {
    width: 46px;
    height: 46px;
  }
}
</style>

