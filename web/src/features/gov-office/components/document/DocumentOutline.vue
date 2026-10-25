<script setup lang="ts">
import { computed } from "vue";
import type { IssueEvaluation } from "../../domain/issueRules";
import type { OfficialDocument } from "../../types";

const props = defineProps<{ doc: OfficialDocument; unresolved: IssueEvaluation[]; template: string }>();
const emit = defineEmits<{ (e: "locate", anchor: string): void }>();

const SECTION_TITLES: Record<string, { title: string; summary: string }> = {
  head: { title: "版头与主送", summary: "发文字号、标题、主送机关" },
  intro: { title: "开头段", summary: "说明发文依据与目的" },
  attach: { title: "附件", summary: "附件说明" },
  sign: { title: "落款", summary: "发文机关署名、成文日期" },
};

const sections = computed(() => {
  const seen: { key: string; anchor: string; title: string; summary: string }[] = [];
  for (const block of props.doc.blocks) {
    if (seen.some((s) => s.key === block.section)) continue;
    const fixed = SECTION_TITLES[block.section];
    const heading = props.doc.blocks.find((b) => b.section === block.section && b.kind === "heading1");
    const headingText = heading?.segments.map((s) => (s.kind === "text" ? s.text : "")).join("") ?? "";
    const firstText = block.segments.map((s) => (s.kind === "text" ? s.text : "")).join("");
    seen.push({
      key: block.section,
      anchor: heading?.id ?? block.id,
      title: fixed?.title ?? (headingText || firstText.slice(0, 14)),
      summary: fixed?.summary ?? firstText.slice(0, 40),
    });
  }
  return seen.map((s, index) => {
    const count = props.unresolved.filter((e) => e.issue.section === s.key).length;
    return { ...s, no: String(index + 1).padStart(2, "0"), count };
  });
});
</script>

<template>
  <div class="gov-outline gov-card">
    <div class="gov-outline__head">
      <h2 class="gov-section-title">文稿提纲</h2>
      <span class="gov-muted">提纲来源：{{ template }}</span>
    </div>
    <ol class="gov-outline__list">
      <li v-for="s in sections" :key="s.key" class="gov-outline__item">
        <span class="gov-outline__no">{{ s.no }}</span>
        <div class="gov-outline__body">
          <span class="gov-outline__title">{{ s.title }}</span>
          <span class="gov-outline__summary">{{ s.summary }}</span>
        </div>
        <span class="gov-tag" :class="s.count ? 'gov-tag--warning' : 'gov-tag--success'">{{ s.count ? `${s.count} 项问题` : "无问题" }}</span>
        <button type="button" class="gov-btn gov-btn--sm" @click="emit('locate', s.anchor)">定位正文</button>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.gov-outline { max-width: 720px; margin: 24px auto; padding: 20px 24px; }
.gov-outline__head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding-bottom: 12px; border-bottom: 1px solid var(--gov-border); }
.gov-outline__list { list-style: none; margin: 0; padding: 0; }
.gov-outline__item { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--gov-border); }
.gov-outline__no { flex: 0 0 28px; font-size: 13px; color: var(--gov-text-3); }
.gov-outline__body { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.gov-outline__title { font-size: 14px; font-weight: 500; }
.gov-outline__summary { font-size: 13px; color: var(--gov-text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
