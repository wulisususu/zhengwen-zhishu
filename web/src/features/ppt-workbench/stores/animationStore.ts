/**
 * P4 Animation Pinia Store
 *
 * Manages animation state per project, synchronized with backend animation revision.
 * Integrates with pptEditor store for element deletion linkage and undo/redo.
 */

import { defineStore } from "pinia";
import { ref, computed } from "vue";
import type {
  AnimationManifest,
  AnimationObject,
  SlideAnimations,
  AnimationGetResponse,
} from "../api/animationApi";
import * as animApi from "../api/animationApi";

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));
let loadEpoch = 0;
let saveInFlight: Promise<void> | null = null;
let mutationSequence = 0;
let savedSequence = 0;

export const useAnimationStore = defineStore("p4Animations", () => {
  // ── State ────────────────────────────────────────────────────
  const projectId = ref<string>("");
  const manifest = ref<AnimationManifest | null>(null);
  const documentRevision = ref<number>(0);
  const animationRevision = ref<number>(1);
  const loading = ref(false);
  const saving = ref(false);
  const error = ref<string | null>(null);
  const lastSaveResult = ref<{ sha256: string; count: number } | null>(null);

  // ── Computed ─────────────────────────────────────────────────
  const currentSlideAnimations = computed(() => {
    // Returns animations for the currently active slide
    // To be set externally via setActiveSlideId()
    return manifest.value?.slides || [];
  });

  const animationCount = computed(() => {
    if (!manifest.value) return 0;
    return manifest.value.slides.reduce((sum: number, s: SlideAnimations) => sum + s.animations.length, 0);
  });

  // ── Actions ──────────────────────────────────────────────────
  async function load(pid: string) {
    const epoch = ++loadEpoch;
    projectId.value = pid;
    loading.value = true;
    error.value = null;
    try {
      const data = await animApi.getAnimations(pid);
      if (epoch !== loadEpoch || projectId.value !== pid) return;
      manifest.value = data.manifest;
      documentRevision.value = data.document_revision;
      animationRevision.value = data.animation_revision;
      mutationSequence = 0;
      savedSequence = 0;
    } catch (e: any) {
      if (epoch !== loadEpoch || projectId.value !== pid) return;
      error.value = e.message || "Failed to load animations";
      manifest.value = { version: 1, project_id: pid, animation_revision: 1, slides: [] };
      documentRevision.value = 0;
      animationRevision.value = 1;
      mutationSequence = 0;
      savedSequence = 0;
    } finally {
      if (epoch === loadEpoch && projectId.value === pid) loading.value = false;
    }
  }

  function reset() {
    loadEpoch += 1;
    projectId.value = "";
    manifest.value = null;
    documentRevision.value = 0;
    animationRevision.value = 1;
    loading.value = false;
    saving.value = false;
    error.value = null;
    lastSaveResult.value = null;
    mutationSequence = 0;
    savedSequence = 0;
  }

  async function save() {
    if (!manifest.value || !projectId.value) return;
    if (saveInFlight) {
      await saveInFlight;
      if (manifest.value && projectId.value && savedSequence < mutationSequence) await save();
      return;
    }
    const pid = projectId.value;
    const currentManifest = manifest.value;
    const currentDocumentRevision = documentRevision.value;
    const currentAnimationRevision = animationRevision.value;
    const sequence = mutationSequence;
    const snapshot = clone(currentManifest);
    saving.value = true;
    error.value = null;
    const current = (async () => {
      try {
        const result = await animApi.saveAnimations(pid, currentDocumentRevision, currentAnimationRevision, snapshot);
        if (projectId.value !== pid || manifest.value !== currentManifest) return;
        animationRevision.value = result.animation_revision;
        documentRevision.value = result.document_revision;
        lastSaveResult.value = { sha256: result.sha256, count: result.animation_count };
        savedSequence = Math.max(savedSequence, sequence);
      } catch (e: any) {
        if (projectId.value === pid && manifest.value === currentManifest) error.value = e.message || "Failed to save animations";
        throw e;
      } finally {
        if (projectId.value === pid) saving.value = false;
      }
    })();
    saveInFlight = current;
    try {
      await current;
    } finally {
      if (saveInFlight === current) saveInFlight = null;
    }
  }

  async function flushSave() {
    if (saveInFlight) await saveInFlight;
    if (manifest.value && projectId.value && savedSequence < mutationSequence) await save();
    if (saveInFlight) await saveInFlight;
  }

  function setDocumentRevision(revision: number) {
    documentRevision.value = revision;
  }

  function markChanged() {
    mutationSequence += 1;
  }

  // ── Slide-level operations ───────────────────────────────────
  function getSlideAnimations(slideId: string): AnimationObject[] {
    if (!manifest.value) return [];
    const slide = manifest.value.slides.find((s: SlideAnimations) => s.slide_id === slideId);
    return slide?.animations || [];
  }

  function addAnimation(slideId: string, anim: AnimationObject) {
    if (!manifest.value) return;
    let slide = manifest.value.slides.find((s: SlideAnimations) => s.slide_id === slideId);
    if (!slide) {
      slide = { slide_id: slideId, animations: [] };
      manifest.value.slides.push(slide);
    }
    slide.animations.push(anim);
    // Normalize orders
    slide.animations.sort((a: AnimationObject, b: AnimationObject) => a.order - b.order);
    markChanged();
  }

  function updateAnimation(slideId: string, animationId: string, updates: Partial<AnimationObject>) {
    if (!manifest.value) return;
    const slide = manifest.value.slides.find((s: SlideAnimations) => s.slide_id === slideId);
    if (!slide) return;
    const idx = slide.animations.findIndex((a: AnimationObject) => a.animation_id === animationId);
    if (idx === -1) return;
    slide.animations[idx] = { ...slide.animations[idx], ...updates };
    markChanged();
  }

  function removeAnimation(slideId: string, animationId: string) {
    if (!manifest.value) return;
    const slide = manifest.value.slides.find((s: SlideAnimations) => s.slide_id === slideId);
    if (!slide) return;
    slide.animations = slide.animations.filter((a: AnimationObject) => a.animation_id !== animationId);
    // Clean up empty slides
    manifest.value.slides = manifest.value.slides.filter((s: SlideAnimations) => s.animations.length > 0);
    markChanged();
  }

  function reorderAnimations(slideId: string, animationIds: string[]) {
    if (!manifest.value) return;
    const slide = manifest.value.slides.find((s: SlideAnimations) => s.slide_id === slideId);
    if (!slide) return;
    const map = new Map(slide.animations.map((a: AnimationObject) => [a.animation_id, a]));
    slide.animations = animationIds
      .filter((id) => map.has(id))
      .map((id, i) => ({ ...map.get(id)!, order: i + 1 }));
    markChanged();
  }

  function cleanupOrphaned(elementIds: string[]) {
    if (!manifest.value) return;
    const idSet = new Set(elementIds);
    for (const slide of manifest.value.slides) {
      slide.animations = slide.animations.filter((a: AnimationObject) => idSet.has(a.element_id));
    }
    manifest.value.slides = manifest.value.slides.filter((s: SlideAnimations) => s.animations.length > 0);
    markChanged();
  }

  function setEnabled(slideId: string, animationId: string, enabled: boolean) {
    updateAnimation(slideId, animationId, { enabled });
  }

  return {
    projectId,
    manifest,
    documentRevision,
    animationRevision,
    loading,
    saving,
    error,
    lastSaveResult,
    currentSlideAnimations,
    animationCount,
    load,
    reset,
    save,
    flushSave,
    setDocumentRevision,
    getSlideAnimations,
    addAnimation,
    updateAnimation,
    removeAnimation,
    reorderAnimations,
    cleanupOrphaned,
    setEnabled,
  };
});
