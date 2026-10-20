import type { components } from "@sallimbook/api-client";
import type { Document } from "../documents/model";
export type ExportInput = components["schemas"]["ExportRequest"];
export type ExportFormat = NonNullable<ExportInput["formats"]>[number];
export const MAX_DOCUMENTS = 10;
export const MAX_DOCUMENT_BYTES = 40 * 1024 * 1024;
export const MAX_ARCHIVE_BYTES = 64 * 1024 * 1024;
export const EXPORT_TIMEOUT_MS = 150_000;
export function exportable(row: Document) {
  return row.state === "ready" && row.active_link_count > 0;
}
export function selectionProblem(formats: ExportFormat[], documents: Document[]): string | null {
  if (!formats.length) return "JSON 또는 CSV 형식을 하나 이상 선택해 주세요.";
  if (documents.length > MAX_DOCUMENTS) return "문서 원본은 10개까지 선택할 수 있어요.";
  if (documents.some((row) => !exportable(row)))
    return "보관이 완료되고 현재 연결이 있는 문서만 내보낼 수 있어요.";
  if (documents.reduce((sum, row) => sum + row.size_bytes, 0) > MAX_DOCUMENT_BYTES)
    return "선택한 문서 원본의 합계는 40MiB 이하여야 해요. 일부 문서를 해제해 주세요.";
  return null;
}
export function byteLabel(value: number) {
  return value < 1024
    ? `${value.toLocaleString("ko-KR")}바이트`
    : value < 1024 * 1024
      ? `${(value / 1024).toFixed(1)}KiB`
      : `${(value / (1024 * 1024)).toFixed(1)}MiB`;
}
