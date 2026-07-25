import type { PptWorkflowEvent } from "./events";

export interface EventReducerResult {
  accepted: boolean;
  reason?: "duplicate" | "stale-sequence";
}

/**
 * Applies only transport reliability rules. Business state belongs to the
 * dedicated Pinia stores, which keeps raw transport details out of components.
 */
export function shouldApplyWorkflowEvent(
  event: PptWorkflowEvent,
  lastSequence: number,
  seenEventIds: ReadonlySet<string>,
): EventReducerResult {
  if (seenEventIds.has(event.eventId)) {
    return { accepted: false, reason: "duplicate" };
  }

  if (event.sequence <= lastSequence) {
    return { accepted: false, reason: "stale-sequence" };
  }

  return { accepted: true };
}
