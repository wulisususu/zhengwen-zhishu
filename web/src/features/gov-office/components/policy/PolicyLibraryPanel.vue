<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { BookOpen, ExternalLink, Search, Upload, X } from "lucide-vue-next";
import { getGovOfficeAdapter } from "../../adapters";
import type { OfficialDocument, PolicyDetail, PolicyDocument, PolicyHit, PolicyStats, PolicyStatus, Tone } from "../../types";
import { POLICY_STATUS_LABELS } from "../../domain/docTypes";
import StatusTag from "../common/StatusTag.vue";

type Filter = "all" | PolicyStatus;
type ImportMode = "file" | "url";
const props = withDefaults(defineProps<{ documentId?: string; initialPolicyId?: number; selectable?: boolean }>(), { selectable: true });
const emit = defineEmits<{ select: [id: string]; "import-available": [available: boolean] }>();
const api = getGovOfficeAdapter();
const FILTERS: { key: Filter; label: string }[] = [{ key: "all", label: "全部" }, { key: "unverified", label: "待核实" }, { key: "current", label: "现行" }, { key: "abolished", label: "已废止" }];
const STATUS_TONES: Record<PolicyStatus, Tone> = { current: "success", unverified: "warning", abolished: "danger" };
const keyword = ref(""); const filter = ref<Filter>("all"); const searched = ref(""); const tab = ref<"files" | "hits">("files");
const policies = ref<PolicyDocument[]>([]); const hits = ref<PolicyHit[]>([]); const total = ref(0); const page = ref(1); const stats = ref<PolicyStats | null>(null);
const detail = ref<PolicyDetail | null>(null); const error = ref(""); const notice = ref(""); const loading = ref(false);
const docs = ref<OfficialDocument[]>([]); const target = ref(""); const admin = ref(false);
const importOpen = ref(false); const importMode = ref<ImportMode>("file"); const importUrl = ref(""); const importTitle = ref("");
const importDocNumber = ref(""); const importIssuer = ref(""); const importSource = ref<File | null>(null); const importClose = ref<HTMLButtonElement | null>(null);
const verifyStatus = ref<PolicyStatus>("unverified"); const verifyNote = ref(""); const writing = ref(false);
let queryRevision = 0; let detailRevision = 0;
const message = (e: unknown) => e instanceof Error ? e.message : "政策操作失败，请稍后重试";
const sourceLink = (url: string) => /^https?:\/\//i.test(url) ? url : "";
const listStatuses = () => filter.value === "all" ? [] : [filter.value];
const clauseStatuses = (): PolicyStatus[] => filter.value === "all" ? ["current", "unverified", "abolished"] : [filter.value];
const count = (key: Filter) => !stats.value ? null : key === "all" ? stats.value.total : stats.value[key];
const hasMore = computed(() => policies.value.length < total.value);
const libraryEmpty = computed(() => !loading.value && !error.value && !searched.value && filter.value === "all" && total.value === 0);
const canImport = computed(() => admin.value && !props.documentId);
const showTarget = computed(() => !props.documentId && !admin.value);
const nextUnverified = computed(() => {
  if (!detail.value) return null;
  const at = policies.value.findIndex(p => p.id === detail.value?.policy.id);
  return [...policies.value.slice(at + 1), ...policies.value.slice(0, Math.max(at, 0))].find(p => p.verified_status === "unverified") ?? null;
});

