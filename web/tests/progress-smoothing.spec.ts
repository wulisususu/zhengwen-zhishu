import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { usePptGenerationStore } from "../src/features/ppt-workbench/stores/pptGeneration";

describe("PPT progress smoothing", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
  });

  it("moves one visual percent at a time and never reaches 100 before completion", () => {
    const generation = usePptGenerationStore();
    generation.start({ id: "task", projectId: "project", chatId: "chat", stage: "understanding", status: "running", progress: 5, lastAppliedSequence: 0 });
    generation.displayProgress = 5;
    generation.actualProgress = 35;
    generation.setActualProgress(35);

    vi.advanceTimersByTime(180);
    expect(generation.displayProgress).toBe(6);
    vi.advanceTimersByTime(180 * 4);
    expect(generation.displayProgress).toBe(10);
    expect(generation.displayProgress).toBeLessThan(100);

    generation.fail({ code: "failed", message: "failed", retryable: false });
    const stopped = generation.displayProgress;
    vi.advanceTimersByTime(3000);
    expect(generation.displayProgress).toBe(stopped);
  });
});
