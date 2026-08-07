import { describe, expect, it, vi } from "vitest";
import {
  LegacyPptMasterAdapter,
  type LegacyPptMasterAdapterOptions,
} from "../src/features/ppt-workbench/adapters/LegacyPptMasterAdapter";
import type { PptExportArtifact } from "../src/features/ppt-workbench/types/project";

const artifact: PptExportArtifact = {
  fileId: 594,
  downloadUrl: "http://backend.test:8000/api/v1/files/594/download",
  size: 4,
  sha256: "expected-sha256",
  valid: true,
  warnings: [],
};

function options(overrides: Partial<LegacyPptMasterAdapterOptions> = {}): LegacyPptMasterAdapterOptions {
  return {
    baseUrl: "http://backend.test:8000",
    getAccessToken: () => "test-token",
    requestIdFactory: () => "request-1",
    fetchImpl: vi.fn(async () => new Response(new Blob(["pptx"]), {
      status: 200,
      headers: { "Content-Disposition": 'attachment; filename="backend-result.pptx"' },
    })),
    saveBlob: vi.fn(),
    digestSha256: vi.fn(async () => "expected-sha256"),
    ...overrides,
  };
}

describe("Legacy authenticated download", () => {
  it("fetches the Blob with Bearer auth and prefers Content-Disposition", async () => {
    const fetchImpl = vi.fn(async () => new Response(new Blob(["pptx"]), {
      status: 200,
      headers: { "Content-Disposition": "attachment; filename*=UTF-8''%E4%BA%A7%E5%93%81%E6%96%B9%E6%A1%88.pptx" },
    }));
    const saveBlob = vi.fn();
    const adapter = new LegacyPptMasterAdapter(options({ fetchImpl, saveBlob }));

    const downloaded = await adapter.download(artifact, "备用项目名");

    expect(fetchImpl).toHaveBeenCalledWith(artifact.downloadUrl, {
      method: "GET",
      headers: { Authorization: "Bearer test-token" },
    });
    expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), "产品方案.pptx");
    expect(downloaded).toEqual({ filename: "产品方案.pptx", size: 4, sha256: "expected-sha256" });
  });

  it("uses a safe project-title filename when the response omits one", async () => {
    const saveBlob = vi.fn();
    const adapter = new LegacyPptMasterAdapter(options({
      fetchImpl: vi.fn(async () => new Response(new Blob(["pptx"]), { status: 200 })),
      saveBlob,
    }));

    await adapter.download(artifact, "2026/产品:方案");

    expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), "2026_产品_方案.pptx");
  });

  it("parses RFC 5987 filenames that include a language tag", async () => {
    const saveBlob = vi.fn();
    const adapter = new LegacyPptMasterAdapter(options({
      fetchImpl: vi.fn(async () => new Response(new Blob(["pptx"]), {
        status: 200,
        headers: { "Content-Disposition": "attachment; filename*=UTF-8'en'%E4%BA%A7%E5%93%81.pptx" },
      })),
      saveBlob,
    }));

    await adapter.download(artifact, "备用名");

    expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), "产品.pptx");
  });

  it("refuses to send a Bearer token to a cross-origin artifact URL", async () => {
    const fetchImpl = vi.fn();
    const adapter = new LegacyPptMasterAdapter(options({ fetchImpl }));

    await expect(adapter.download({ ...artifact, downloadUrl: "https://untrusted.example/file.pptx" }, "项目"))
      .rejects.toMatchObject({ code: "LEGACY_DOWNLOAD_ORIGIN_FORBIDDEN" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rejects size and SHA-256 mismatches before saving", async () => {
    const saveBlob = vi.fn();
    const sizeAdapter = new LegacyPptMasterAdapter(options({ saveBlob }));
    await expect(sizeAdapter.download({ ...artifact, size: 5 }, "项目")).rejects.toMatchObject({ code: "DOWNLOAD_SIZE_MISMATCH" });

    const shaAdapter = new LegacyPptMasterAdapter(options({
      saveBlob,
      digestSha256: vi.fn(async () => "different-sha256"),
    }));
    await expect(shaAdapter.download(artifact, "项目")).rejects.toMatchObject({ code: "DOWNLOAD_SHA256_MISMATCH" });
    expect(saveBlob).not.toHaveBeenCalled();
  });

  it("routes an unauthorized download through the host auth callback", async () => {
    const onUnauthorized = vi.fn();
    const adapter = new LegacyPptMasterAdapter(options({
      fetchImpl: vi.fn(async () => new Response(null, { status: 401 })),
      onUnauthorized,
    }));

    await expect(adapter.download(artifact, "项目")).rejects.toMatchObject({ code: "AUTHENTICATION_REQUIRED" });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});
