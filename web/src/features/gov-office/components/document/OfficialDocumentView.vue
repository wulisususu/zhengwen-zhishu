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

const letterhead = computed(() => previewLetterhead(props.doc.docType));

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

    <h2 class="gov-doc__title">{{ doc.title }}</h2>

    <template v-for="block in doc.blocks" :key="block.id">
      <div v-if="block.kind === 'signature'" :class="blockClass(block)" :data-anchor="block.id">
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
  </div>
</template>

<style scoped>
.gov-doc { display: flex; flex-direction: column; }
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
