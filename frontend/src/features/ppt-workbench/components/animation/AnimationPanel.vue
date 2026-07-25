<!--
  P4 Animation Panel — Right-side inspector panel for object animations.
  Shows animations for the currently selected element on the current slide.

  Dependencies:
  - useAnimationStore from ../../stores/animationStore
  - usePptEditor from ../../stores/pptEditor
-->
<template>
  <div class="p4-animation-panel" :class="{ collapsed }">
    <!-- Header -->
    <div class="panel-header" @click="collapsed = !collapsed">
      <span class="panel-title">
        <span class="icon">🎬</span>
        {{ t('animation.title') }}
      </span>
      <span class="collapse-icon">{{ collapsed ? '▶' : '▼' }}</span>
    </div>

    <template v-if="!collapsed">
      <!-- No element selected -->
      <div v-if="!selectedElementIds.length" class="empty-state">
        <p>{{ t('animation.select_element') }}</p>
      </div>

      <!-- Element selected -->
      <template v-else>
        <!-- Master/Layout inheritance notice -->
        <div v-if="isInheritedElement" class="notice warning">
          {{ t('animation.inherited_notice') }}
        </div>

        <!-- Current element animations -->
        <div class="section">
          <div class="section-header">
            <h4>{{ t('animation.element_animations') }}</h4>
            <button
              v-if="!isInheritedElement && !isLockedVector"
              class="btn-add"
              @click="showAddForm = !showAddForm"
            >
              + {{ t('animation.add') }}
            </button>
          </div>

          <!-- Animation list for current element -->
          <div v-if="currentAnimations.length === 0" class="empty-hint">
            {{ t('animation.no_animations') }}
          </div>
          <div
            v-for="anim in currentAnimations"
            :key="anim.animation_id"
            class="animation-card"
            :class="{ disabled: !anim.enabled }"
            draggable="true"
            @dragstart="onDragStart(anim)"
            @dragover.prevent
            @drop="onDrop(anim)"
          >
            <div class="anim-header">
              <span class="anim-badge" :class="anim.category">{{ t(`animation.category.${anim.category}`) }}</span>
              <span class="anim-effect">{{ anim.effect }}</span>
              <div class="anim-actions">
                <button class="btn-sm" @click="toggleEnabled(anim)" :title="anim.enabled ? t('animation.disable') : t('animation.enable')">
                  {{ anim.enabled ? '👁' : '🚫' }}
                </button>
                <button class="btn-sm danger" @click="confirmDelete(anim)">✕</button>
              </div>
            </div>
            <div class="anim-details" v-if="anim.enabled">
              <div class="anim-row">
                <label>{{ t('animation.trigger') }}</label>
                <select :value="anim.trigger" @change="updateAnim(anim, 'trigger', ($event.target as HTMLSelectElement).value)">
                  <option value="on_click">{{ t('animation.trigger.on_click') }}</option>
                  <option value="with_previous">{{ t('animation.trigger.with_previous') }}</option>
                  <option value="after_previous">{{ t('animation.trigger.after_previous') }}</option>
                </select>
              </div>
              <div class="anim-row">
                <label>{{ t('animation.duration') }} (ms)</label>
                <input type="number" :value="anim.duration_ms" min="100" max="10000" step="50"
                  @change="updateAnim(anim, 'duration_ms', Number(($event.target as HTMLInputElement).value))" />
              </div>
              <div class="anim-row">
                <label>{{ t('animation.delay') }} (ms)</label>
                <input type="number" :value="anim.delay_ms" min="0" max="60000" step="50"
                  @change="updateAnim(anim, 'delay_ms', Number(($event.target as HTMLInputElement).value))" />
              </div>
            </div>
          </div>
        </div>

        <!-- Add animation form -->
        <div v-if="showAddForm" class="section add-form">
          <h5>{{ t('animation.add_new') }}</h5>
          <div class="form-row">
            <label>{{ t('animation.category.label') }}</label>
            <select v-model="newAnim.category">
              <option value="entrance">{{ t('animation.category.entrance') }}</option>
            </select>
          </div>
          <div class="form-row">
            <label>{{ t('animation.effect') }}</label>
            <select v-model="newAnim.effect">
              <option v-for="e in effectsForCategory(newAnim.category)" :key="e" :value="e">{{ e }}</option>
            </select>
          </div>
          <div class="form-actions">
            <button class="btn-primary" @click="doAdd">{{ t('animation.add') }}</button>
            <button class="btn-cancel" @click="showAddForm = false">{{ t('animation.cancel') }}</button>
          </div>
        </div>

        <!-- All slide animations (if viewing) -->
        <div class="section" v-if="slideAnimations.length > 0">
          <div class="section-header">
            <h4>{{ t('animation.slide_animations') }} ({{ slideAnimations.length }})</h4>
            <button class="btn-sm" @click="previewSlide">{{ t('animation.preview') }}</button>
          </div>
        </div>

        <!-- Preview notice -->
        <div class="notice info">
          {{ t('animation.preview_disclaimer') }}
        </div>
      </template>

      <!-- Error display -->
      <div v-if="store.error" class="error-banner">
        {{ store.error }}
        <button @click="store.error = null">✕</button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { useAnimationStore } from "../../stores/animationStore";
