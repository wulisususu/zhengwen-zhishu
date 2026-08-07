import { watch } from "vue";
import { loadProjectSession, saveProjectSession, type PersistedProjectSession } from "../persistence/projectSessionStorage";
import { usePptConversationStore } from "../stores/pptConversation";
import { usePptGenerationStore } from "../stores/pptGeneration";
import { usePptProjectStore } from "../stores/pptProject";
import { usePptSourcesStore } from "../stores/pptSources";

export function useProjectSessionPersistence(projectId: string) {
  const project = usePptProjectStore();
  const conversation = usePptConversationStore();
  const generation = usePptGenerationStore();
  const sources = usePptSourcesStore();
  const restored = loadProjectSession(projectId);

  if (restored) {
    project.restoreSession(restored);
    conversation.restoreSession(restored.conversation.chatId, restored.conversation.messages);
    generation.restoreStableSnapshot(restored.generation);
    sources.restore(restored.sources);
  }

  const stop = watch(() => ({
    project: project.project,
    outline: project.outline,
    slides: project.slides,
    theme: project.theme,
    validation: project.validation,
    proposals: project.proposals,
    projectRevision: project.projectRevision,
    chatId: conversation.chatId,
    messages: conversation.messages,
    task: generation.task,
    workflowStage: generation.workflowStage,
    status: generation.status,
    progress: generation.progress,
    actualProgress: generation.actualProgress,
    displayProgress: generation.displayProgress,
    error: generation.error,
    sources: { items: sources.items, policy: sources.policy, manifest: sources.manifest },
  }), (state) => {
    if (!state.project || state.project.id !== projectId) return;
    const snapshot: PersistedProjectSession = {
      projectId,
      project: state.project,
      outline: state.outline,
      slides: state.slides,
      theme: state.theme,
      validation: state.validation,
      proposals: state.proposals,
      projectRevision: state.projectRevision,
      conversation: { chatId: state.chatId, messages: state.messages },
      generation: {
        task: state.task,
        workflowStage: state.workflowStage,
        status: state.status,
        progress: state.progress,
        actualProgress: state.actualProgress,
        displayProgress: state.displayProgress,
        error: state.error,
      },
      sources: state.sources,
    };
    saveProjectSession(projectId, snapshot);
  }, { deep: true });

  return { restored: Boolean(restored), stop };
}
