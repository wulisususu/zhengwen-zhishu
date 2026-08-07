import { defineStore } from "pinia";
import type { PptChatMessage } from "../types/conversation";

export const usePptConversationStore = defineStore("pptConversation", {
  state: () => ({ chatId: null as string | null, messages: [] as PptChatMessage[], streamingMessageId: null as string | null, draft: "" }),
  actions: {
    restoreSession(chatId: string | null, messages: PptChatMessage[]) {
      this.chatId = chatId;
      this.messages = messages.map((message) => ({ ...message, streaming: false }));
      this.streamingMessageId = null;
      this.draft = "";
    },
    append(message: PptChatMessage) { this.messages.push(message); },
    appendDelta(taskId: string, text: string) {
      const message = this.messages.find((item) => item.id === this.streamingMessageId);
      if (message) { message.content += text; return; }
      const id = `assistant-${taskId}`;
      this.messages.push({ id, role: "assistant", content: text, createdAt: new Date().toISOString(), taskId, streaming: true });
      this.streamingMessageId = id;
    },
    upsertStage(taskId: string, stage: import("../types/task").WorkflowStage, content: string, progress?: number) {
      const id = `stage-${taskId}-${stage}`;
      const message = this.messages.find((item) => item.id === id);
      if (message) {
        message.content = content;
        message.progress = progress;
        message.streaming = true;
        return;
      }
      this.messages.push({
        id,
        role: "assistant",
        kind: "stage",
        stage,
        content,
        progress,
        createdAt: new Date().toISOString(),
        taskId,
        streaming: true,
      });
    },
    finishStream() {
      const message = this.messages.find((item) => item.id === this.streamingMessageId);
      if (message) message.streaming = false;
      this.messages.forEach((item) => {
        if (item.kind === "stage") item.streaming = false;
      });
      this.streamingMessageId = null;
    },
  },
});
