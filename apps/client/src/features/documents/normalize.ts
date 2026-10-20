/** Camera JPEG normalization before hashing: orientation applied, long edge bounded, metadata dropped. */
export const MAX_LONG_EDGE = 3072;
export const JPEG_QUALITY = 0.9;

export function targetSize(width: number, height: number): { width: number; height: number } {
  const scale = Math.min(1, MAX_LONG_EDGE / Math.max(width, height));
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

function aborted(signal: AbortSignal) {
  if (signal.aborted) throw new DOMException("", "AbortError");
}

/**
 * Re-encodes a JPEG through a CPU canvas so the same file always yields the same bytes
 * (pending uploads are resumed by name, type, size and SHA-256). Returns null when the
 * browser cannot decode or encode it; the original bytes are then uploaded for the server
 * to judge.
 */
export async function normalizeJpeg(
  bytes: ArrayBuffer,
  signal: AbortSignal,
): Promise<ArrayBuffer | null> {
  let bitmap: ImageBitmap | null = null;
  const canvas = document.createElement("canvas");
  try {
    try {
      bitmap = await createImageBitmap(new Blob([bytes], { type: "image/jpeg" }), {
        imageOrientation: "from-image",
      });
    } catch {
      return null;
    }
    aborted(signal);
    const size = targetSize(bitmap.width, bitmap.height);
    canvas.width = size.width;
    canvas.height = size.height;
    const context = canvas.getContext("2d", { alpha: false, willReadFrequently: true });
    if (!context) return null;
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";
    context.drawImage(bitmap, 0, 0, size.width, size.height);
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY),
    );
    aborted(signal);
    if (!blob) return null;
    const result = await blob.arrayBuffer();
    aborted(signal);
    return result;
  } finally {
    bitmap?.close();
    canvas.width = 0;
    canvas.height = 0;
  }
}
