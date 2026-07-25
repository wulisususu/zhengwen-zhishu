export interface WorkflowCapabilities {
  incrementalOutline: boolean;
  incrementalSlides: boolean;
  taskCancellation: boolean;
  taskResume: boolean;
  slideRegeneration: boolean;
  proposalApply: boolean;
  fileDownload: boolean;
}

export const mockWorkflowCapabilities: WorkflowCapabilities = {
  incrementalOutline: true,
  incrementalSlides: true,
  taskCancellation: true,
  taskResume: true,
  slideRegeneration: true,
  proposalApply: true,
  fileDownload: true,
};
