<script setup lang="ts">
import { nextTick } from "vue";
import { FIELD_LABELS } from "../../domain/docTypes";
import type { FieldKey, OfficialDocument } from "../../types";

const props = defineProps<{ doc: OfficialDocument; editable: boolean }>();
const emit = defineEmits<{ (e: "update", field: FieldKey, value: string): void }>();

const FIELDS: { key: FieldKey; required: boolean; placeholder: string }[] = [
  { key: "recipient", required: true, placeholder: "例如：各区政务服务管理部门" },
  { key: "issuer", required: true, placeholder: "例如：示例单位数据管理办公室" },
  { key: "undertaker", required: false, placeholder: "例如：数据安全处" },
];

async function focusField(field: FieldKey) {
  await nextTick();
  document.getElementById(`gov-field-${field}`)?.focus();
}
defineExpose({ focusField });

function isEmpty(field: FieldKey) {
  return !props.doc.fields[field].trim();
}
</script>

<template>
  <section class="gov-fields" aria-label="起草要素">
    <h2 class="gov-subtitle">起草要素</h2>
    <label v-for="f in FIELDS" :key="f.key" class="gov-label" :for="`gov-field-${f.key}`">
      <span>{{ FIELD_LABELS[f.key] }}<span v-if="f.required" class="gov-fields__req" aria-hidden="true"> *</span></span>
      <input
        :id="`gov-field-${f.key}`"
        class="gov-input"
        :class="{ 'gov-input--required-empty': f.required && isEmpty(f.key) }"
        type="text"
        :value="doc.fields[f.key]"
        :placeholder="f.placeholder"
        :disabled="!editable"
        :aria-required="f.required"
        @input="emit('update', f.key, ($event.target as HTMLInputElement).value)"
      />
    </label>
    <dl class="gov-fields__meta">
      <dt>发文字号</dt><dd>{{ doc.docNumber.text || "—" }}</dd>
      <dt>成文日期</dt><dd>{{ doc.signDate || "—" }}</dd>
    </dl>
    <p class="gov-muted" style="margin: 0; line-height: 18px">必填要素为空时，正文以【待补充】标记显示，不由模型编造。</p>
  </section>
</template>

<style scoped>
.gov-fields { display: flex; flex-direction: column; gap: 10px; }
.gov-fields__req { color: var(--gov-red); }
.gov-fields__meta { margin: 0; display: grid; grid-template-columns: 72px minmax(0, 1fr); row-gap: 6px; font-size: 13px; }
.gov-fields__meta dt { color: var(--gov-text-3); }
.gov-fields__meta dd { margin: 0; }
</style>
