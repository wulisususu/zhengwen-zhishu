<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ExternalLink } from "lucide-vue-next";
import { getGovOfficeAdapter } from "../../adapters";
import type { OfficialDocument, PolicyDetail, PolicyDocument, PolicyHit, PolicyStatus } from "../../types";
import { POLICY_STATUS_LABELS } from "../../domain/docTypes";

const props = withDefaults(defineProps<{ documentId?: string; initialPolicyId?: number; selectable?: boolean }>(), { selectable: true });
const emit = defineEmits<{ select: [id: string] }>();
const api = getGovOfficeAdapter();
const keyword = ref(""); const includeUnverified = ref(false); const includeAbolished = ref(false);
const policies = ref<PolicyDocument[]>([]); const hits = ref<PolicyHit[]>([]); const total = ref(0);
const detail = ref<PolicyDetail | null>(null); const error = ref(""); const notice = ref(""); const loading = ref(false);
const docs = ref<OfficialDocument[]>([]); const target = ref(""); const admin = ref(false);
const importUrl = ref(""); const importTitle = ref(""); const importSource = ref<File | null>(null);
const verifyStatus = ref<PolicyStatus>("unverified"); const verifyNote = ref(""); const writing = ref(false);
let queryRevision = 0; let detailRevision = 0;
const message = (e: unknown) => e instanceof Error ? e.message : "政策操作失败，请稍后重试";
const sourceLink = (url: string) => /^https?:\/\//i.test(url) ? url : "";

async function search() {
  const revision = ++queryRevision; loading.value = true; error.value = "";
  const query = keyword.value.trim();
  const statuses: PolicyStatus[] = ["current"];
  if (includeUnverified.value) statuses.push("unverified");
  if (includeAbolished.value) statuses.push("abolished");
  try {
    if (!api.listPolicies || !api.searchPolicies) throw new Error("政策库尚未接入");
    const [list, clauses] = await Promise.all([api.listPolicies(query), query ? api.searchPolicies(query, statuses) : Promise.resolve({ hits: [] })]);
    if (revision !== queryRevision) return;
    policies.value = list.items; total.value = list.total; hits.value = clauses.hits;
  } catch (e) { if (revision === queryRevision) error.value = message(e); }
  finally { if (revision === queryRevision) loading.value = false; }
}
async function open(id: number) {
  const revision = ++detailRevision; error.value = "";
  try {
    if (!api.getPolicy) throw new Error("政策详情尚未接入");
    const result = await api.getPolicy(id);
    if (revision === detailRevision) { detail.value = result; verifyStatus.value = result.policy.verified_status; verifyNote.value = ""; }
  } catch (e) { if (revision === detailRevision) error.value = message(e); }
}
async function select(id: string) {
  if (!props.selectable || writing.value) return;
  if (props.documentId) { emit("select", id); return; }
  if (!target.value) { error.value = "请先选择要加入的文稿"; return; }
  writing.value = true; error.value = "";
  try {
    if (!api.selectCitations) throw new Error("文稿引用接口尚未接入");
    const doc = await api.getDocument(target.value);
    await api.selectCitations(doc.id, [...new Set([...doc.policyRefs.map(p => p.id), id])]);
    notice.value = "政策条款已保存到文稿，刷新后仍可查看。";
  } catch (e) { error.value = message(e); }
  finally { writing.value = false; }
}
async function importPolicy() {
  if (writing.value) return;
  writing.value = true; error.value = ""; notice.value = "";
  try {
    if (!api.importPolicy) throw new Error("政策导入尚未接入");
    const form = new FormData();
    if (importSource.value) { form.append("file", importSource.value); if (importUrl.value.trim()) form.append("source_url", importUrl.value.trim()); }
    else form.append("url", importUrl.value.trim());
    if (importTitle.value.trim()) form.append("title", importTitle.value.trim());
    const result = await api.importPolicy(form);
    notice.value = "政策已入库；新版本状态为未核验，须人工核对后方可标记现行。";
    if (result.extraction) notice.value += ` PDF 共 ${result.extraction.page_count} 页，${result.extraction.fallback ? '已使用原 OCR 回退链路' : '文字层解析完成'}。${result.extraction.warnings.join('；')}`;
    await search(); await open(result.policy.id);
  } catch (e) { error.value = message(e); }
  finally { writing.value = false; }
}
async function verify() {
  if (!detail.value || !verifyNote.value.trim() || writing.value) return;
  writing.value = true; error.value = "";
  try {
    if (!api.verifyPolicy) throw new Error("政策核验尚未接入");
    await api.verifyPolicy(detail.value.policy.id, verifyStatus.value, verifyNote.value.trim());
    await open(detail.value.policy.id); await search(); notice.value = "人工核验记录已保存。";
  } catch (e) { error.value = message(e); }
  finally { writing.value = false; }
}
function chooseFile(event: Event) { importSource.value = (event.target as HTMLInputElement).files?.[0] ?? null; }
onMounted(async () => {
  await search();
  try {
    const actor = await api.getCurrentActor(); admin.value = actor.roles.includes("reviewer");
    if (!props.documentId) docs.value = (await api.listDocuments()).filter(d => d.authorAccount === actor.account && ["draft", "returned"].includes(d.status));
    if (props.initialPolicyId) await open(props.initialPolicyId);
  } catch (e) { error.value = message(e); }
});
</script>