import { usePptEditorStore } from "../../stores/pptEditor";
import type { AnimationObject } from "../../api/animationApi";

// ── i18n helpers (simplified) ─────────────────────────────────
const t = (key: string): string => {
  const map: Record<string, string> = {
    "animation.title": "Animation",
    "animation.select_element": "Select an element to edit its animations",
    "animation.inherited_notice": "Master/Layout elements cannot be animated",
    "animation.element_animations": "Element Animations",
    "animation.add": "Add",
    "animation.add_new": "New Animation",
    "animation.cancel": "Cancel",
    "animation.no_animations": "No animations on this element",
    "animation.disable": "Disable",
    "animation.enable": "Enable",
    "animation.trigger": "Trigger",
    "animation.trigger.on_click": "On Click",
    "animation.trigger.with_previous": "With Previous",
    "animation.trigger.after_previous": "After Previous",
    "animation.duration": "Duration",
    "animation.delay": "Delay",
    "animation.category.label": "Category",
    "animation.category.entrance": "Entrance",
    "animation.category.emphasis": "Emphasis",
    "animation.category.exit": "Exit",
    "animation.effect": "Effect",
    "animation.slide_animations": "Slide Animations",
    "animation.preview": "Preview",
    "animation.preview_disclaimer": "Browser preview is approximate. Animation accuracy is guaranteed in PowerPoint export.",
  };
  return map[key] || key;
};

const effectsForCategory = (_cat: string): string[] => {
  return ["appear", "fade", "wipe", "fly_in", "zoom"];
};

// ── Stores ──────────────────────────────────────────────────
const store = useAnimationStore();
const editor = usePptEditorStore();

// ── Local state ──────────────────────────────────────────────
const collapsed = ref(false);
const showAddForm = ref(false);
const newAnim = ref({
  category: "entrance" as string,
  effect: "fade" as string,
});

// ── Computed ─────────────────────────────────────────────────
const selectedElementIds = computed(() => editor.selectedElementIds || []);
const selectedSlideId = computed(() => editor.selectedSlideId || "");

const currentAnimations = computed(() => {
  if (!selectedSlideId.value) return [];
  return store.getSlideAnimations(selectedSlideId.value);
});

const slideAnimations = computed(() => {
  if (!selectedSlideId.value) return [];
  return store.getSlideAnimations(selectedSlideId.value);
});

const selectedElement = computed(() => editor.document?.slides
  .flatMap((slide) => slide.elements)
  .find((element) => element.id === selectedElementIds.value[0]) as any);

const isInheritedElement = computed(() => {
  const el = selectedElement.value;
  return Boolean(el?.inherited || el?.is_master_element || el?.is_layout_element);
});

const isLockedVector = computed(() => selectedElement.value?.type === "lockedVector");

watch(() => editor.projectId, async (projectId) => {
  if (!projectId) {
    store.reset();
    return;
  }
  if (store.projectId !== projectId) await store.load(projectId);
}, { immediate: true });

// ── Methods ──────────────────────────────────────────────────
function persist() {
  void store.save().catch(() => undefined);
}

function updateAnim(anim: AnimationObject, field: string, value: any) {
  store.updateAnimation(selectedSlideId.value, anim.animation_id, { [field]: value });
  persist();
}

function toggleEnabled(anim: AnimationObject) {
  store.setEnabled(selectedSlideId.value, anim.animation_id, !anim.enabled);
  persist();
}

function confirmDelete(anim: AnimationObject) {
  store.removeAnimation(selectedSlideId.value, anim.animation_id);
  persist();
}

