import type { Page } from "@playwright/test";

/** Synthetic JPEG segment assembly and inspection for upload normalization tests. */
const segment = (marker: number, payload: Buffer) => {
  const header = Buffer.alloc(4);
  header.writeUInt16BE(0xff00 | marker, 0);
  header.writeUInt16BE(payload.length + 2, 2);
  return Buffer.concat([header, payload]);
};

export function withSegments(jpeg: Buffer, segments: Buffer[], trailer?: Buffer): Buffer {
  return Buffer.concat([
    jpeg.subarray(0, 2),
    ...segments,
    jpeg.subarray(2),
    trailer ?? Buffer.alloc(0),
  ]);
}

export function exifOrientation(value: number): Buffer {
  // Big-endian TIFF with one IFD0 entry: 0x0112 Orientation, SHORT, count 1.
  const tiff = Buffer.alloc(26);
  tiff.write("MM\0*", 0, "latin1");
  tiff.writeUInt32BE(8, 4);
  tiff.writeUInt16BE(1, 8);
  tiff.writeUInt16BE(0x0112, 10);
  tiff.writeUInt16BE(3, 12);
  tiff.writeUInt32BE(1, 14);
  tiff.writeUInt16BE(value, 18);
  tiff.writeUInt32BE(0, 22);
  return segment(0xe1, Buffer.concat([Buffer.from("Exif\0\0", "latin1"), tiff]));
}

export const xmp = () =>
  segment(
    0xe1,
    Buffer.from('http://ns.adobe.com/xap/1.0/\0<x:xmpmeta xmlns:x="adobe:ns:meta/"/>', "latin1"),
  );

export const mpf = () => segment(0xe2, Buffer.from("MPF\0MM\0*\0\0\0\x08", "latin1"));

export const seftTrailer = () =>
  Buffer.concat([
    Buffer.from("\0\0\0\x18ftypmp42\0\0\0\0mp42isom", "latin1"),
    Buffer.from("SEFHsynthetic camera trailer onlySEFT", "latin1"),
  ]);

/** Markers in file order (APPn with their ASCII prefix) and the byte count after EOI. */
export function segments(jpeg: Buffer): {
  markers: { marker: number; prefix: string }[];
  trailing: number;
} {
  const markers: { marker: number; prefix: string }[] = [];
  if (jpeg.readUInt16BE(0) !== 0xffd8) throw new Error("synthetic jpeg without SOI");
  let position = 2;
  while (position < jpeg.length) {
    if (jpeg[position] !== 0xff) throw new Error("synthetic jpeg marker expected");
    while (jpeg[position] === 0xff) position++;
    const marker = jpeg[position++]!;
    if (marker === 0xd9) return { markers, trailing: jpeg.length - position };
    const length = jpeg.readUInt16BE(position);
    const payload = jpeg.subarray(position + 2, position + length);
    const prefix =
      marker >= 0xe0 && marker <= 0xef
        ? /^[\x20-\x7e]*/.exec(payload.subarray(0, 32).toString("latin1"))![0]
        : "";
    markers.push({ marker, prefix });
    position += length;
    if (marker === 0xda) {
      // Skip entropy-coded data: stuffed 0xFF00, restart markers and fill bytes.
      while (position + 1 < jpeg.length) {
        if (jpeg[position] !== 0xff) position++;
        else if (
          jpeg[position + 1] === 0x00 ||
          (jpeg[position + 1]! >= 0xd0 && jpeg[position + 1]! <= 0xd7)
        )
          position += 2;
        else if (jpeg[position + 1] === 0xff) position++;
        else break;
      }
    }
  }
  throw new Error("synthetic jpeg without EOI");
}

export async function canvasJpeg(
  page: Page,
  width: number,
  height: number,
  pattern: "plain" | "left-dark",
): Promise<Buffer> {
  const data = await page.evaluate(
    ({ width, height, pattern }) => {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d")!;
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, width, height);
      if (pattern === "left-dark") {
        context.fillStyle = "#000000";
        context.fillRect(0, 0, width / 2, height);
      }
      context.fillStyle = "#808080";
      context.font = `${Math.max(16, Math.round(height / 12))}px sans-serif`;
      context.fillText("SYNTHETIC RECEIPT", width * 0.55, height / 2);
      return canvas.toDataURL("image/jpeg", 0.92);
    },
    { width, height, pattern },
  );
  return Buffer.from(data.slice(data.indexOf(",") + 1), "base64");
}
