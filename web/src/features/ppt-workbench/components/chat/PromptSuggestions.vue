<script setup lang="ts">
defineProps<{ suggestions: string[] }>();
defineEmits<{ select: [prompt: string] }>();
</script>

<template>
  <div class="flex flex-wrap justify-center gap-2.5" aria-label="PPT 快捷需求">
    <button
      v-for="suggestion in suggestions"
      :key="suggestion"
      type="button"
      data-prompt-suggestion
      class="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700"
      @click="$emit('select', suggestion)"
    >
      {{ suggestion }}
    </button>
  </div>
</template>
