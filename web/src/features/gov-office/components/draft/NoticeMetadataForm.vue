<script setup lang="ts">
import { computed } from "vue";
import type { NoticeMetadata } from "../../types";
const props = defineProps<{ modelValue: NoticeMetadata }>();
const emit = defineEmits<{ (e: "update:modelValue", value: NoticeMetadata): void }>();
function patch(value: Partial<NoticeMetadata>) { emit("update:modelValue", { ...props.modelValue, ...value }); }
function value(event: Event) { return (event.target as HTMLInputElement).value; }
function editTable(index: number, row: number, col: number, text: string) {
  const tables = props.modelValue.tables.map(t => ({ ...t, head: [...t.head], rows: t.rows.map(r => [...r]) }));
  if (row === -1) tables[index].head[col] = text;
  else tables[index].rows[row][col] = text;
  patch({ tables });
}
function addRow(index: number) { patch({ tables: props.modelValue.tables.map((t, i) => i === index ? { ...t, rows: [...t.rows, t.head.map(() => "")] } : t) }); }
function addColumn(index: number) { patch({ tables: props.modelValue.tables.map((t, i) => i === index ? { ...t, head: [...t.head, ""], rows: t.rows.map(r => [...r, ""]) } : t) }); }
/** Folded items that already have content, so a collapsed section never hides filled-in data silently. */
const filled = computed(() => {
  const m = props.modelValue;
  return [m.copyTo, m.note, m.titleLines].filter(text => text.trim()).length + m.tables.length;
});
</script>

<template>
  <div class="gov-notice-meta">
    <label class="gov-label">发文字号<input class="gov-input" aria-label="发文字号" maxlength="60" :value="modelValue.docNumber" placeholder="例如：办发〔2026〕8号" @input="patch({ docNumber: value($event) })" /></label>
    <label class="gov-label">印发机关<input class="gov-input" aria-label="印发机关" maxlength="60" :value="modelValue.printer" @input="patch({ printer: value($event) })" /></label>
    <label class="gov-label">印发日期<input class="gov-input" aria-label="印发日期" maxlength="30" :value="modelValue.printDate" placeholder="2026年10月26日" @input="patch({ printDate: value($event) })" /></label>
    <details class="gov-notice-meta__more">
      <summary>抄送、附注与表格<span v-if="filled" class="gov-muted">（已填 {{ filled }} 项）</span></summary>
      <div class="gov-notice-meta__fields">
        <label class="gov-label">抄送机关（每行一个）<textarea class="gov-textarea" aria-label="抄送机关" :value="modelValue.copyTo" rows="2" @input="patch({ copyTo: value($event) })" /></label>
        <label class="gov-label">附注<input class="gov-input" aria-label="附注" maxlength="200" :value="modelValue.note" @input="patch({ note: value($event) })" /></label>
        <label class="gov-label">标题分行（可选，保持标题原文）<textarea class="gov-textarea" aria-label="标题分行" :value="modelValue.titleLines" rows="2" @input="patch({ titleLines: value($event) })" /></label>
      </div>
      <div v-for="(table, index) in modelValue.tables" :key="index" class="gov-notice-meta__table">
        <label class="gov-label">表格标题<input class="gov-input" :aria-label="`表格${index + 1}标题`" maxlength="60" :value="table.caption" @input="patch({ tables: modelValue.tables.map((t, i) => i === index ? { ...t, caption: value($event) } : t) })" /></label>
        <table><thead><tr><th v-for="(cell, col) in table.head" :key="col"><input class="gov-input" :aria-label="`表格${index + 1}表头第${col + 1}列`" :value="cell" maxlength="40" @input="editTable(index, -1, col, value($event))" /></th></tr></thead>
          <tbody><tr v-for="(row, r) in table.rows" :key="r"><td v-for="(cell, c) in row" :key="c"><input class="gov-input" :aria-label="`表格${index + 1}第${r + 1}行第${c + 1}列`" maxlength="200" :value="cell" @input="editTable(index, r, c, value($event))" /></td></tr></tbody></table>
        <div class="gov-notice-meta__actions">
          <button type="button" class="gov-btn gov-btn--sm" :disabled="table.rows.length >= 200" @click="addRow(index)">增加行</button>
          <button type="button" class="gov-btn gov-btn--sm" :disabled="table.head.length >= 8" @click="addColumn(index)">增加列</button>
          <button type="button" class="gov-btn gov-btn--sm" @click="patch({ tables: modelValue.tables.filter((_, i) => i !== index) })">移除此表格</button>
        </div>
      </div>
      <button type="button" class="gov-btn gov-btn--sm" :disabled="modelValue.tables.length >= 20" @click="patch({ tables: [...modelValue.tables, { caption: '', head: ['事项', '数量'], rows: [['', '']] }] })">添加表格</button>
      <p class="gov-muted">表格将排在正文之后；有修改时请保存并重新审校。</p>
    </details>
  </div>
</template>

<style scoped>
.gov-notice-meta { display: flex; flex-direction: column; gap: 10px; }
.gov-notice-meta__more summary { cursor: pointer; font-size: var(--gov-fs-sm); color: var(--gov-text-2); }
.gov-notice-meta__fields { display: flex; flex-direction: column; gap: 10px; margin: 10px 0; }
.gov-notice-meta__table { overflow-x: auto; margin: 12px 0; }
.gov-notice-meta__table table { width: 100%; border-collapse: collapse; margin: 8px 0; }
.gov-notice-meta__table td, .gov-notice-meta__table th { padding: 3px; min-width: 100px; }
.gov-notice-meta__actions { display: flex; flex-wrap: wrap; gap: 6px; }
</style>
