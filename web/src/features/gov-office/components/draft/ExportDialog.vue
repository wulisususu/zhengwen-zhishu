<script setup lang="ts">
import { computed, ref } from "vue";
import BaseDialog from "../common/BaseDialog.vue";
import { documentGates } from "../../domain/issueRules";
import { useGovDocumentsStore } from "../../stores/govDocuments";
import type { Actor, ExportResult, OfficialDocument } from "../../types";

const props = defineProps<{ doc: OfficialDocument; actor: Actor }>();
const emit = defineEmits<{ (e: "close"): void; (e: "locate", anchor: string): void }>();

const store = useGovDocumentsStore();
const gates = computed(() => documentGates(props.doc, props.actor));
const result = ref<ExportResult | null>(null);
const busy = ref(false);

async function exportInternal() {
  busy.value = true;
  result.value = (await store.exportDocument(props.doc.id, "internal_draft")) ?? null;
  busy.value = false;
}
</script>

<template>
  <BaseDialog title="导出" :width="560" @close="emit('close')">
    <section class="gov-export__option">
      <div class="gov-export__head">
        <h3 class="gov-subtitle">内部草稿</h3>
        <span class="gov-tag gov-tag--warning">带「未审核 · 内部草稿」标识</span>
      </div>
      <p style="margin: 0">任何状态都可以导出，供内部传阅修改，不能作为正式文件使用。</p>
      <button type="button" class="gov-btn gov-btn--outline" style="align-self: flex-start" :disabled="busy" @click="exportInternal">导出内部草稿</button>
      <div v-if="result" class="gov-banner gov-banner--info" role="status">{{ result.message }}</div>
    </section>

    <section class="gov-export__option">
      <div class="gov-export__head">
        <h3 class="gov-subtitle">正式导出</h3>
        <span class="gov-tag" :class="gates.canFormalExport ? 'gov-tag--success' : 'gov-tag--neutral'">{{ gates.canFormalExport ? "可导出" : "不可导出" }}</span>
      </div>
      <p style="margin: 0">须审核通过、无未处理的严重问题，并由具有正式发文权限的人员操作。</p>
      <div v-if="!gates.canFormalExport" class="gov-banner gov-banner--danger">{{ gates.formalExportBlockedReason }}</div>
      <div v-for="b in gates.blockers" :key="b.issue.id" class="gov-export__blocker">
        <span>{{ b.issue.title }}<span class="gov-muted"> · {{ b.issue.locationLabel }}</span></span>
        <button type="button" class="gov-btn gov-btn--sm" @click="emit('locate', b.issue.anchor)">定位</button>
      </div>
      <button type="button" class="gov-btn gov-btn--primary" style="align-self: flex-start" :disabled="!gates.canFormalExport">正式导出 DOCX</button>
    </section>

    <span class="gov-muted">导出文件由后端模板生成；演示环境不会生成或下载任何文件。</span>
  </BaseDialog>
</template>

<style scoped>
.gov-export__option { display: flex; flex-direction: column; gap: 8px; padding: 12px 14px; border: 1px solid var(--gov-border); border-radius: var(--gov-r-md); }
.gov-export__head { display: flex; align-items: center; gap: 8px; }
.gov-export__blocker { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 10px; border: 1px solid var(--gov-border); border-radius: var(--gov-r-md); font-size: 13px; color: var(--gov-text-1); }
</style>
