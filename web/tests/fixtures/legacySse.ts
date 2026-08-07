export function byteStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();

  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

export const splitLegacyFrames = [
  ": keep-alive\r\nevent: pro",
  "gress\r\ndata: {\"message\":\"正在生成\",",
  "\"progress\":25}\r\n\r\nevent: spec\ndata: {\"theme\":",
  "\"clean\"}\n\nevent: done\ndata: {\"file_id\":594}",
];

export const splitLegacyMessages = [
  { event: "progress", data: '{"message":"正在生成","progress":25}' },
  { event: "spec", data: '{"theme":"clean"}' },
  { event: "done", data: '{"file_id":594}' },
];

export const multilineLegacyFrameChunks = [
  ": ping\n",
  "event: validate\n",
  "data: {\"passed\":true,\n",
  "data: \"warnings\":[]}\n",
];

export const multilineLegacyMessages = [
  { event: "validate", data: '{"passed":true,\n"warnings":[]}' },
];

export const validDoneFrame =
  'event: done\ndata: {"file_id":594,"download_url":"/api/v1/files/594/download","size":14469,"sha256":"abc123","valid":true,"validation_result":{"passed":true,"warnings":[],"errors":[],"blocking_errors":[]}}\n\n';

export const allSuccessfulLegacyFrames = [
  'event: progress\ndata: {"step":"spec","message":"Planning design specification..."}\n\n',
  'event: spec\ndata: {"theme":{"id":"theme-1"}}\n\n',
  'event: validate\ndata: {"passed":true,"warnings":[],"errors":[],"blocking_errors":[]}\n\n',
  'event: done\ndata: {"file_id":594,"download_url":"/api/v1/files/594/download","size":14469,"sha256":"abc123","valid":true,"validation_result":{"passed":true,"warnings":["字体已替换"],"errors":[],"blocking_errors":[]}}\n\n',
].join("");

export const fallbackLegacyFrame =
  'event: fallback\ndata: {"code":"RENDER_FAILED","message":"渲染失败"}\n\n';

export const incompleteLegacyFrames =
  'event: progress\ndata: {"step":"svg","current":1,"total":4,"message":"Generating SVG slides..."}\n\n';

export const invalidDoneFrame =
  'event: done\ndata: {"file_id":594,"download_url":"/api/v1/files/594/download","size":14469,"sha256":"abc123","valid":false,"validation_result":{"passed":true,"warnings":[],"errors":[],"blocking_errors":["发现阻断问题"]}}\n\n';

export const externalOriginDoneFrame =
  'event: done\ndata: {"file_id":594,"download_url":"https://untrusted.example/download.pptx","size":14469,"sha256":"abc123","valid":true,"validation_result":{"passed":true,"warnings":[],"errors":[],"blocking_errors":[]}}\n\n';

export const malformedDoneFrame = 'event: done\ndata: null\n\n';

export const sensitiveFallbackFrame =
  'event: fallback\ndata: {"code":"PIPELINE_FAILED","message":"Traceback: C:\\\\srv\\\\projects\\\\secret.pptx"}\n\n';

export const sensitiveProgressFrame =
  'event: progress\ndata: {"step":"export","message":"Writing /home/service/projects/secret.pptx"}\n\n';

export const workflowCompletionFrames = [
  'event: progress\ndata: {"step":"export","message":"Exporting PPTX..."}\n\n',
  'event: done\ndata: {"file_id":594,"download_url":"/api/v1/files/594/download","size":14469,"sha256":"abc123","valid":true,"validation_result":{"passed":true,"warnings":["字体已替换"],"errors":[],"blocking_errors":[]}}\n\n',
].join("");

export const legacyProgressStageCases = [
  ["parse", "Analyzing user requirements...", "understanding", "正在分析需求"],
  ["spec", "Planning design specification...", "design", "正在规划设计方案"],
  ["svg", "Generating SVG slides...", "slides", "正在生成幻灯片"],
  ["svg_done", "SVG generation completed", "validation", "正在执行质量检查"],
  ["validate", "Validating presentation...", "validation", "正在执行质量检查"],
  ["export", "Exporting PPTX...", "export", "正在导出 PPTX"],
] as const;

export function legacyProgressEvent(step: string, message: string) {
  return { type: "progress", data: { step, message } } as const;
}

export function doneEventWithForbiddenPathGetters() {
  const data: Record<string, unknown> = {
    file_id: 594,
    download_url: "/api/v1/files/594/download",
    size: 14_469,
    sha256: "abc123",
    valid: true,
    validation_result: { passed: true, warnings: [], errors: [], blocking_errors: [] },
  };
  for (const key of ["pptx_path", "filepath", "project_dir"]) {
    Object.defineProperty(data, key, {
      enumerable: true,
      get: () => { throw new Error(`${key} must not be read`); },
    });
  }
  return { type: "done", data } as const;
}
