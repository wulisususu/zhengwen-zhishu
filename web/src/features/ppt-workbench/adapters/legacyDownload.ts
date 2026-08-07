import type { DownloadedPptFile } from "./PptWorkflowAdapter";
import type { PptExportArtifact } from "../types/project";

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export class LegacyDownloadError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "LegacyDownloadError";
  }
}

function cleanFilename(value: string, stripPath = true): string {
  const source = stripPath ? (value.split(/[\\/]/).at(-1) ?? value) : value;
  const cleaned = source.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").trim();
  if (!cleaned) return "presentation.pptx";
  return cleaned.toLowerCase().endsWith(".pptx") ? cleaned : `${cleaned}.pptx`;
}

export function filenameFromContentDisposition(header: string | null, fallbackTitle: string): string {
  if (header) {
    const encodedValue = /filename\*\s*=\s*([^;]+)/i.exec(header)?.[1]?.trim().replace(/^"|"$/g, "");
    if (encodedValue) {
      const encoded = /^[^']*'[^']*'(.*)$/.exec(encodedValue)?.[1] ?? encodedValue;
      try {
        return cleanFilename(decodeURIComponent(encoded));
      } catch {
        return cleanFilename(encoded);
      }
    }

    const plain = /filename\s*=\s*(?:"([^"]+)"|([^;]+))/i.exec(header);
    const value = plain?.[1] ?? plain?.[2]?.trim();
    if (value) return cleanFilename(value);
  }

  return cleanFilename(fallbackTitle, false);
}

export async function digestBlobSha256(blob: Blob): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new LegacyDownloadError("DOWNLOAD_SHA256_UNAVAILABLE", "当前浏览器无法校验下载文件");
  }
  const digest = await globalThis.crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function saveBlobWithObjectUrl(blob: Blob, filename: string): void {
  if (typeof document === "undefined") {
    throw new LegacyDownloadError("DOWNLOAD_SAVE_UNAVAILABLE", "当前环境无法保存下载文件");
  }
  const objectUrl = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

export interface DownloadLegacyArtifactOptions {
  artifact: PptExportArtifact;
  fallbackTitle: string;
  token: string;
  fetchImpl: FetchLike;
  saveBlob: (blob: Blob, filename: string) => void | Promise<void>;
  digestSha256: (blob: Blob) => Promise<string>;
  verifySha256: boolean;
  onUnauthorized?: () => void | Promise<void>;
}

export async function downloadLegacyArtifact(options: DownloadLegacyArtifactOptions): Promise<DownloadedPptFile> {
  const response = await options.fetchImpl(options.artifact.downloadUrl, {
    method: "GET",
    headers: { Authorization: `Bearer ${options.token}` },
  });

  if (response.status === 401) {
    await options.onUnauthorized?.();
    throw new LegacyDownloadError("AUTHENTICATION_REQUIRED", "登录状态已失效，请重新登录");
  }
  if (!response.ok) {
    throw new LegacyDownloadError("DOWNLOAD_HTTP_ERROR", `PPT 下载失败（HTTP ${response.status}）`);
  }

  const blob = await response.blob();
  if (blob.size !== options.artifact.size) {
    throw new LegacyDownloadError("DOWNLOAD_SIZE_MISMATCH", "下载文件大小与服务器记录不一致");
  }

  let sha256: string | undefined;
  if (options.verifySha256) {
    sha256 = (await options.digestSha256(blob)).toLowerCase();
    if (sha256 !== options.artifact.sha256.toLowerCase()) {
      throw new LegacyDownloadError("DOWNLOAD_SHA256_MISMATCH", "下载文件完整性校验失败");
    }
  }

  const filename = filenameFromContentDisposition(
    response.headers.get("Content-Disposition"),
    options.fallbackTitle,
  );
  await options.saveBlob(blob, filename);
  return { filename, size: blob.size, sha256 };
}
