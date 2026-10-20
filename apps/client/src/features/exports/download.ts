import { ApiError } from "../../platform/api";
import { checksum } from "../documents/model";
import { MAX_ARCHIVE_BYTES } from "./model";
export type ExportProgress = {
  phase: "preparing" | "receiving" | "verifying";
  received: number;
  total: number | null;
};
export type ExportFile = {
  bytes: Uint8Array<ArrayBuffer>;
  filename: string;
  exportId: string;
  size: number;
};
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const invalid = () => new ApiError(422, "DOCUMENT_CONTENT_MISMATCH");

/** Consume only a generated client's successful response. Never store or preview archive contents. */
export async function receiveExport(
  response: Response,
  signal: AbortSignal,
  progress: (value: ExportProgress) => void,
): Promise<ExportFile> {
  let bytes: Uint8Array<ArrayBuffer> | undefined;
  let reader: ReadableStreamDefaultReader<Uint8Array<ArrayBufferLike>> | undefined;
  let completed = false;
  const cancel = () => {
    bytes?.fill(0);
    void reader?.cancel().catch(() => {});
  };
  signal.addEventListener("abort", cancel, { once: true });
  try {
    signal.throwIfAborted();
    const id = response.headers.get("X-Export-ID") ?? "";
    const digest = response.headers.get("X-Export-SHA256") ?? "";
    const length = response.headers.get("Content-Length") ?? "";
    const size = Number(length);
    if (
      response.status !== 200 ||
      response.headers.get("Content-Type")?.split(";", 1)[0]?.trim().toLowerCase() !==
        "application/zip" ||
      !uuid.test(id) ||
      !/^[0-9a-f]{64}$/.test(digest) ||
      !/^[1-9][0-9]*$/.test(length) ||
      !Number.isSafeInteger(size) ||
      size < 22 ||
      size > MAX_ARCHIVE_BYTES ||
      !/(?:^|,)\s*no-store\s*(?:,|$)/i.test(response.headers.get("Cache-Control") ?? "") ||
      response.headers.get("X-Content-Type-Options")?.toLowerCase() !== "nosniff" ||
      response.headers.get("Content-Disposition") !==
        `attachment; filename="sallimbook-${id}.zip"` ||
      !response.body
    )
      throw invalid();
    bytes = new Uint8Array(size);
    reader = response.body.getReader();
    let received = 0;
    progress({ phase: "receiving", received, total: size });
    for (;;) {
      signal.throwIfAborted();
      const chunk = await reader.read();
      if (chunk.done) break;
      try {
        signal.throwIfAborted();
        if (chunk.value.byteLength > size - received) throw invalid();
        bytes.set(chunk.value, received);
        received += chunk.value.byteLength;
        progress({ phase: "receiving", received, total: size });
      } finally {
        chunk.value.fill(0);
      }
    }
    signal.throwIfAborted();
    if (
      received !== size ||
      bytes[0] !== 0x50 ||
      bytes[1] !== 0x4b ||
      bytes[2] !== 0x03 ||
      bytes[3] !== 0x04
    )
      throw invalid();
    progress({ phase: "verifying", received, total: size });
    if ((await checksum(bytes.buffer)) !== digest) throw invalid();
    signal.throwIfAborted();
    completed = true;
    return { bytes, filename: `sallimbook-${id}.zip`, exportId: id, size };
  } finally {
    signal.removeEventListener("abort", cancel);
    if (!completed) bytes?.fill(0);
    if (reader) {
      if (!completed) await reader.cancel().catch(() => {});
      reader.releaseLock();
    } else if (!completed && response.body) await response.body.cancel().catch(() => {});
  }
}

export function saveExport(file: ExportFile, signal: AbortSignal) {
  let url: string | undefined;
  let anchor: HTMLAnchorElement | undefined;
  try {
    signal.throwIfAborted();
    url = URL.createObjectURL(new Blob([file.bytes], { type: "application/zip" }));
    anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = file.filename;
    anchor.rel = "noopener";
    document.body.append(anchor);
    signal.throwIfAborted();
    anchor.click();
  } finally {
    anchor?.remove();
    if (url) URL.revokeObjectURL(url);
    file.bytes.fill(0);
  }
}
