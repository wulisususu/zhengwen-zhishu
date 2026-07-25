const leadingRequest = /^(?:请(?:帮我)?|帮我|请你|我要|我想要|为我)?\s*(?:生成|制作|创建|做|写)?\s*(?:一份|一个|一套|一页)?\s*/u;
const trailingFormat = /\s*(?:PPTX?|幻灯片|演示文稿|演示文件)\s*$/iu;

export function derivePromptDisplayTitle(prompt: string): string {
  const normalized = prompt
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 160);
  const concise = normalized
    .replace(leadingRequest, "")
    .replace(trailingFormat, "")
    .replace(/^[：:，,。.!！？?\-—\s]+|[：:，,。.!！？?\-—\s]+$/g, "")
    .trim();
  return (concise || "演示文稿").slice(0, 32);
}