async function loadStats() {
  try { stats.value = await api.getPolicyStats(); } catch { stats.value = null; }
}
async function search() {
  const revision = ++queryRevision; loading.value = true; error.value = "";
  const query = keyword.value.trim();
  try {
    if (!api.listPolicies || !api.searchPolicies) throw new Error("政策库尚未接入");
    const [list, clauses] = await Promise.all([api.listPolicies(query, { statuses: listStatuses() }), query ? api.searchPolicies(query, clauseStatuses()) : Promise.resolve({ hits: [] })]);
    if (revision !== queryRevision) return;
    policies.value = list.items; total.value = list.total; hits.value = clauses.hits; page.value = 1; searched.value = query;
    tab.value = query && clauses.hits.length ? "hits" : "files";
  } catch (e) { if (revision === queryRevision) error.value = message(e); }
  finally { if (revision === queryRevision) loading.value = false; }
}
async function loadMore() {
  if (!api.listPolicies || loading.value) return;
  const revision = queryRevision; loading.value = true;
  try {
    const list = await api.listPolicies(searched.value, { statuses: listStatuses(), page: page.value + 1 });
    if (revision !== queryRevision) return;
    policies.value = [...policies.value, ...list.items.filter(p => !policies.value.some(q => q.id === p.id))]; total.value = list.total; page.value += 1;
  } catch (e) { error.value = message(e); }
  finally { loading.value = false; }
}
function setFilter(key: Filter) { if (filter.value !== key) { filter.value = key; void search(); } }
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
  if (!target.value) { error.value = "请先在检索栏右侧选择要引用到的文稿"; return; }
  writing.value = true; error.value = "";
  try {
    if (!api.selectCitations) throw new Error("文稿引用接口尚未接入");
    const doc = await api.getDocument(target.value);
    await api.selectCitations(doc.id, [...new Set([...doc.policyRefs.map(p => p.id), id])]);
    notice.value = "政策条款已保存到文稿，刷新后仍可查看。";
  } catch (e) { error.value = message(e); }
  finally { writing.value = false; }
}
async function openImport(mode: ImportMode = "file") {
  if (!canImport.value) return;
  importMode.value = mode; importOpen.value = true;
  await nextTick(); importClose.value?.focus();
}
function closeImport() { if (!writing.value) importOpen.value = false; }
async function importPolicy() {
  if (writing.value) return;
  writing.value = true; error.value = ""; notice.value = "";
  try {
    if (!api.importPolicy) throw new Error("政策导入尚未接入");
    const form = new FormData();
    const url = importUrl.value.trim();
    if (importMode.value === "file" && importSource.value) { form.append("file", importSource.value); if (url) form.append("source_url", url); }
    else form.append("url", url);
    if (importTitle.value.trim()) form.append("title", importTitle.value.trim());
    if (importDocNumber.value.trim()) form.append("doc_number", importDocNumber.value.trim());
    if (importIssuer.value.trim()) form.append("issuer", importIssuer.value.trim());
    const result = await api.importPolicy(form);
    notice.value = "政策已入库；新版本状态为未核验，须人工核对后方可标记现行。";
    if (result.extraction) notice.value += ` PDF 共 ${result.extraction.page_count} 页，${result.extraction.fallback ? '已使用原 OCR 回退链路' : '文字层解析完成'}。${result.extraction.warnings.join('；')}`;
    importOpen.value = false; importSource.value = null; importUrl.value = ""; importTitle.value = ""; importDocNumber.value = ""; importIssuer.value = "";
    await Promise.all([search(), loadStats()]); await open(result.policy.id);
  } catch (e) { error.value = message(e); }
  finally { writing.value = false; }
}
async function verify() {
  if (!detail.value || !verifyNote.value.trim() || writing.value) return;
  writing.value = true; error.value = "";
  try {
    if (!api.verifyPolicy) throw new Error("政策核验尚未接入");
    await api.verifyPolicy(detail.value.policy.id, verifyStatus.value, verifyNote.value.trim());
    await open(detail.value.policy.id); await Promise.all([search(), loadStats()]); notice.value = "人工核验记录已保存。";
  } catch (e) { error.value = message(e); }
  finally { writing.value = false; }
}
function chooseFile(event: Event) { importSource.value = (event.target as HTMLInputElement).files?.[0] ?? null; }
function dropFile(event: DragEvent) { const file = event.dataTransfer?.files?.[0]; if (file) importSource.value = file; }
defineExpose({ openImport });
onMounted(async () => {
  await Promise.all([search(), loadStats()]);
  try {
    const actor = await api.getCurrentActor(); admin.value = actor.roles.includes("reviewer");
    emit("import-available", canImport.value);
    if (showTarget.value) docs.value = (await api.listDocuments()).filter(d => d.authorAccount === actor.account && ["draft", "returned"].includes(d.status));
    if (props.initialPolicyId) await open(props.initialPolicyId);
  } catch (e) { error.value = message(e); }
});
</script>

