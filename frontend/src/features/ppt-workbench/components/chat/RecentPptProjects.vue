<script setup lang="ts">
import { onMounted, ref } from "vue";
import { loadRecentProjectSummaries, type RecentProjectSummary } from "../../persistence/projectSessionStorage";
import { useRoute, useRouter } from "vue-router";

type BackendProject = { project_id?: unknown; title?: unknown; updated_at?: unknown; editor_supported?: unknown };

const props = defineProps<{ currentProjectId?: string }>();
const router = useRouter();
const route = useRoute();
const projects = ref<RecentProjectSummary[]>(loadRecentProjectSummaries());

function normalizeProject(value: BackendProject): RecentProjectSummary | null {
  if (typeof value.project_id !== "string" || !value.project_id) return null;
  return {
    projectId: value.project_id,
    title: typeof value.title === "string" && value.title ? value.title : "未命名 PPT",
    updatedAt: typeof value.updated_at === "string" ? value.updated_at : new Date(0).toISOString(),
    editorSupported: value.editor_supported === true,
  } as RecentProjectSummary & { editorSupported: boolean };
}

onMounted(async () => {
  try {
    const response = await fetch("/api/v1/ppt-master/projects/recent");
    const payload = await response.json();
    if (!response.ok || !Array.isArray(payload?.data)) return;
    const records = payload.data as BackendProject[];
    projects.value = records.map(normalizeProject).filter((item): item is RecentProjectSummary => item !== null);
  } catch {
    // LocalStorage is a display cache for offline/error fallback only.
  }
});
</script>

<template>
  <section data-recent-projects class="w-full" aria-labelledby="recent-ppt-title">
    <div class="mb-2 px-3">
      <h2 id="recent-ppt-title" class="text-xs font-semibold text-slate-500">最近 PPT 会话</h2>
    </div>
    <div v-if="projects.length" class="space-y-1">
      <button
        v-for="item in projects"
        :key="item.projectId"
        type="button"
        :class="['block w-full rounded-[12px] border px-3 py-2.5 text-left transition-all', (props.currentProjectId || String(route.params.projectId ?? '')) === item.projectId ? 'border-[rgba(94,106,210,0.10)] bg-[#F4F6FF] font-semibold text-[#344054] shadow-[0_1px_2px_rgba(16,24,40,0.04)]' : 'border-transparent bg-transparent text-[#475467] hover:border-[#E6EAF2] hover:bg-[#F8FAFC]']"
        :disabled="(item as any).editorSupported === false"
        @click="(item as any).editorSupported !== false && router.push(`/ppt/${encodeURIComponent(item.projectId)}`)"
      >
        <strong class="block truncate text-[13px]">{{ item.title }}</strong>
        <span class="mt-1 block truncate text-[11px] text-slate-400">{{ (item as any).editorSupported === false ? '不支持在线编辑' : new Date(item.updatedAt).toLocaleString() }}</span>
      </button>
    </div>
    <div v-else class="px-3 py-2 text-xs text-slate-400">
      暂无最近 PPT 会话
    </div>
  </section>
</template>
