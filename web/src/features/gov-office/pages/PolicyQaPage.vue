<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { MessagesSquare, PanelRightOpen } from "lucide-vue-next";
import GovLayout from "../components/layout/GovLayout.vue";
import GovPageHeader from "../components/layout/GovPageHeader.vue";
import AnswerBlock from "../components/policy/AnswerBlock.vue";
import EvidencePanel from "../components/policy/EvidencePanel.vue";
import QaComposer from "../components/policy/QaComposer.vue";
import QaSessionList from "../components/policy/QaSessionList.vue";
import { COMPACT_BELOW, useViewport } from "../composables/useViewport";
import { usePolicyQaStore } from "../stores/policyQa";
import type { AskOptions } from "../types";
import { getGovOfficeAdapter } from "../adapters";
import PolicyLibraryPanel from "../components/policy/PolicyLibraryPanel.vue";

const isLive = getGovOfficeAdapter().mode === "http";

const qa = usePolicyQaStore();
const { width } = useViewport();
const compact = computed(() => width.value < COMPACT_BELOW);

const historyOpen = ref(true);
const evidenceOpen = ref(true);
const scroller = ref<HTMLElement | null>(null);
const composer = ref<InstanceType<typeof QaComposer> | null>(null);

const session = computed(() => qa.activeSession);
const citationIds = computed(() => [...new Set(session.value?.turns.flatMap((t) => t.answer.citationIds) ?? [])]);

onMounted(() => {
  if (isLive) return;
  historyOpen.value = !compact.value;
  qa.load();
});
watch(compact, (isCompact) => {
  if (isCompact) historyOpen.value = false;
});

function selectSession(id: string) {
  qa.selectSession(id);
  if (compact.value) historyOpen.value = false;
}

function openCitation(id: string) {
  qa.selectCitation(id);
  evidenceOpen.value = true;
}

async function ask(question: string, options: AskOptions) {
  await qa.ask(question, options);
  await nextTick();
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: "smooth" });
}
</script>

<template>
  <GovLayout>
    <template v-if="isLive">
      <GovPageHeader title="政策检索" subtitle="检索真实政策库、查看原文条款，并将可追溯依据保存到文稿" />
      <PolicyLibraryPanel />
    </template>
    <template v-else>
    <GovPageHeader title="政策问答" subtitle="仅基于已入库政策检索作答，结论附条款依据；无可靠依据时不生成结论" />

    <div class="gov-qa">
      <aside v-if="historyOpen" class="gov-qa__history" :class="{ 'is-overlay': compact }">
        <QaSessionList
          :sessions="qa.sessions"
          :active-id="qa.activeSessionId"
          @select="selectSession"
          @new="qa.newSession(); historyOpen = !compact"
          @collapse="historyOpen = false"
        />
      </aside>
      <div v-if="historyOpen && compact" class="gov-qa__scrim" aria-hidden="true" @click="historyOpen = false" />

      <section class="gov-qa__main" aria-label="问答区">
        <div class="gov-qa__bar">
          <button v-if="!historyOpen" type="button" class="gov-btn gov-btn--sm" @click="historyOpen = true">
            <MessagesSquare :size="14" aria-hidden="true" />会话记录（{{ qa.sessions.length }}）
          </button>
          <span class="gov-qa__session-title">{{ session?.title }}</span>
          <button v-if="!evidenceOpen" type="button" class="gov-btn gov-btn--sm" @click="evidenceOpen = true">
            <PanelRightOpen :size="14" aria-hidden="true" />引用依据（{{ citationIds.length }}）
          </button>
        </div>
        <div ref="scroller" class="gov-qa__scroll">
          <div class="gov-qa__turns">
            <AnswerBlock
              v-for="turn in session?.turns ?? []"
              :key="turn.id"
              :turn="turn"
              :citations="qa.citations"
              :selected-citation-id="qa.selectedCitationId"
              @cite="openCitation"
              @rephrase="composer?.setQuestion('本市人才公寓补贴对申请人的户籍有何要求？')"
            />
            <div v-if="session && !session.turns.length" class="gov-empty">新会话：在下方输入政策问题。回答将仅引用已入库政策。</div>
            <div v-if="qa.error" class="gov-banner gov-banner--danger" role="alert">{{ qa.error }}</div>
          </div>
        </div>
        <div class="gov-qa__composer">
          <QaComposer ref="composer" :busy="qa.asking" @ask="ask" />
        </div>
      </section>

      <aside v-if="evidenceOpen" class="gov-qa__evidence">
        <EvidencePanel
          :citation-ids="citationIds"
          :citations="qa.citations"
          :selected-id="qa.selectedCitationId"
          @select="qa.selectCitation"
          @back="qa.clearCitation()"
          @collapse="evidenceOpen = false"
        />
      </aside>
    </div>
    </template>
  </GovLayout>
</template>

<style scoped>
.gov-qa { position: relative; flex: 1 1 auto; min-height: 0; display: flex; }
.gov-qa__history { flex: 0 0 240px; width: 240px; border-right: 1px solid var(--gov-border); min-height: 0; }
.gov-qa__history.is-overlay { position: absolute; z-index: 20; top: 0; bottom: 0; left: 0; box-shadow: var(--gov-sh-3); }
.gov-qa__scrim { position: absolute; inset: 0; z-index: 10; background: rgba(16, 36, 63, 0.18); }
.gov-qa__main { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
.gov-qa__bar { flex: 0 0 auto; display: flex; align-items: center; gap: 10px; padding: 8px 24px; min-height: 44px; border-bottom: 1px solid var(--gov-border); background: var(--gov-surface-2); }
.gov-qa__session-title { flex: 1 1 auto; min-width: 0; font-size: 13px; color: var(--gov-text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gov-qa__scroll { flex: 1 1 auto; overflow-y: auto; padding: 24px; }
.gov-qa__turns { max-width: 880px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }
.gov-qa__composer { flex: 0 0 auto; padding: 12px 24px 16px; border-top: 1px solid var(--gov-border); background: var(--gov-surface); }
.gov-qa__evidence { flex: 0 0 344px; width: 344px; border-left: 1px solid var(--gov-border); min-height: 0; }
</style>
