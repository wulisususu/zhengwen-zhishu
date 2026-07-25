import { defineStore } from "pinia";
import type { GenerationStatus, PptGenerationTask, WorkflowError, WorkflowStage } from "../types/task";
import type { PersistedProjectSession } from "../persistence/projectSessionStorage";

export const usePptGenerationStore = defineStore("pptGeneration", {
  state: () => ({
    task: null as PptGenerationTask | null,
    workflowStage: "idle" as WorkflowStage,
    status: "idle" as GenerationStatus,
    progress: 0,
    actualProgress: 0,
    displayProgress: 0,
    progressTimer: null as ReturnType<typeof setInterval> | null,
    lastAppliedSequence: 0,
    error: null as WorkflowError | null,
    seenEventIds: new Set<string>(),
  }),
  actions: {
    restoreStableSnapshot(snapshot: PersistedProjectSession["generation"]) {
      this.task = snapshot.task;
      this.workflowStage = snapshot.workflowStage;
      this.status = snapshot.status;
      this.stopProgressAnimation();
      this.actualProgress = Math.max(0, Math.min(99, snapshot.actualProgress ?? snapshot.progress));
      this.displayProgress = Math.max(0, Math.min(snapshot.displayProgress ?? snapshot.progress, this.actualProgress));
      this.progress = this.displayProgress;
      this.error = snapshot.error;
      this.lastAppliedSequence = 0;
      this.seenEventIds = new Set();
    },
    start(task: PptGenerationTask) {
      this.task = task; this.workflowStage = "understanding"; this.status = "running";
      this.stopProgressAnimation();
      this.progress = 0; this.actualProgress = 1; this.displayProgress = 1;
      this.lastAppliedSequence = 0; this.error = null; this.seenEventIds = new Set();
      this.startProgressAnimation();
    },
    acceptEvent(eventId: string, sequence: number) { this.seenEventIds.add(eventId); this.lastAppliedSequence = sequence; },
    complete() {
      this.stopProgressAnimation();
      this.actualProgress = 100; this.displayProgress = 100; this.progress = 100;
      this.workflowStage = "completed"; this.status = "completed";
      if (this.task) { this.task.stage = "completed"; this.task.status = "completed"; this.task.progress = 100; this.task.completedAt = new Date().toISOString(); }
    },
    fail(error: WorkflowError) {
      this.stopProgressAnimation();
      this.workflowStage = "failed"; this.status = "failed"; this.error = error;
      if (this.task) { this.task.stage = "failed"; this.task.status = "failed"; }
    },
    interrupt(error: WorkflowError) {
      this.stopProgressAnimation();
      this.status = "interrupted"; this.error = error;
      if (this.task) this.task.status = "interrupted";
    },
    cancel() {
      this.stopProgressAnimation();
      this.workflowStage = "cancelled"; this.status = "cancelled";
      if (this.task) { this.task.stage = "cancelled"; this.task.status = "cancelled"; }
    },
    setActualProgress(value: number) {
      const bounded = Math.max(this.actualProgress, Math.min(99, Math.round(value)));
      this.actualProgress = bounded;
      this.progress = this.displayProgress;
      this.startProgressAnimation();
    },
    startProgressAnimation() {
      if (this.progressTimer !== null || this.status !== "running") return;
      this.progressTimer = setInterval(() => {
        if (this.displayProgress >= this.actualProgress) {
          const timer = this.progressTimer;
          this.progressTimer = null;
          if (timer !== null) clearInterval(timer);
          return;
        }
        this.displayProgress = Math.min(this.actualProgress, this.displayProgress + 1);
        this.progress = this.displayProgress;
        if (this.task) this.task.progress = this.displayProgress;
      }, 180);
    },
    stopProgressAnimation() {
      if (this.progressTimer !== null) clearInterval(this.progressTimer);
      this.progressTimer = null;
      this.progress = this.displayProgress;
    },
  },
});
