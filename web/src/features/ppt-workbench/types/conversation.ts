export interface PptChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt: string;
  taskId?: string;
  streaming?: boolean;
  kind?: "text" | "stage";
  stage?: import("./task").WorkflowStage;
  progress?: number;
}
