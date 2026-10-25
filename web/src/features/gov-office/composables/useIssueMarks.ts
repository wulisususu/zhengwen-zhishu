import { computed, type Ref } from "vue";
import { summarizeIssues } from "../domain/issueRules";
import type { IssueSeverity, OfficialDocument } from "../types";

const SEVERITY_RANK: Record<IssueSeverity, number> = { critical: 3, warning: 2, hint: 1 };

/** anchor id -> most serious unresolved severity, for marking the preview. */
export function useIssueMarks(doc: Ref<OfficialDocument | undefined>) {
  const summary = computed(() => (doc.value ? summarizeIssues(doc.value) : null));
  const marks = computed(() => {
    const result: Record<string, IssueSeverity> = {};
    for (const e of summary.value?.unresolved ?? []) {
      const current = result[e.issue.anchor];
      if (!current || SEVERITY_RANK[e.issue.severity] > SEVERITY_RANK[current]) result[e.issue.anchor] = e.issue.severity;
    }
    return result;
  });
  return { summary, marks };
}
