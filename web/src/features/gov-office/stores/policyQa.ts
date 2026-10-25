import { defineStore } from "pinia";
import { getGovOfficeAdapter, GovOfficeError } from "../adapters";
import type { AskOptions, Citation, QaSession } from "../types";

export const usePolicyQaStore = defineStore("policyQa", {
  state: () => ({
    sessions: [] as QaSession[],
    citations: {} as Record<string, Citation>,
    activeSessionId: "",
    selectedCitationId: "",
    asking: false,
    error: "",
  }),
  getters: {
    activeSession: (state) => state.sessions.find((s) => s.id === state.activeSessionId) ?? null,
  },
  actions: {
    async load() {
      const adapter = getGovOfficeAdapter();
      this.sessions = await adapter.listQaSessions();
      const ids = [...new Set(this.sessions.flatMap((s) => s.turns.flatMap((t) => t.answer.citationIds)))];
      const list = await adapter.getCitations(ids);
      this.citations = Object.fromEntries(list.map((c) => [c.id, c]));
      if (!this.activeSessionId && this.sessions.length) this.activeSessionId = this.sessions[0].id;
    },
    selectSession(id: string) {
      this.activeSessionId = id;
      this.selectedCitationId = "";
    },
    newSession() {
      const id = `local-${Date.now()}`;
      this.sessions = [
        { id, origin: "demo", title: "新建问答", updatedAt: "刚刚", badge: { label: "未提问", tone: "neutral" }, turns: [] },
        ...this.sessions,
      ];
      this.selectSession(id);
    },
    selectCitation(id: string) {
      this.selectedCitationId = id;
    },
    clearCitation() {
      this.selectedCitationId = "";
    },
    async ask(question: string, options: AskOptions) {
      const session = this.activeSession;
      if (!session || !question.trim()) return;
      this.asking = true;
      this.error = "";
      try {
        const turn = await getGovOfficeAdapter().askPolicyQuestion(session.id, question.trim(), options);
        session.turns.push(turn);
        if (session.title === "新建问答") session.title = question.trim().slice(0, 18);
      } catch (err) {
        this.error = err instanceof GovOfficeError ? err.message : "提问失败，请稍后重试。";
      } finally {
        this.asking = false;
      }
    },
  },
});
