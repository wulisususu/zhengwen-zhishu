export interface SseMessage {
  event: string;
  data: string;
}

function parseBlock(block: string): SseMessage | null {
  let event = "message";
  const data: string[] = [];

  for (const line of block.split(/\r\n|\r|\n/)) {
    if (!line || line.startsWith(":")) continue;

    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") event = value;
    if (field === "data") data.push(value);
  }

  return data.length > 0 ? { event, data: data.join("\n") } : null;
}

function takeFrame(buffer: string): { frame: string; rest: string } | null {
  const boundary = /\r?\n\r?\n/.exec(buffer);
  if (!boundary || boundary.index === undefined) return null;

  return {
    frame: buffer.slice(0, boundary.index),
    rest: buffer.slice(boundary.index + boundary[0].length),
  };
}

export async function* parseSseStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<SseMessage> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let reachedEnd = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) { reachedEnd = true; break; }
      buffer += decoder.decode(value, { stream: true });

      let current = takeFrame(buffer);
      while (current) {
        buffer = current.rest;
        const message = parseBlock(current.frame);
        if (message) yield message;
        current = takeFrame(buffer);
      }
    }

    buffer += decoder.decode();
    let current = takeFrame(buffer);
    while (current) {
      buffer = current.rest;
      const message = parseBlock(current.frame);
      if (message) yield message;
      current = takeFrame(buffer);
    }

    const finalMessage = parseBlock(buffer);
    if (finalMessage) yield finalMessage;
  } finally {
    if (!reachedEnd) {
      try { await reader.cancel(); } catch { /* The response may already be closed by the browser. */ }
    }
    reader.releaseLock();
  }
}
