<script setup lang="ts">
import { ref } from "vue";
import { RouterLink } from "vue-router";
import { TriangleAlert } from "lucide-vue-next";
import CitationChip from "./CitationChip.vue";
import StatusTag from "../common/StatusTag.vue";
import type { Citation, QaTurn } from "../../types";

const props = defineProps<{ turn: QaTurn; citations: Record<string, Citation>; selectedCitationId: string }>();
const emit = defineEmits<{ (e: "cite", id: string): void; (e: "rephrase"): void }>();

const copied = ref(false);

function plainText(): string {
  return props.turn.answer.sections
    .map((s) => `${s.heading}：${s.segments.map((seg) => (seg.kind === "text" ? seg.text : seg.label)).join("")}`)
    .join("\n");
}

async function copy() {
  try {
    await navigator.clipboard.writeText(plainText());
    copied.value = true;
    setTimeout(() => (copied.value = false), 2000);
  } catch {
    copied.value = false;
  }
}
</script>

<template>
  <div class="gov-turn">
    <div class="gov-turn__q">
      <span class="gov-turn__avatar" aria-hidden="true">问</span>
      <div class="gov-turn__q-text">
        <span class="gov-turn__question">{{ turn.question }}</span>
        <span class="gov-muted">{{ turn.askedAt }}</span>
      </div>
    </div>

    <article class="gov-answer" :class="`gov-answer--${turn.answer.kind}`">
      <div class="gov-answer__badges">
        <span class="gov-answer__label">回答</span>
        <StatusTag v-for="b in turn.answer.badges" :key="b.label" :tone="b.tone" :label="b.label" />
      </div>

      <div
        v-for="(section, si) in turn.answer.sections"
        :key="si"
        class="gov-answer__section"
        :class="`gov-answer__section--${section.tone}`"
      >
        <TriangleAlert v-if="section.tone === 'danger' || turn.answer.kind === 'no_basis'" :size="18" class="gov-answer__icon" aria-hidden="true" />
        <div class="gov-answer__section-body">
          <h3 class="gov-answer__heading">{{ section.heading }}</h3>
          <p class="gov-answer__text">
            <template v-for="(seg, i) in section.segments" :key="i">
              <CitationChip
                v-if="seg.kind === 'cite'"
                :label="seg.label"
                :status="citations[seg.citationId]?.status ?? 'unverified'"
                :selected="selectedCitationId === seg.citationId"
                @open="emit('cite', seg.citationId)"
              />
              <template v-else>{{ seg.text }}</template>
            </template>
          </p>
        </div>
      </div>

      <div v-if="turn.answer.lowRelevance?.length" class="gov-answer__low">
        <span class="gov-answer__heading">相关度较低的检索结果（未达可信阈值 {{ turn.answer.threshold }}，不作为依据）</span>
        <div v-for="hit in turn.answer.lowRelevance" :key="hit.title" class="gov-answer__hit">
          <span>{{ hit.title }}</span>
          <span class="gov-muted">相关度 {{ hit.score.toFixed(2) }}</span>
        </div>
      </div>

      <footer class="gov-answer__foot">
        <span class="gov-muted">{{ turn.answer.meta }}</span>
        <div class="gov-answer__actions">
          <template v-if="turn.answer.kind === 'no_basis'">
            <RouterLink to="/gov/library" class="gov-btn gov-btn--sm">前往政策库补充</RouterLink>
            <button type="button" class="gov-btn gov-btn--sm" @click="emit('rephrase')">换个问法</button>
            <button type="button" class="gov-btn gov-btn--sm" disabled title="人工核实流程待接入后端">提交人工核实（待接入）</button>
          </template>
          <template v-else-if="turn.answer.kind === 'grounded'">
            <button type="button" class="gov-btn gov-btn--sm" @click="copy">{{ copied ? "已复制" : "复制回答" }}</button>
            <RouterLink to="/gov/draft" class="gov-btn gov-btn--sm gov-btn--outline">前往公文起草</RouterLink>
          </template>
        </div>
      </footer>
    </article>
  </div>
</template>

<style scoped>
.gov-turn { display: flex; flex-direction: column; gap: 12px; }
.gov-turn__q { display: flex; gap: 12px; align-items: flex-start; }
.gov-turn__avatar {
  flex: 0 0 28px; width: 28px; height: 28px; border-radius: 14px; background: var(--gov-primary-100); color: var(--gov-primary);
  font-size: 13px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center;
}
.gov-turn__q-text { display: flex; flex-direction: column; gap: 2px; padding-top: 3px; min-width: 0; }
.gov-turn__question { font-size: 15px; font-weight: 500; line-height: 22px; }
.gov-answer { background: var(--gov-surface); border: 1px solid var(--gov-border); border-radius: var(--gov-r-lg); padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; }
.gov-answer__badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.gov-answer__label { font-size: 13px; font-weight: 700; color: var(--gov-text-2); }
.gov-answer__section { display: flex; gap: 10px; }
.gov-answer__section-body { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.gov-answer__icon { flex: 0 0 18px; margin-top: 2px; }
.gov-answer__heading { margin: 0; font-size: 14px; font-weight: 700; }
.gov-answer__text { margin: 0; font-size: 14px; line-height: 26px; }
.gov-answer__section--muted .gov-answer__text { color: var(--gov-text-2); }
.gov-answer__section--note { padding: 12px 14px; border-radius: var(--gov-r-md); background: var(--gov-surface-2); border: 1px solid var(--gov-border); }
.gov-answer__section--note .gov-answer__text { font-size: 13px; line-height: 20px; color: var(--gov-text-2); }
.gov-answer__section--danger { padding: 12px 14px; border-radius: var(--gov-r-md); background: var(--gov-red-50); border: 1px solid var(--gov-red-200); color: var(--gov-red); }
.gov-answer__section--danger .gov-answer__text { color: var(--gov-text-1); }
.gov-answer--no_basis .gov-answer__section:first-of-type,
.gov-answer--unavailable .gov-answer__section:first-of-type {
  padding: 16px; border-radius: var(--gov-r-md); background: var(--gov-warn-50); border: 1px solid var(--gov-warn-200); color: var(--gov-warn);
}
.gov-answer--no_basis .gov-answer__text,
.gov-answer--unavailable .gov-answer__text { color: var(--gov-text-2); font-size: 13px; line-height: 21px; }
.gov-answer__low { display: flex; flex-direction: column; gap: 8px; }
.gov-answer__hit { display: flex; justify-content: space-between; gap: 12px; padding: 10px 12px; border: 1px dashed var(--gov-border-strong); border-radius: var(--gov-r-md); font-size: 13px; color: var(--gov-text-2); }
.gov-answer__foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding-top: 12px; border-top: 1px solid var(--gov-border); }
.gov-answer__actions { display: flex; gap: 8px; flex-wrap: wrap; }
</style>