<template>
  <section class="policy-library" aria-label="真实政策库">
    <p class="gov-muted">检索已入库政策及条款，保留原文和来源。条款检索默认仅含已人工核验的现行政策；文件列表同时展示未核验政策。本页不生成政策结论。</p>
    <form data-testid="policy-search" class="policy-search" @submit.prevent="search">
      <label class="gov-label">检索词<input v-model="keyword" class="gov-input" aria-label="政策检索词" maxlength="100" placeholder="政策标题或条款关键词" /></label>
      <label><input v-model="includeUnverified" type="checkbox" />条款包含未核验</label>
      <label><input v-model="includeAbolished" type="checkbox" />条款包含已废止</label>
      <button class="gov-btn gov-btn--primary" type="submit">搜索政策</button>
      <span v-if="loading" role="status">正在检索…</span>
    </form>
    <div v-if="error" class="gov-banner gov-banner--danger" role="alert">{{ error }}</div>
    <div v-if="notice" class="gov-banner gov-banner--info" role="status">{{ notice }}</div>
    <label v-if="!documentId" class="gov-label">引用目标文稿
      <select v-model="target" class="gov-select" aria-label="引用目标文稿"><option value="">请选择自己的可编辑文稿</option><option v-for="doc in docs" :key="doc.id" :value="doc.id">{{ doc.title }}</option></select>
    </label>
    <div class="policy-columns">
      <div class="policy-list">
        <h2>政策文件（{{ total }}）</h2>
        <p v-if="total > policies.length" class="gov-muted">显示前 {{ policies.length }} 份，请输入关键词缩小范围。</p>
        <button v-for="p in policies" :key="p.id" :data-testid="`policy-open-${p.id}`" class="policy-card" type="button" @click="open(p.id)">
          <strong>{{ p.title }}</strong><span>{{ p.doc_number || '文号未录入' }} · {{ p.issuer || '机关未录入' }}</span>
          <span>{{ POLICY_STATUS_LABELS[p.verified_status] }} · 第 {{ p.version }} 版</span>
        </button>
        <p v-if="!loading && !policies.length">没有匹配的政策文件。管理员可从官方网址或文件导入。</p>
        <h2 v-if="keyword.trim()">条款命中（{{ hits.length }}）</h2>
        <article v-for="hit in hits" :key="hit.citation_id" class="policy-card">
          <button class="gov-btn gov-btn--text" type="button" @click="open(hit.policy_id)">{{ hit.policy_title }} · {{ hit.clause }}</button>
          <span>{{ POLICY_STATUS_LABELS[hit.status] }}</span>
          <p>{{ hit.excerpt.before }}<mark>{{ hit.excerpt.highlight }}</mark>{{ hit.excerpt.after }}</p>
          <button type="button" class="gov-btn" :disabled="!selectable || writing" @click="select(hit.citation_id)">加入文稿</button>
        </article>
        <p v-if="keyword.trim() && !loading && !hits.length">所选状态中未检出条款；可调整关键词或勾选未核验政策。</p>
      </div>
      <article v-if="detail" class="policy-detail" aria-label="政策原文条款">
        <header class="policy-detail__header">
          <div class="policy-detail__heading">
            <h2>{{ detail.policy.title }}</h2>
            <p class="gov-muted">{{ POLICY_STATUS_LABELS[detail.policy.verified_status] }} · 第 {{ detail.policy.version }} 版 · {{ detail.policy.publish_date || '发布日期未录入' }}</p>
          </div>
          <div v-if="sourceLink(detail.policy.url)" class="policy-detail__source">
            <a class="gov-btn gov-btn--primary policy-source-button" :href="sourceLink(detail.policy.url)" target="_blank" rel="noopener noreferrer">
              <ExternalLink :size="18" aria-hidden="true" />打开官方原文
            </a>
            <span class="gov-muted">在新窗口打开，核对原始文件</span>
          </div>
        </header>
        <p v-if="detail.policy.is_current === false" class="gov-banner gov-banner--danger">历史版本：已被替代，仅供历史对照；请查看最新版本并重新核验。</p>
        <p v-if="detail.policy.status_note">核验说明：{{ detail.policy.status_note }}</p>
        <p v-if="!sourceLink(detail.policy.url)" class="gov-muted">文件上传来源（内容哈希定位）：{{ detail.policy.url }}</p>
        <p v-if="!detail.clauses.length">尚无全文条款；管理员需导入政策正文。检索摘要不作为全文。</p>
        <section v-for="clause in detail.clauses" :key="clause.id" class="policy-clause">
          <p v-if="clause.page_number" class="gov-muted">PDF 第 {{ clause.page_number }} 页 · {{ clause.source_anchor }}</p>
          <p class="policy-text">{{ clause.content }}</p><p v-if="clause.needs_review" class="gov-muted">条款切分待人工复核</p>
          <button :data-testid="`select-clause-${clause.id}`" type="button" class="gov-btn" :disabled="!selectable || writing" @click="select(`clause:${clause.id}`)">加入文稿</button>
        </section>
        <form v-if="admin" class="policy-verify" @submit.prevent="verify">
          <h3>人工核验</h3><p class="gov-muted">请核对原始来源和有效性后再保存；系统不会自动判定现行。</p>
          <label class="gov-label">核验状态<select v-model="verifyStatus" class="gov-select" aria-label="核验状态"><option value="unverified">未核验</option><option value="current">现行</option><option value="abolished">已废止</option></select></label>
          <label class="gov-label">核验依据与说明<input v-model="verifyNote" class="gov-input" required maxlength="500" aria-label="核验依据与说明" /></label>
          <button type="submit" class="gov-btn" :disabled="writing || !verifyNote.trim()">保存人工核验</button>
        </form>
      </article>
      <p v-else class="gov-muted">选择政策文件，查看完整条款、来源和版本。</p>
    </div>
    <details v-if="admin" data-testid="policy-import">
      <summary>管理员导入政策</summary>
      <form class="policy-import" @submit.prevent="importPolicy">
        <label class="gov-label">政策原文网址<input v-model="importUrl" class="gov-input" aria-label="政策原文网址" type="url" placeholder="https://www.gov.cn/…；内网模式可上传文件" /></label>
        <label class="gov-label">政策标题（可选）<input v-model="importTitle" class="gov-input" aria-label="导入政策标题" maxlength="300" /></label>
        <label class="gov-label">上传政策文件<input type="file" aria-label="上传政策文件" accept=".txt,.md,.html,.htm,.docx,.pdf" @change="chooseFile" /></label>
        <p class="gov-muted">支持 TXT、Markdown、HTML、DOCX、PDF，最多 10 MB。文字 PDF 保留页码；扫描件使用原 OCR 链路。导入后需人工核验，内网模式可离线导入。</p>
        <button type="submit" class="gov-btn" :disabled="writing || (!importSource && !importUrl.trim())">{{ writing ? '处理中…' : '导入政策' }}</button>
      </form>
    </details>
  </section>
