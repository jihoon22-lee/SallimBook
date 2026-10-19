import type { components } from "@sallimbook/api-client";
export type Document = components["schemas"]["DocumentResponse"];
export type DocumentLink = components["schemas"]["DocumentLinkResponse"];
export type Target = components["schemas"]["DocumentTarget"];
export type CreateDocument = components["schemas"]["DocumentCreate"];
export const MAX_BYTES = 20 * 1024 * 1024;
export const targetLabels: Record<Target["kind"], string> = {
  policy: "보험",
  case: "사건",
  medical_node: "진료·약국",
  expense: "의료비",
  claim: "청구",
  appliance: "가전",
  asset: "자산",
};
export const etag = (version: number) => `"${version}"`;
export function fileProblem(file: Pick<File, "name" | "size" | "type">): string | null {
  if (!file.size || file.size > MAX_BYTES) return "파일은 1바이트 이상 20MiB 이하여야 해요.";
  if (
    !file.name ||
    [...file.name].length > 255 ||
    file.name !== file.name.trim() ||
    /[/\\\p{Cc}\p{Cf}]/u.test(file.name)
  )
    return "파일 이름에서 경로·제어 문자와 앞뒤 공백을 제거해 주세요.";
  const extensions: Record<string, string[]> = {
    "application/pdf": ["pdf"],
    "image/png": ["png"],
    "image/jpeg": ["jpg", "jpeg"],
  };
  if (
    !extensions[file.type]?.includes(file.name.split(".").pop()?.toLowerCase() ?? "") ||
    !file.name.includes(".")
  )
    return "이름의 확장자와 파일 형식이 일치하는 PDF·JPEG·PNG를 선택해 주세요.";
  return null;
}
export async function checksum(bytes: ArrayBuffer) {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
export const expired = (row: Document) =>
  row.state === "pending" && Date.parse(row.pending_expires_at) <= Date.now();
export function stateLabel(row: Document) {
  return row.state === "deleted"
    ? "삭제됨"
    : row.state === "ready"
      ? row.active_link_count
        ? "보관 완료"
        : "연결 없는 보관 문서"
      : expired(row)
        ? "업로드 기한 만료"
        : "파일 업로드 대기";
}
export function sameContent(row: Document, input: CreateDocument) {
  return (
    row.original_name === input.original_name &&
    row.mime_type === input.mime_type &&
    row.size_bytes === input.size_bytes &&
    row.checksum_sha256 === input.checksum_sha256
  );
}