<template>
  <section class="policy-library" :class="{ 'policy-library--embedded': documentId }" aria-label="真实政策库">
    <form data-testid="policy-search" class="policy-toolbar" @submit.prevent="search">
      <label class="policy-toolbar__search">
        <Search :size="16" aria-hidden="true" />
        <input v-model="keyword" type="search" aria-label="政策检索词" maxlength="100" placeholder="政策标题、文号或条款关键词" />
      </label>
      <button class="gov-btn gov-btn--primary policy-toolbar__go" type="submit">搜索</button>
      <div class="policy-filters" role="group" aria-label="按核验状态筛选">
        <button v-for="f in FILTERS" :key="f.key" type="button" class="policy-filter" :class="{ 'policy-filter--on': filter === f.key }" :aria-pressed="filter === f.key" @click="setFilter(f.key)">
          {{ f.label }}<b v-if="count(f.key) !== null">{{ count(f.key) }}</b>
        </button>
      </div>
      <label v-if="showTarget" class="policy-toolbar__target">引用到
        <select v-model="target" class="gov-select" aria-label="引用目标文稿"><option value="">请选择自己的可编辑文稿</option><option v-for="doc in docs" :key="doc.id" :value="doc.id">{{ doc.title }}</option></select>
      </label>
      <span v-if="loading" class="gov-muted" role="status">正在检索…</span>
    </form>
    <div v-if="error" class="gov-banner gov-banner--danger policy-message" role="alert">{{ error }}</div>
    <div v-if="notice" class="gov-banner gov-banner--info policy-message" role="status">{{ notice }}</div>

    <section v-if="libraryEmpty" class="policy-empty" aria-label="政策库为空">
      <div class="policy-empty__inner">
        <span class="policy-empty__icon"><BookOpen :size="30" aria-hidden="true" /></span>
        <h2>政策库里还没有文件</h2>
        <p>导入政策原文后，起草人可以检索条款、加入文稿，政策问答也会依据这里的文件回答。</p>
        <div v-if="canImport" class="policy-empty__actions">
          <button type="button" class="gov-btn gov-btn--primary" @click="openImport('file')">上传政策文件</button>
          <button type="button" class="gov-btn" @click="openImport('url')">从官方网址导入</button>
        </div>
        <p v-else class="gov-muted">政策导入与核验由审核人负责，请联系审核人导入。</p>
        <ol class="policy-steps">
          <li><strong>导入</strong><span>上传 PDF、DOCX 等原文，或填写政府网站的政策网址。</span></li>
          <li><strong>核验</strong><span>对照官方原文确认是否现行，填写核验说明。导入的文件默认是「待核实」。</span></li>
          <li><strong>使用</strong><span>核验为现行的条款可以作为现行依据，被起草、审校和问答引用。</span></li>
        </ol>
      </div>
    </section>

    <div v-else class="policy-columns">
      <section class="policy-pane" aria-label="检索结果">
        <div class="policy-tabs" role="tablist">
          <button type="button" role="tab" :aria-selected="tab === 'files'" class="policy-tab" :class="{ 'policy-tab--on': tab === 'files' }" @click="tab = 'files'">政策文件 {{ total }}</button>
          <button v-if="searched" type="button" role="tab" :aria-selected="tab === 'hits'" class="policy-tab" :class="{ 'policy-tab--on': tab === 'hits' }" @click="tab = 'hits'">条款命中 {{ hits.length }}</button>
        </div>
        <div v-if="tab === 'files'" class="policy-pane__body policy-list">
          <button v-for="p in policies" :key="p.id" :data-testid="`policy-open-${p.id}`" class="policy-card" :class="{ 'policy-card--on': detail?.policy.id === p.id }" type="button" @click="open(p.id)">
            <strong>{{ p.title }}</strong><span class="policy-meta">{{ p.doc_number || '文号未录入' }} · {{ p.issuer || '机关未录入' }}</span>
            <span class="policy-card__status"><StatusTag :tone="STATUS_TONES[p.verified_status]" :label="POLICY_STATUS_LABELS[p.verified_status]" /><span class="policy-meta">第 {{ p.version }} 版<template v-if="p.publish_date"> · {{ p.publish_date }}</template></span></span>
          </button>
          <p v-if="!loading && !policies.length" class="gov-muted">没有符合条件的政策文件，可以换个关键词或状态。</p>
          <button v-if="hasMore" type="button" class="gov-btn policy-more" :disabled="loading" @click="loadMore">加载更多（已显示 {{ policies.length }} / {{ total }}）</button>
        </div>
        <div v-else class="policy-pane__body policy-list">
          <article v-for="hit in hits" :key="hit.citation_id" class="policy-card">
            <span class="policy-card__status"><button class="gov-btn gov-btn--text policy-hit-title" type="button" @click="open(hit.policy_id)">{{ hit.policy_title }} · {{ hit.clause }}</button><StatusTag :tone="STATUS_TONES[hit.status]" :label="POLICY_STATUS_LABELS[hit.status]" /></span>
            <p class="policy-excerpt">{{ hit.excerpt.before }}<mark>{{ hit.excerpt.highlight }}</mark>{{ hit.excerpt.after }}</p>
            <span><button type="button" class="gov-btn gov-btn--sm" :disabled="!selectable || writing" @click="select(hit.citation_id)">加入文稿</button></span>
          </article>
          <p v-if="!loading && !hits.length" class="gov-muted">所选状态中未检出条款；可以换个关键词或状态。</p>
        </div>
      </section>

      <article v-if="detail" class="policy-pane policy-detail" aria-label="政策原文条款">
        <header class="policy-detail__header">
          <div class="policy-detail__heading">
            <h2>{{ detail.policy.title }}</h2>
            <p class="policy-card__status"><StatusTag :tone="STATUS_TONES[detail.policy.verified_status]" :label="POLICY_STATUS_LABELS[detail.policy.verified_status]" /><span class="policy-meta">{{ detail.policy.doc_number || '文号未录入' }} · 第 {{ detail.policy.version }} 版 · {{ detail.policy.publish_date || '发布日期未录入' }} · 共 {{ detail.clauses.length }} 条</span></p>
          </div>
          <a v-if="sourceLink(detail.policy.url)" class="gov-btn gov-btn--primary policy-source-button" :href="sourceLink(detail.policy.url)" target="_blank" rel="noopener noreferrer" title="在新窗口打开，核对原始文件">
            <ExternalLink :size="16" aria-hidden="true" />打开官方原文
          </a>
        </header>
        <p v-if="detail.policy.is_current === false" class="gov-banner gov-banner--danger policy-detail__note">历史版本：已被替代，仅供历史对照；请查看最新版本并重新核验。</p>
        <p v-if="selectable && !admin && detail.policy.verified_status === 'unverified'" class="gov-banner gov-banner--warning policy-detail__note">这份政策尚未经人工核验。加入文稿后会作为未核验依据，审校时会提示核验。</p>
        <div class="policy-pane__body policy-detail__body">
          <p v-if="detail.policy.status_note" class="gov-muted">核验说明：{{ detail.policy.status_note }}</p>
          <p v-if="!sourceLink(detail.policy.url)" class="gov-muted">文件上传来源（内容哈希定位）：{{ detail.policy.url }}</p>
          <p v-if="!detail.clauses.length">尚无全文条款；管理员需导入政策正文。检索摘要不作为全文。</p>
          <section v-for="clause in detail.clauses" :key="clause.id" class="policy-clause">
            <div class="policy-clause__text">
              <p v-if="clause.page_number" class="policy-meta">PDF 第 {{ clause.page_number }} 页 · {{ clause.source_anchor }}</p>
              <p class="policy-text">{{ clause.content }}</p><p v-if="clause.needs_review" class="policy-meta">条款切分待人工复核</p>
            </div>
            <button :data-testid="`select-clause-${clause.id}`" type="button" class="gov-btn gov-btn--sm" :disabled="!selectable || writing" @click="select(`clause:${clause.id}`)">加入文稿</button>
          </section>
        </div>
        <form v-if="admin" class="policy-verify" aria-label="人工核验" @submit.prevent="verify">
          <strong>人工核验</strong>
          <div class="policy-seg" role="radiogroup" aria-label="核验状态">
            <label v-for="s in (['unverified', 'current', 'abolished'] as PolicyStatus[])" :key="s" :class="{ 'policy-seg--on': verifyStatus === s }"><input v-model="verifyStatus" type="radio" name="policy-verify-status" :value="s" />{{ { unverified: '未核验', current: '现行', abolished: '已废止' }[s] }}</label>
          </div>
          <input v-model="verifyNote" class="gov-input policy-verify__note" required maxlength="500" aria-label="核验依据与说明" placeholder="核验依据与说明（必填），如：已对照官网原文，现行有效" />
          <button type="submit" class="gov-btn gov-btn--primary" :disabled="writing || !verifyNote.trim()">保存核验</button>
          <button v-if="nextUnverified" type="button" class="gov-btn gov-btn--text" :disabled="writing" @click="open(nextUnverified.id)">下一份待核实 →</button>
        </form>
      </article>
      <div v-else class="policy-pane policy-placeholder"><p class="gov-muted">选择左侧政策文件，查看完整条款、来源和版本。</p></div>
    </div>

    <div v-if="importOpen" class="policy-drawer-mask" @click.self="closeImport">
      <aside data-testid="policy-import" class="policy-drawer" role="dialog" aria-modal="true" aria-labelledby="policy-import-title" @keydown.esc="closeImport">
        <header class="policy-drawer__head">
          <h2 id="policy-import-title">导入政策</h2>
          <button ref="importClose" type="button" class="gov-btn gov-btn--icon" aria-label="关闭导入" @click="closeImport"><X :size="18" aria-hidden="true" /></button>
        </header>
        <form class="policy-import" @submit.prevent="importPolicy">
          <div class="policy-drawer__body">
            <div class="policy-mode" role="tablist" aria-label="导入方式">
              <button type="button" role="tab" :aria-selected="importMode === 'file'" :class="{ 'policy-mode--on': importMode === 'file' }" @click="importMode = 'file'">上传文件</button>
              <button type="button" role="tab" :aria-selected="importMode === 'url'" :class="{ 'policy-mode--on': importMode === 'url' }" @click="importMode = 'url'">官方网址</button>
            </div>
            <template v-if="importMode === 'file'">
              <label class="policy-drop" @dragover.prevent @drop.prevent="dropFile">
                <Upload :size="28" aria-hidden="true" />
                <strong>{{ importSource ? importSource.name : '把政策文件拖到这里，或点击选择' }}</strong>
                <span class="policy-meta">支持 PDF、DOCX、TXT、Markdown、HTML，单个文件不超过 10 MB；文字 PDF 保留页码，扫描件走原 OCR 链路</span>
                <input type="file" class="policy-drop__input" aria-label="上传政策文件" accept=".txt,.md,.html,.htm,.docx,.pdf" @change="chooseFile" />
              </label>
              <label class="gov-label">官方来源网址（可选）<input v-model="importUrl" class="gov-input" aria-label="政策来源网址" type="url" placeholder="https://… 便于之后核对原文" /></label>
            </template>
            <label v-else class="gov-label">政策原文网址<input v-model="importUrl" class="gov-input" aria-label="政策原文网址" type="url" placeholder="https://www.gov.cn/…" /></label>
            <p class="policy-meta">补充信息（可选，留空则从原文识别）</p>
            <label class="gov-label">政策标题<input v-model="importTitle" class="gov-input" aria-label="导入政策标题" maxlength="300" /></label>
            <div class="policy-drawer__row">
              <label class="gov-label">文号<input v-model="importDocNumber" class="gov-input" aria-label="导入政策文号" maxlength="100" /></label>
              <label class="gov-label">发布机关<input v-model="importIssuer" class="gov-input" aria-label="导入政策发布机关" maxlength="200" /></label>
            </div>
            <p class="gov-banner gov-banner--warning">导入后状态为「待核实」。请对照官方原文完成人工核验，核验为现行后才能作为现行依据引用。</p>
          </div>
          <footer class="policy-drawer__foot">
            <button type="button" class="gov-btn" :disabled="writing" @click="closeImport">取消</button>
            <button type="submit" class="gov-btn gov-btn--primary" :disabled="writing || (importMode === 'file' ? !importSource : !importUrl.trim())">{{ writing ? '处理中…' : '导入（待核实）' }}</button>
          </footer>
        </form>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.policy-library { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--gov-bg); }
