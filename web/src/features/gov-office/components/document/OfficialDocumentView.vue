<script setup lang="ts">
import { computed } from "vue";
import { FIELD_LABELS, previewLetterhead } from "../../domain/docTypes";
import type { DocBlock, DocSegment, IssueSeverity, OfficialDocument } from "../../types";

const props = defineProps<{
  doc: OfficialDocument;
  /** anchor id -> severity of the most serious unresolved issue there */
  marks: Record<string, IssueSeverity>;
  focusAnchor: string;
}>();

const letterhead = computed(() => {
  const layout = previewLetterhead(props.doc.docType);
  return props.doc.origin === "backend" ? { ...layout, orgText: props.doc.fields.issuer || "【待补充：发文机关】" } : layout;
});

function anchorClass(anchor: string | undefined) {
  if (!anchor) return {};
  return {
    [`is-mark-${props.marks[anchor]}`]: !!props.marks[anchor],
    "is-focus": props.focusAnchor === anchor,
  };
}

function fieldValue(seg: DocSegment): string {
  return seg.kind === "field" ? props.doc.fields[seg.field].trim() : "";
}

function blockClass(block: DocBlock) {
  return [`gov-doc__${block.kind}`, anchorClass(block.id)];
}
</script>

<template>
  <div class="gov-doc">
    <template v-if="letterhead.kind === 'file_red' || letterhead.kind === 'minutes'">
      <div class="gov-doc__org">{{ letterhead.orgText }}</div>
      <p v-if="letterhead.showDocNumber" class="gov-doc__docno">
        <span :data-anchor="doc.docNumber.id" :class="anchorClass(doc.docNumber.id)">{{ doc.docNumber.text }}</span>
      </p>
      <div class="gov-doc__rule" />
    </template>
    <template v-else-if="letterhead.kind === 'letter'">
      <div class="gov-doc__org gov-doc__org--letter">{{ letterhead.orgText }}</div>
      <div class="gov-doc__rule gov-doc__rule--double" />
    </template>

    <h2 class="gov-doc__title" :data-anchor="doc.id + '-title'" :class="anchorClass(doc.id + '-title')">{{ doc.title }}</h2>

    <template v-for="block in doc.blocks" :key="block.id">
      <table v-if="block.kind === 'table' && block.table" class="gov-doc__table" :class="anchorClass(block.id)" :data-anchor="block.id">
        <caption>{{ block.table.caption }}</caption>
        <thead><tr><th v-for="(cell, c) in block.table.head" :key="c">{{ cell }}</th></tr></thead>
        <tbody><tr v-for="(row, r) in block.table.rows" :key="r"><td v-for="(cell, c) in row" :key="c">{{ cell }}</td></tr></tbody>
      </table>
      <div v-else-if="block.kind === 'signature'" :class="blockClass(block)" :data-anchor="block.id">
        <span v-for="(seg, i) in block.segments" :key="i" class="gov-doc__sign-line">
          <span v-if="seg.kind === 'field'" :data-anchor="seg.id" :class="anchorClass(seg.id)">
            <template v-if="fieldValue(seg)">{{ fieldValue(seg) }}</template>
            <span v-else class="gov-doc__placeholder">【待补充：{{ FIELD_LABELS[seg.field] }}】</span>
          </span>
          <span v-else>{{ seg.text }}</span>
        </span>
        <span class="gov-doc__sign-line">{{ doc.signDate }}</span>
      </div>
      <component
        :is="block.kind === 'heading1' || block.kind === 'heading2' ? 'h3' : 'p'"
        v-else
        :class="blockClass(block)"
        :data-anchor="block.id"
      >
        <template v-if="block.kind === 'attachment'">附件：</template>
        <template v-for="(seg, i) in block.segments" :key="i">
          <span v-if="seg.kind === 'field'" :data-anchor="seg.id" :class="anchorClass(seg.id)">
            <template v-if="fieldValue(seg)">{{ fieldValue(seg) }}</template>
            <span v-else class="gov-doc__placeholder">【待补充：{{ FIELD_LABELS[seg.field] }}】</span>
          </span>
          <span v-else-if="seg.id" :data-anchor="seg.id" :class="anchorClass(seg.id)">{{ seg.text }}</span>
          <template v-else>{{ seg.text }}</template>
        </template>
        <template v-if="block.kind === 'recipient'">：</template>
      </component>
    </template>
    <p v-if="doc.note">{{ doc.note }}</p>
    <div v-if="doc.origin === 'backend'" class="gov-doc__banji" :data-anchor="doc.id + '-banji'" :class="anchorClass(doc.id + '-banji')">
      <p v-if="doc.banji?.copyTo?.length">抄送：{{ doc.banji.copyTo.join('、') }}</p>
      <p>{{ doc.banji?.printer || '【待补充：印发机关】' }}　{{ doc.banji?.printDate || '【待补充：印发日期】' }}印发</p>
    </div>
    <div v-if="doc.origin === 'backend' && doc.policyRefs.length" :data-anchor="doc.id + '-policies'" :class="anchorClass(doc.id + '-policies')">
      <p>政策依据（来源及有效性须人工核验）</p>
      <p v-for="ref in doc.policyRefs" :key="ref.id">《{{ ref.title }}》{{ ref.clause }} · {{ ref.status === 'current' ? '现行' : ref.status === 'abolished' ? '已废止' : '未核验' }} {{ ref.statusNote }}</p>
    </div>
  </div>
