<script setup lang="ts">
import BaseDialog from "../common/BaseDialog.vue";
import type { IssueEvaluation } from "../../domain/issueRules";

defineProps<{ blockers: IssueEvaluation[]; checkStatus?: string }>();
const emit = defineEmits<{ (e: "close"): void; (e: "confirm"): void }>();
</script>

<template>
  <BaseDialog title="提交审核" @close="emit('close')">
    <p style="margin: 0">提交后文稿进入「待审核」，编辑将锁定，直到审核人退回修改。</p>
    <template v-if="blockers.length">
      <div class="gov-banner gov-banner--warning">
        仍有 {{ blockers.length }} 项严重问题未处理。可以提交给审核人查看，但处理完毕前审核人不能审核通过，也不能正式导出。
      </div>
      <ul style="margin: 0; padding-left: 18px">
        <li v-for="b in blockers" :key="b.issue.id">{{ b.issue.title }}（{{ b.issue.locationLabel }}）</li>
      </ul>
    </template>
    <div v-else-if="checkStatus === 'not_run'" class="gov-banner gov-banner--warning">自动审校未接入，本次提交为人工审核，不能据此认定文稿无错误。</div>
    <div v-else class="gov-banner gov-banner--success">没有未处理的严重问题。</div>
    <template #footer>
      <button type="button" class="gov-btn" data-dialog-close @click="emit('close')">取消</button>
      <button type="button" class="gov-btn gov-btn--primary" @click="emit('confirm')">确认提交</button>
    </template>
  </BaseDialog>
</template>