.policy-toolbar { flex: 0 0 auto; display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 12px 24px; background: var(--gov-surface); border-bottom: 1px solid var(--gov-border); }
.policy-toolbar__search { flex: 1 1 320px; display: flex; align-items: center; gap: 8px; height: 38px; padding: 0 12px; border: 1px solid var(--gov-border-strong); border-radius: var(--gov-r-md); background: var(--gov-surface); color: var(--gov-text-3); }
.policy-toolbar__search:focus-within { border-color: var(--gov-primary); }
.policy-toolbar__search input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; font: inherit; font-size: var(--gov-fs-body); color: var(--gov-text-1); }
.policy-toolbar__go { height: 38px; }
.policy-filters { display: flex; flex-wrap: wrap; gap: 8px; }
.policy-filter { display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 12px; border: 1px solid var(--gov-border); border-radius: 16px; background: var(--gov-surface); color: var(--gov-text-2); font: inherit; font-size: var(--gov-fs-sm); cursor: pointer; }
.policy-filter--on { background: var(--gov-primary); border-color: var(--gov-primary); color: #fff; }
.policy-toolbar__target { display: flex; align-items: center; gap: 8px; padding-left: 12px; border-left: 1px solid var(--gov-border); font-size: var(--gov-fs-sm); color: var(--gov-text-2); }
.policy-toolbar__target .gov-select { height: 38px; min-width: 220px; max-width: 320px; }
.policy-message { margin: 12px 24px 0; }
.policy-columns { flex: 1 1 auto; min-height: 0; display: grid; grid-template-columns: minmax(280px, 400px) minmax(0, 1fr); gap: 16px; padding: 16px 24px; }
.policy-pane { min-height: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--gov-surface); border: 1px solid var(--gov-border); border-radius: var(--gov-r-lg); }
.policy-pane__body { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
.policy-tabs { flex: 0 0 auto; display: flex; gap: 4px; padding: 0 12px; border-bottom: 1px solid var(--gov-border); }
.policy-tab { height: 44px; padding: 0 10px; border: 0; border-bottom: 2px solid transparent; background: none; font: inherit; font-size: var(--gov-fs-body); color: var(--gov-text-3); cursor: pointer; }
.policy-tab--on { border-bottom-color: var(--gov-primary); color: var(--gov-primary); font-weight: 700; }
.policy-list { display: flex; flex-direction: column; gap: 8px; padding: 12px; }
.policy-card { display: flex; flex-direction: column; gap: 6px; padding: 12px 14px; text-align: left; border: 1px solid var(--gov-border); border-radius: var(--gov-r-md); background: var(--gov-surface); color: inherit; font: inherit; overflow-wrap: anywhere; }
button.policy-card { cursor: pointer; }
.policy-card--on { border-color: var(--gov-primary); background: var(--gov-primary-50); box-shadow: inset 3px 0 0 var(--gov-primary); }
.policy-card__status { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0; }
.policy-hit-title { height: auto; padding: 0; text-align: left; font-weight: 600; white-space: normal; }
.policy-excerpt { margin: 0; font-size: var(--gov-fs-sm); line-height: 1.75; color: var(--gov-text-2); }
.policy-excerpt mark { background: #fde9b8; color: var(--gov-text-1); }
.policy-meta { margin: 0; font-size: var(--gov-fs-xs); color: var(--gov-text-3); }
.policy-more { align-self: center; margin-top: 4px; }
.policy-detail__header { flex: 0 0 auto; display: flex; flex-wrap: wrap; align-items: flex-start; gap: 16px; padding: 16px 20px; border-bottom: 1px solid var(--gov-border); }
.policy-detail__heading { flex: 1 1 260px; min-width: 0; display: flex; flex-direction: column; gap: 6px; overflow-wrap: anywhere; }
.policy-detail__heading h2 { margin: 0; font-size: 17px; line-height: 1.5; }
.policy-source-button { height: 38px; text-decoration: none; font-weight: 600; }
.policy-detail__note { flex: 0 0 auto; margin: 0; border-radius: 0; }
.policy-detail__body { padding: 0 20px; }
.policy-clause { display: flex; align-items: flex-start; gap: 16px; padding: 14px 0; border-bottom: 1px solid var(--gov-border); }
.policy-clause:last-child { border-bottom: 0; }
.policy-clause__text { flex: 1 1 auto; min-width: 0; }
.policy-text { margin: 4px 0 0; white-space: pre-wrap; line-height: 1.85; overflow-wrap: anywhere; }
.policy-verify { flex: 0 0 auto; display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 12px 20px; background: var(--gov-surface-2); border-top: 1px solid var(--gov-border); }
.policy-seg { display: inline-flex; border: 1px solid var(--gov-border-strong); border-radius: var(--gov-r-md); overflow: hidden; }
.policy-seg label { display: flex; align-items: center; gap: 6px; height: 32px; padding: 0 12px; font-size: var(--gov-fs-sm); color: var(--gov-text-2); border-right: 1px solid var(--gov-border-strong); cursor: pointer; }
.policy-seg label:last-child { border-right: 0; }
.policy-seg--on { background: var(--gov-primary-50); color: var(--gov-primary) !important; font-weight: 600; }
.policy-verify__note { flex: 1 1 160px; width: auto; min-width: 0; }
.policy-placeholder { align-items: center; justify-content: center; }
.policy-empty { flex: 1 1 auto; min-height: 0; overflow-y: auto; margin: 16px 24px; display: flex; align-items: center; justify-content: center; background: var(--gov-surface); border: 1px solid var(--gov-border); border-radius: var(--gov-r-lg); }
.policy-empty__inner { width: min(560px, 100%); padding: 32px 16px; display: flex; flex-direction: column; align-items: center; gap: 16px; text-align: center; }
.policy-empty__inner h2 { margin: 0; font-size: 20px; }
.policy-empty__inner p { margin: 0; line-height: 1.7; color: var(--gov-text-2); }
.policy-empty__icon { width: 64px; height: 64px; border-radius: 16px; background: var(--gov-primary-50); color: var(--gov-primary); display: flex; align-items: center; justify-content: center; }
.policy-empty__actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 12px; }
.policy-empty__actions .gov-btn { height: 42px; padding: 0 20px; }
.policy-steps { width: 100%; margin: 0; padding: 16px 20px 16px 40px; display: flex; flex-direction: column; gap: 12px; text-align: left; border: 1px solid var(--gov-border); border-radius: var(--gov-r-lg); background: var(--gov-surface-2); }
.policy-steps strong { display: block; font-size: var(--gov-fs-body); }
.policy-steps span { font-size: var(--gov-fs-sm); line-height: 1.6; color: var(--gov-text-3); }
.policy-drawer-mask { position: fixed; inset: 0; z-index: 40; background: rgba(16, 36, 63, 0.38); display: flex; justify-content: flex-end; }
.policy-drawer { width: min(520px, 100%); height: 100%; display: flex; flex-direction: column; background: var(--gov-surface); box-shadow: var(--gov-sh-3); }
.policy-drawer__head { flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; height: 60px; padding: 0 16px 0 24px; border-bottom: 1px solid var(--gov-border); }
.policy-drawer__head h2 { margin: 0; font-size: 17px; }
.policy-import { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.policy-drawer__body { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; }
.policy-drawer__body .gov-banner { margin: 0; line-height: 1.7; }
.policy-drawer__row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.policy-mode { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid var(--gov-border-strong); border-radius: var(--gov-r-md); overflow: hidden; }
.policy-mode button { height: 38px; border: 0; background: var(--gov-surface); color: var(--gov-text-2); font: inherit; font-size: var(--gov-fs-body); cursor: pointer; }
.policy-mode button + button { border-left: 1px solid var(--gov-border-strong); }
.policy-mode .policy-mode--on { background: var(--gov-primary-50); color: var(--gov-primary); font-weight: 700; }
.policy-drop { position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 180px; padding: 16px; border: 2px dashed var(--gov-border-strong); border-radius: var(--gov-r-lg); background: var(--gov-surface-2); color: var(--gov-primary); text-align: center; cursor: pointer; overflow-wrap: anywhere; }
.policy-drop:focus-within { border-color: var(--gov-primary); }
.policy-drop strong { color: var(--gov-text-1); }
.policy-drop__input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.policy-drawer__foot { flex: 0 0 auto; display: flex; justify-content: flex-end; gap: 12px; padding: 12px 24px; border-top: 1px solid var(--gov-border); background: var(--gov-surface-2); }
.policy-library--embedded .policy-toolbar { padding: 12px 20px; }
.policy-library--embedded .policy-columns { padding: 12px 20px; }
@media (max-width: 900px) {
  .policy-columns { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(200px, 40%) minmax(0, 1fr); }
  .policy-toolbar__target { padding-left: 0; border-left: 0; }
}
</style>