</template>

<style scoped>
.policy-library { padding: 20px; overflow: auto; display: flex; flex-direction: column; gap: 16px; min-height: 0; }
.policy-search { display: flex; gap: 12px; flex-wrap: wrap; align-items: end; }.policy-search > label:first-child { flex: 1; min-width: 200px; }
.policy-columns { display: grid; grid-template-columns: minmax(240px, 1fr) minmax(300px, 1.5fr); gap: 24px; align-items: start; }
.policy-list { display: flex; flex-direction: column; gap: 10px; }.policy-card { display: flex; flex-direction: column; gap: 8px; padding: 12px; text-align: left; border: 1px solid var(--gov-border); border-radius: 8px; background: var(--gov-surface); color: inherit; overflow-wrap: anywhere; }
.policy-detail { min-width: 0; }.policy-clause { border-bottom: 1px solid var(--gov-border); padding: 14px 0; }.policy-text { white-space: pre-wrap; line-height: 1.8; overflow-wrap: anywhere; }
.policy-detail__header { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 16px; padding: 16px; margin-bottom: 12px; border: 1px solid var(--gov-border); border-radius: 8px; background: var(--gov-surface); }
.policy-detail__heading { flex: 1 1 260px; min-width: 0; overflow-wrap: anywhere; }
.policy-detail__heading h2 { margin-bottom: 8px; line-height: 1.6; }
.policy-detail__source { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
.policy-detail__source > span { font-size: 12px; }
.policy-source-button { min-height: 42px; min-width: 160px; padding: 0 18px; text-decoration: none; font-weight: 600; }
.policy-import,.policy-verify { display: flex; flex-direction: column; gap: 12px; padding: 16px 0; }h2 { font-size: 16px; }h3 { font-size: 14px; }p { line-height: 1.6; }
@media(max-width: 900px) { .policy-columns { grid-template-columns: 1fr; } }
</style>
