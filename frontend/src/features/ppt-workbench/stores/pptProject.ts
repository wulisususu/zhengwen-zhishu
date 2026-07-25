import { defineStore } from "pinia";
import type { PptExportArtifact, PresentationProject } from "../types/project";
import type { OutlineItem, PresentationTheme, Slide, ValidationResult } from "../types/presentation";
import type { PptChangeProposal } from "../types/proposal";
import type { PersistedProjectSession } from "../persistence/projectSessionStorage";

export const usePptProjectStore = defineStore("pptProject", {
  state: () => ({
    project: null as PresentationProject | null,
    outline: [] as OutlineItem[],
    slides: [] as Slide[],
    theme: null as PresentationTheme | null,
    validation: null as ValidationResult | null,
    proposals: [] as PptChangeProposal[],
    projectRevision: 0,
  }),
  actions: {
    restoreSession(snapshot: PersistedProjectSession) {
      this.project = snapshot.project;
      this.outline = snapshot.outline;
      this.slides = snapshot.slides;
      this.theme = snapshot.theme;
      this.validation = snapshot.validation;
      this.proposals = snapshot.proposals;
      this.projectRevision = snapshot.projectRevision;
      if (this.project) {
        this.project.outline = this.outline;
        this.project.presentation.slides = this.slides;
        this.project.theme = this.theme;
        this.project.validation = this.validation;
      }
    },
    setProject(project: PresentationProject) {
      this.project = project; this.outline = project.outline; this.slides = project.presentation.slides;
      this.theme = project.theme; this.validation = project.validation; this.projectRevision = project.version;
    },
    setDisplayTitle(title: string, source: NonNullable<PresentationProject["titleSource"]>) {
      if (!this.project) return;
      this.project.title = title;
      this.project.titleSource = source;
      this.project.updatedAt = new Date().toISOString();
    },
    addOutlineItem(item: OutlineItem) {
      if (!this.outline.some((existing) => existing.id === item.id)) this.outline.push(item);
    },
    setOutline(outline: OutlineItem[]) { this.outline = outline; },
    setTheme(theme: PresentationTheme) { this.theme = theme; },
    upsertSlide(slide: Slide) {
      const index = this.slides.findIndex((existing) => existing.id === slide.id);
      if (index < 0) this.slides.push(slide); else this.slides.splice(index, 1, slide);
      this.slides.sort((a, b) => a.index - b.index);
    },
    setValidation(validation: ValidationResult) {
      this.validation = validation;
      if (this.project) this.project.validation = validation;
    },
    setExportArtifact(artifact: PptExportArtifact) {
      if (this.project) this.project.exportArtifact = artifact;
    },
    clearExportArtifact() {
      if (this.project) this.project.exportArtifact = null;
    },
    resetGenerationData() {
      this.outline = [];
      this.slides = [];
      this.theme = null;
      this.validation = null;
      this.proposals = [];
      if (this.project) {
        this.project.outline = [];
        this.project.presentation.slides = [];
        this.project.theme = null;
        this.project.validation = null;
        this.project.exportArtifact = null;
      }
    },
    addProposal(proposal: PptChangeProposal) {
      if (!this.proposals.some((existing) => existing.id === proposal.id)) this.proposals.push(proposal);
    },
    updateProposalStatus(id: string, status: PptChangeProposal["status"]) {
      const proposal = this.proposals.find((item) => item.id === id);
      if (proposal) proposal.status = status;
    },
    applyApprovedProposal(id: string) {
      const proposal = this.proposals.find((item) => item.id === id);
      if (!proposal || proposal.status !== "approved" || proposal.target !== "slide") return;

      const patch = proposal.patch as { field?: string; to?: unknown };
      const slide = this.slides.find((item) => item.id === proposal.targetId);
      if (!slide || patch.field !== "title" || typeof patch.to !== "string") return;

      slide.title = patch.to;
      slide.revision += 1;
      proposal.status = "applied";
      this.projectRevision += 1;
    },
    approveAndApplyProposal(id: string) {
      this.updateProposalStatus(id, "approved");
      this.applyApprovedProposal(id);
    },
  },
});
