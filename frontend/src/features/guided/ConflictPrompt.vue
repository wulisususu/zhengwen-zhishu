<script setup lang="ts">
// ConflictPrompt.vue — 409 (revision_conflict) UI prompt.
// Server truth was already refetched by the store; this just asks the user to
// acknowledge and continue with the refreshed state.
import { useGuidedPlanner } from './useGuidedPlanner'

const store = useGuidedPlanner()
</script>

<template>
  <div
    v-if="store.conflict"
    class="fixed inset-x-0 bottom-4 z-50 flex justify-center px-4"
    role="alertdialog"
    aria-modal="false"
    aria-label="版本冲突"
  >
    <div class="w-full max-w-lg rounded-xl border border-amber-300 bg-amber-50 p-4 shadow-lg">
      <h3 class="text-sm font-semibold text-amber-900">检测到版本冲突 (409)</h3>
      <p class="mt-1 text-sm text-amber-800">
        该引导项目已在服务端被更新（服务端版本 r{{ store.conflict.serverRevision }}）。我们已自动拉取最新状态，请基于最新内容继续操作。
      </p>
      <div class="mt-3 flex justify-end gap-2">
        <button
          type="button"
          class="rounded-lg bg-amber-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-800"
          @click="store.resolveConflict()"
        >
          使用最新状态继续
        </button>
      </div>
    </div>
  </div>
</template>
