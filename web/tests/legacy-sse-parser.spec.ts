import { describe, expect, it } from "vitest";
import { parseSseStream } from "../src/features/ppt-workbench/adapters/legacySseParser";
import {
  byteStream,
  multilineLegacyFrameChunks,
  multilineLegacyMessages,
  splitLegacyFrames,
  splitLegacyMessages,
} from "./fixtures/legacySse";

async function collect(stream: ReadableStream<Uint8Array>) {
  const messages = [];
  for await (const message of parseSseStream(stream)) messages.push(message);
  return messages;
}

describe("Legacy SSE frame parser", () => {
  it("reassembles event and data fields split across byte chunks", async () => {
    const messages = await collect(byteStream(splitLegacyFrames));

    expect(messages).toEqual(splitLegacyMessages);
  });

  it("joins multiline data, ignores comments, and flushes the final frame", async () => {
    const messages = await collect(byteStream(multilineLegacyFrameChunks));

    expect(messages).toEqual(multilineLegacyMessages);
  });
});