function doAdd() {
  const slideAnims = store.getSlideAnimations(selectedSlideId.value);
  const maxOrder = slideAnims.reduce((max: number, a: any) => Math.max(max, a.order), 0);

  const anim: AnimationObject = {
    animation_id: `anim_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    element_id: selectedElementIds.value[0],
    category: "entrance",
    effect: newAnim.value.effect as AnimationObject["effect"],
    order: maxOrder + 1,
    duration_ms: 500,
    delay_ms: 0,
    trigger: "on_click",
    direction: null,
    repeat: 1,
    enabled: true,
  };

  store.addAnimation(selectedSlideId.value, anim);
  persist();
  showAddForm.value = false;
  newAnim.value = { category: "entrance", effect: "fade" };
}

// Drag-and-drop reordering
let draggedAnim: AnimationObject | null = null;

function onDragStart(anim: AnimationObject) {
  draggedAnim = anim;
}

function onDrop(targetAnim: AnimationObject) {
  if (!draggedAnim || draggedAnim.animation_id === targetAnim.animation_id) return;
  const ids = slideAnimations.value.map((a: any) => a.animation_id);
  const fromIdx = ids.indexOf(draggedAnim.animation_id);
  const toIdx = ids.indexOf(targetAnim.animation_id);
  if (fromIdx === -1 || toIdx === -1) return;
  ids.splice(fromIdx, 1);
  ids.splice(toIdx, 0, draggedAnim.animation_id);
  store.reorderAnimations(selectedSlideId.value, ids);
  persist();
  draggedAnim = null;
}

function previewSlide() {
  // Browser-approximate preview — shows CSS animations in order
  // Implementation deferred to full preview system
  console.log("Preview slide animations (approximate)");
}

// ── Watchers ─────────────────────────────────────────────────
watch([selectedElementIds, selectedSlideId], () => {
  showAddForm.value = false;
});
</script>

<style scoped>
.p4-animation-panel {
  background: var(--panel-bg, #f8f9fa);
  border-left: 1px solid var(--border-color, #e0e0e0);
  font-size: 13px;
  overflow-y: auto;
  height: 100%;
}

.p4-animation-panel.collapsed {
  width: 32px;
  min-width: 32px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  background: var(--panel-header-bg, #e8ecf1);
  font-weight: 600;
  user-select: none;
}

.panel-title .icon {
  margin-right: 6px;
}

.empty-state {
  padding: 24px 12px;
  text-align: center;
  color: var(--text-muted, #888);
}

.notice {
  padding: 8px 12px;
  margin: 8px;
  border-radius: 4px;
  font-size: 12px;
}

.notice.warning {
  background: #fff3cd;
  color: #856404;
}

.notice.info {
  background: #d1ecf1;
  color: #0c5460;
}

.section {
  padding: 8px 12px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.section-header h4 {
  margin: 0;
  font-size: 13px;
}

.empty-hint {
  padding: 12px 0;
  text-align: center;
  color: var(--text-muted, #aaa);
  font-style: italic;
}

.animation-card {
  border: 1px solid var(--border-color, #ddd);
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 6px;
  background: var(--card-bg, #fff);
  cursor: grab;
}

.animation-card.disabled {
  opacity: 0.5;
  background: var(--card-disabled-bg, #f0f0f0);
}

.anim-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.anim-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  font-weight: 600;
  text-transform: uppercase;
}

.anim-badge.entrance {
  background: #d4edda;
  color: #155724;
}

.anim-badge.emphasis {
  background: #cce5ff;
  color: #004085;
}

.anim-badge.exit {
  background: #f8d7da;
  color: #721c24;
}

.anim-effect {
  flex: 1;
  font-weight: 500;
}

.anim-actions {
  display: flex;
  gap: 4px;
}

.anim-details {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--border-light, #eee);
}

.anim-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.anim-row label {
  width: 80px;
  font-size: 11px;
  color: var(--text-muted, #666);
}

.anim-row select,
.anim-row input {
  flex: 1;
  padding: 2px 6px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 3px;
  font-size: 12px;
}

.btn-add {
  padding: 2px 8px;
  font-size: 12px;
  border: 1px solid var(--primary, #1976d2);
  border-radius: 4px;
  background: var(--primary, #1976d2);
  color: #fff;
  cursor: pointer;
}

.btn-sm {
  padding: 1px 6px;
  font-size: 11px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 3px;
  background: transparent;
  cursor: pointer;
}

.btn-sm.danger {
  border-color: var(--danger, #dc3545);
  color: var(--danger, #dc3545);
}

.btn-primary {
  padding: 4px 12px;
  font-size: 12px;
  border: none;
  border-radius: 4px;
  background: var(--primary, #1976d2);
  color: #fff;
  cursor: pointer;
}

.btn-cancel {
  padding: 4px 12px;
  font-size: 12px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
}

.add-form {
  background: var(--highlight-bg, #f0f7ff);
  border-radius: 6px;
  margin: 8px 12px;
}

.add-form h5 {
  margin: 0 0 8px 0;
  font-size: 12px;
}

.form-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.form-row label {
  width: 60px;
  font-size: 11px;
  color: var(--text-muted, #666);
}

.form-row select {
  flex: 1;
  padding: 2px 6px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 3px;
  font-size: 12px;
}

.form-actions {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}

.error-banner {
  padding: 8px 12px;
  margin: 8px;
  background: #f8d7da;
  color: #721c24;
  border-radius: 4px;
  font-size: 12px;
  display: flex;
  justify-content: space-between;
}

.error-banner button {
  background: none;
  border: none;
  cursor: pointer;
}
</style>
