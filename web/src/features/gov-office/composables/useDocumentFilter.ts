import { computed, ref, type Ref } from "vue";
import { summarizeIssues } from "../domain/issueRules";
import type { DocStatus, DocumentFilter, OfficialDocument } from "../types";

export function useDocumentFilter(docs: Ref<OfficialDocument[]>, initial: Partial<DocumentFilter> = {}) {
  const defaults: DocumentFilter = { keyword: "", docType: "all", status: "all", criticalOnly: false, ...initial };
  const filter = ref<DocumentFilter>({ ...defaults });

  const filtered = computed(() => {
    const keyword = filter.value.keyword.trim();
    return docs.value.filter((d) => {
      if (keyword && !d.title.includes(keyword) && !d.author.includes(keyword)) return false;
      if (filter.value.docType !== "all" && d.docType !== filter.value.docType) return false;
      if (filter.value.status !== "all" && d.status !== filter.value.status) return false;
      if (filter.value.criticalOnly && summarizeIssues(d).open.critical === 0) return false;
      return true;
    });
  });

  const counts = computed(() => {
    const result: Record<DocStatus | "all", number> = { all: docs.value.length, draft: 0, pending: 0, returned: 0, approved: 0 };
    docs.value.forEach((d) => (result[d.status] += 1));
    return result;
  });

  function reset() {
    filter.value = { ...defaults };
  }

  return { filter, filtered, counts, reset };
}