</template>

<style scoped>
.gov-doc { display: flex; flex-direction: column; }
.gov-doc__table { width: 100%; border-collapse: collapse; margin: 1em 0; }
.gov-doc__table td, .gov-doc__table th { border: 1px solid #333; padding: 4px 8px; }
.gov-doc__banji { border-top: 1px solid #333; border-bottom: 1px solid #333; margin-top: 2em; }
.gov-doc__heading3, .gov-doc__heading4 { margin: 0; text-indent: 2em; }
.gov-doc__org {
  text-align: center; color: #b42318; font-family: var(--gov-font-doc-title); font-weight: 700;
  font-size: 56px; letter-spacing: 6px; line-height: 1.3;
}
.gov-doc__org--letter { font-size: 44px; }
.gov-doc__docno { margin: 28px 0 0; text-align: center; }
.gov-doc__rule { height: 2px; background: #b42318; margin: 12px 0 44px; }
.gov-doc__rule--double { height: 6px; background: transparent; border-top: 2px solid #b42318; border-bottom: 1px solid #b42318; }
.gov-doc__title {
  margin: 0 0 30px; text-align: center; font-family: var(--gov-font-doc-title); font-weight: 700;
  font-size: 29.33px; line-height: 1.5;
}
.gov-doc__recipient { margin: 0; }
.gov-doc__paragraph { margin: 0; text-indent: 2em; }
.gov-doc__heading1 { margin: 0; text-indent: 2em; font-family: var(--gov-font-doc-h1); font-size: 1em; font-weight: 400; }
.gov-doc__heading2 { margin: 0; text-indent: 2em; font-family: var(--gov-font-doc-h2); font-size: 1em; font-weight: 400; }
.gov-doc__attachment { margin: 1.8em 0 0; text-indent: 2em; }
.gov-doc__signature { margin: 3em 0 0; display: flex; flex-direction: column; align-items: flex-end; padding-right: 2em; }
.gov-doc__sign-line { display: block; }
.gov-doc__placeholder { color: #b42318; background: #fdf1f0; font-weight: 700; padding: 0 2px; }

.is-mark-critical { text-decoration: underline wavy #b42318; text-decoration-thickness: 1px; text-underline-offset: 0.25em; }
.is-mark-warning { text-decoration: underline wavy #93470a; text-decoration-thickness: 1px; text-underline-offset: 0.25em; }
.is-mark-hint { text-decoration: underline dotted #1f4e8c; text-decoration-thickness: 2px; text-underline-offset: 0.25em; }
.is-focus { background: rgba(31, 78, 140, 0.12); box-shadow: 0 0 0 3px rgba(31, 78, 140, 0.45); border-radius: 2px; }
</style>
