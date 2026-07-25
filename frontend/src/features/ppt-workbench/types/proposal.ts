export type ProposalTarget = "brief" | "outline" | "slide" | "element" | "theme";
export interface PptChangeProposal { id: string; taskId: string; projectId: string; target: ProposalTarget; targetId?: string; baseProjectVersion: number; status: "pending" | "approved" | "rejected" | "applied" | "failed"; summary: string; patch: unknown; createdAt: string; }
