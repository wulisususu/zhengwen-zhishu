<script setup lang="ts">
import type { Slide } from "../../types/presentation";

defineProps<{ slide: Slide; selected: boolean }>();
defineEmits<{ select: [] }>();
</script>

<template>
  <button
    type="button"
    class="group w-full rounded-xl border bg-white p-2 text-left transition"
    :class="selected ? 'border-blue-500 shadow-[0_0_0_2px_rgba(59,130,246,.12)]' : 'border-slate-200 hover:border-slate-300'"
    :data-status="slide.status"
    :aria-current="selected ? 'true' : undefined"
    :aria-label="`第 ${slide.index} 页：${slide.title || '生成中'}`"
    @click="$emit('select')"
  >
    <div class="mb-2 flex items-center justify-between px-0.5 text-[11px] text-slate-400">
      <span>{{ slide.index }}</span><span>{{ slide.status === 'ready' ? '已完成' : slide.status === 'generating' ? '生成中' : slide.status === 'error' ? '失败' : '等待' }}</span>
    </div>
    <div class="relative aspect-video overflow-hidden rounded-lg border border-slate-100 bg-slate-50 p-3" :class="slide.status === 'generating' ? 'animate-pulse ring-2 ring-blue-200' : ''">
      <template v-if="slide.status === 'ready'">
        <img
          v-if="slide.thumbnailUrl"
          :src="slide.thumbnailUrl"
          :alt="`${slide.title} 缩略图`"
          data-slide-thumbnail-image
          class="h-full w-full rounded-md bg-white object-contain shadow-sm"
        >
        <div v-else class="h-full rounded-md bg-white p-2 shadow-sm" :style="{ backgroundColor: '#ffffff' }">
          <strong class="line-clamp-2 text-[10px] leading-4 text-slate-700">{{ slide.title }}</strong>
          <div class="mt-2 h-1.5 w-3/4 rounded bg-blue-100" /><div class="mt-1 h-1.5 w-1/2 rounded bg-slate-100" />
        </div>
      </template>
      <template v-else-if="slide.status === 'error'">
        <div class="flex h-full items-center justify-center text-center text-[10px] leading-4 text-rose-500">本页生成失败<br>可稍后重试</div>
      </template>
      <template v-else>
        <div class="h-2 w-2/3 rounded bg-slate-200" /><div class="mt-3 h-1.5 w-full rounded bg-slate-200" /><div class="mt-1.5 h-1.5 w-4/5 rounded bg-slate-100" />
      </template>
    </div>
  </button>
</template>


