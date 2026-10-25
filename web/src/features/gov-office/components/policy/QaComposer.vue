<script setup lang="ts">
import { ref } from "vue";
import type { AskOptions } from "../../types";

const props = defineProps<{ busy: boolean }>();
const emit = defineEmits<{ (e: "ask", question: string, options: AskOptions): void }>();

const question = ref("");
const scope = ref<AskOptions["scope"]>("current");
const excludeAbolished = ref(true);
const hint = ref("");

function ask() {
  if (!question.value.trim()) {
    hint.value = "请先输入问题。";
    return;
  }
  hint.value = "";
  emit("ask", question.value, { scope: scope.value, excludeAbolished: excludeAbolished.value });
  question.value = "";
}

function setQuestion(text: string) {
  question.value = text;
  document.getElementById("gov-qa-input")?.focus();
}
defineExpose({ setQuestion });
</script>

<template>
  <form class="gov-composer" @submit.prevent="ask">
    <label for="gov-qa-input" class="gov-composer__label">输入政策问题</label>
    <textarea
      id="gov-qa-input"
      v-model="question"
      class="gov-textarea"
      rows="2"
      placeholder="例如：申请首次贷款贴息需要准备哪些材料？"
      @keydown.enter.exact.prevent="ask"
    />
    <div class="gov-composer__row">
      <label class="gov-composer__opt">
        检索范围
        <select v-model="scope" class="gov-select">
          <option value="current">全部现行政策</option>
          <option value="all">全部政策（含已废止）</option>
          <option value="picked">仅指定政策</option>
        </select>
      </label>
      <label class="gov-composer__opt">
        <input v-model="excludeAbolished" type="checkbox" />
        不引用已废止政策作为依据
      </label>
      <span v-if="hint" role="alert" class="gov-composer__hint">{{ hint }}</span>
      <span style="flex: 1 1 auto" />
      <button type="submit" class="gov-btn gov-btn--primary" :disabled="props.busy">{{ props.busy ? "提交中…" : "提问" }}</button>
    </div>
  </form>
</template>

<style scoped>
.gov-composer { display: flex; flex-direction: column; gap: 8px; max-width: 880px; margin: 0 auto; width: 100%; }
.gov-composer__label { font-size: 13px; font-weight: 500; color: var(--gov-text-2); }
.gov-composer__row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.gov-composer__opt { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--gov-text-2); white-space: nowrap; }
.gov-composer__hint { font-size: 12px; color: var(--gov-red); }
</style>
