<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { FileCheck, FilePen, MessageSquare, ShieldCheck } from "lucide-vue-next";
import GovLayout from "../components/layout/GovLayout.vue";
import GovPageHeader from "../components/layout/GovPageHeader.vue";
import StatusTag from "../components/common/StatusTag.vue";
import { getGovOfficeAdapter } from "../adapters";
import { docTypeConfig, STATUS_LABELS, STATUS_TONES } from "../domain/docTypes";
import { summarizeIssues } from "../domain/issueRules";
import { useGovDocumentsStore } from "../stores/govDocuments";
import { useGovSessionStore } from "../stores/govSession";
import type { PolicyStats } from "../types";

const store = useGovDocumentsStore();
const session = useGovSessionStore();
const policyStats = ref<PolicyStats | null>(null);
const policyError = ref("");

onMounted(async () => {
  try { policyStats.value = await getGovOfficeAdapter().getPolicyStats(); }
  catch { policyError.value = "政策库读取失败，请稍后重试"; }
});

const docs = computed(() => store.list);
const kpis = computed(() => {
  const summaries = docs.value.map((d) => summarizeIssues(d));
  const openIssues = summaries.reduce((n, s) => n + s.unresolved.length, 0);
  const pending = docs.value.filter((d) => d.status === "pending");
  const pendingBlocked = pending.filter((d) => summarizeIssues(d).blockers.length > 0).length;
  return [
    {
      label: "入库政策",
      value: policyStats.value && policyStats.value.available !== false ? String(policyStats.value.total) : "—",
      unit: "件",
      sub: policyStats.value?.available === false ? "政策检索未接入" : policyStats.value
        ? `现行 ${policyStats.value.current} · 已废止 ${policyStats.value.abolished} · 待核实 ${policyStats.value.unverified}`
        : policyError.value || "读取中…",
    },
    { label: "待审核文稿", value: String(pending.length), unit: "份", sub: `其中 ${pendingBlocked} 份存在阻断审批的严重问题` },
    { label: "文稿总数", value: String(docs.value.length), unit: "份", sub: "草稿、待审核、退回与已通过" },
    { label: "未处理审校问题", value: session.isDemo ? String(openIssues) : "—", unit: "项", sub: session.isDemo ? "含规则检查与 AI 语义审查" : "自动审校未接入" },
  ];
});
const recent = computed(() => docs.value.slice(0, 6));
const entries = [
  { to: "/gov/policy-qa", title: "政策检索", desc: "检索政策条款，查看来源并保存文稿依据", icon: MessageSquare },
  { to: "/gov/draft", title: "公文起草", desc: "按文种模板起草，缺失要素自动标记", icon: FilePen },
  { to: "/gov/proofread", title: "文稿审校", desc: "规则检查与 AI 语义审查，问题定位", icon: FileCheck },
  { to: "/gov/review-center", title: "审核中心", desc: "待审核任务、通过与退回、审核记录", icon: ShieldCheck },
];

function entryFor(id: string, status: string) {
  if (status === "pending") return { to: "/gov/review-center", label: "去审核" };
  if (docTypeConfig(store.byId[id].docType).supported && (status === "draft" || status === "returned")) return { to: `/gov/draft/${id}`, label: "继续起草" };
  return { to: "/gov/proofread", label: "查看" };
}
</script>

<template>
  <GovLayout>
    <GovPageHeader title="工作台首页" :subtitle="session.isDemo ? '以下数字来自演示数据，不代表真实业务量' : ''" />
    <div class="gov-home">
      <section class="gov-home__kpis" aria-label="概览指标">
        <div v-for="k in kpis" :key="k.label" class="gov-card gov-home__kpi">
          <span class="gov-home__kpi-label">{{ k.label }}</span>
          <span class="gov-home__kpi-value">{{ k.value }}<span class="gov-home__kpi-unit">{{ k.unit }}</span></span>
          <span class="gov-muted">{{ k.sub }}</span>
        </div>
      </section>

      <div class="gov-home__grid">
        <section class="gov-card gov-home__tasks" aria-label="近期文稿">
          <div class="gov-home__card-head">
            <h2 class="gov-section-title">近期文稿</h2>
            <RouterLink to="/gov/proofread" class="gov-btn gov-btn--text gov-btn--sm">全部文稿</RouterLink>
          </div>
          <div v-for="d in recent" :key="d.id" class="gov-home__task">
            <div class="gov-home__task-main">
              <span class="gov-home__task-title">{{ d.title }}</span>
              <span class="gov-muted">{{ docTypeConfig(d.docType).label }} · {{ d.author }} · {{ d.createdAt }}</span>
            </div>
            <StatusTag :tone="STATUS_TONES[d.status]" :label="STATUS_LABELS[d.status]" />
            <RouterLink :to="entryFor(d.id, d.status).to" class="gov-btn gov-btn--sm">{{ entryFor(d.id, d.status).label }}</RouterLink>
          </div>
          <div v-if="!recent.length" class="gov-empty" style="margin: 16px">暂无文稿</div>
        </section>

        <section class="gov-card gov-home__entries" aria-label="快捷入口">
          <h2 class="gov-section-title">快捷入口</h2>
          <RouterLink v-for="e in entries" :key="e.to" :to="e.to" class="gov-home__entry">
            <span class="gov-home__entry-icon"><component :is="e.icon" :size="18" aria-hidden="true" /></span>
            <span class="gov-home__entry-text">
              <span class="gov-home__entry-title">{{ e.title }}</span>
              <span class="gov-muted">{{ e.desc }}</span>
            </span>
          </RouterLink>
        </section>
      </div>
    </div>
  </GovLayout>
</template>

<style scoped>
.gov-home { flex: 1 1 auto; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 20px; }
.gov-home__kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.gov-home__kpi { padding: 16px 20px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.gov-home__kpi-label { font-size: 13px; color: var(--gov-text-2); }
.gov-home__kpi-value { font-size: var(--gov-fs-display); font-weight: 700; line-height: 36px; }
.gov-home__kpi-unit { font-size: 13px; font-weight: 400; color: var(--gov-text-3); margin-left: 4px; }
.gov-home__grid { display: flex; flex-wrap: wrap; gap: 20px; align-items: flex-start; }
.gov-home__tasks { flex: 999 1 560px; min-width: 0; }
.gov-home__card-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 20px; border-bottom: 1px solid var(--gov-border); }
.gov-home__task { display: flex; align-items: center; gap: 12px; padding: 12px 20px; border-bottom: 1px solid var(--gov-border); }
.gov-home__task-main { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.gov-home__task-title { font-size: 14px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gov-home__entries { flex: 1 1 320px; min-width: 0; padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.gov-home__entry { display: flex; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--gov-border); border-radius: var(--gov-r-md); text-decoration: none; color: var(--gov-text-1); }
.gov-home__entry:hover { border-color: var(--gov-primary); }
.gov-home__entry-icon { width: 36px; height: 36px; flex: 0 0 36px; border-radius: var(--gov-r-md); background: var(--gov-primary-50); color: var(--gov-primary); display: inline-flex; align-items: center; justify-content: center; }
.gov-home__entry-text { display: flex; flex-direction: column; min-width: 0; }
.gov-home__entry-title { font-size: 14px; font-weight: 500; }
</style>
