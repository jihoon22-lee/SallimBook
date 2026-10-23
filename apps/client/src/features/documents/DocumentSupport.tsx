import { useEffect, useRef, useState } from "react";
import { ApiError, toApiError } from "../../platform/api";
import { FinanceError } from "../finance/FinanceSupport";
import { useMounted } from "../auth/AuthFeedback";
import { MAX_PDF_PAGES } from "./model";
export function DocumentError({ error }: { error: ApiError | null }) {
  const messages: Partial<Record<ApiError["code"], string>> = {
    DOCUMENT_STORAGE_QUOTA_EXCEEDED:
      "문서 보관 한도에 도달했어요. 필요 없는 문서를 삭제한 뒤 다시 시도해 주세요.",
    DOCUMENT_STORAGE_CAPACITY_UNAVAILABLE:
      "지금은 문서를 보관할 공간을 확보할 수 없어요. 잠시 후 같은 파일로 다시 시도해 주세요.",
    DOCUMENT_UPLOAD_BUSY: "다른 파일을 확인하고 있어요. 잠시 후 같은 파일로 다시 시도해 주세요.",
    DOCUMENT_UPLOAD_TIMEOUT:
      "파일 전송 시간이 초과됐어요. 현재 문서 상태를 확인한 뒤 다시 시도해 주세요.",
    DOCUMENT_CARD_DATA:
      "카드 사진이나 카드 비밀정보는 첨부할 수 없어요. 카드 정보가 없는 문서를 선택해 주세요.",
    DOCUMENT_MALWARE: "안전하지 않은 파일이라 보관하지 않았어요.",
    DOCUMENT_UNSAFE:
      "이 파일은 안전하게 열 수 없어 보관하지 않았어요. 일반 PDF·JPEG·PNG 문서를 확인해 주세요.",
    DOCUMENT_IMAGE_UNSUPPORTED:
      "사진·이미지에 지원하지 않는 부가 정보(편집 정보·동영상 등)가 있어 보관하지 않았어요. JPEG로 다시 저장하거나 화면을 다시 캡처해 첨부해 주세요.",
    DOCUMENT_TOO_COMPLEX: `쪽수나 해상도가 커서 검사 시간 안에 확인하지 못했어요. PDF는 ${MAX_PDF_PAGES}쪽 이하로 나누거나 해상도를 낮춰 다시 첨부해 주세요.`,
    DOCUMENT_UNREADABLE:
      "문서 내용을 읽기 어려워 보관하지 않았어요. 글자가 선명한 문서를 선택해 주세요.",
    DOCUMENT_SCAN_UNAVAILABLE:
      "파일 안전 검사를 지금 완료할 수 없어요. 잠시 후 다시 시도해 주세요.",
    DOCUMENT_OCR_UNAVAILABLE: "문서 확인을 지금 완료할 수 없어요. 잠시 후 다시 시도해 주세요.",
    DOCUMENT_STORAGE_UNAVAILABLE: "문서 보관을 지금 완료할 수 없어요. 잠시 후 다시 시도해 주세요.",
    DOCUMENT_UPLOAD_EXPIRED: "업로드 기한이 지났어요. 대기 기록을 삭제한 뒤 새로 첨부해 주세요.",
    DOCUMENT_UNLINKED: "연결 없는 문서예요. 대상에 다시 연결한 후 원본을 저장할 수 있어요.",
    DOCUMENT_NOT_READY: "파일 업로드가 완료되지 않았어요.",
    DOCUMENT_UNAVAILABLE: "삭제됐거나 사용할 수 없는 문서예요.",
    INVALID_DOCUMENT_TARGET: "이 대상에는 문서를 연결할 수 없어요.",
    DOCUMENT_CONTENT_MISMATCH:
      "대기 기록과 파일이 달라요. 처음 선택한 것과 같은 파일을 선택해 주세요.",
    DOCUMENT_CONTENT_EXISTS: "이미 업로드된 문서예요. 현재 문서 상태를 확인해 주세요.",
    DOCUMENT_ALREADY_LINKED: "이미 이 대상에 연결돼 있어요. 현재 연결 이력을 확인해 주세요.",
    DOCUMENT_LINK_ENDED: "이미 종료된 연결이에요. 현재 연결 이력을 확인해 주세요.",
    DOCUMENT_TOO_LARGE: "20MiB 이하 파일을 선택해 주세요.",
    DOCUMENT_CONTENT_LENGTH: "파일 크기를 확인할 수 없어요. 파일을 다시 선택해 주세요.",
    DOCUMENT_CONTENT_TYPE: "PDF·JPEG·PNG 파일을 선택해 주세요.",
    REQUEST_CANCELLED:
      "대기를 중단했어요. 서버에 반영됐을 수 있어요. 같은 입력으로 다시 시도하면 기존 요청을 확인해요.",
  };
  return error && messages[error.code] ? (
    <p role="alert" className="auth-message">
      {messages[error.code]}
    </p>
  ) : (
    <FinanceError error={error} />
  );
}
export function useDocumentCommand() {
  const mounted = useMounted();
  const controller = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    const abort = () => controller.current?.abort();
    window.addEventListener("pagehide", abort);
    return () => {
      abort();
      window.removeEventListener("pagehide", abort);
    };
  }, []);
  async function run<T>(action: (signal: AbortSignal) => Promise<T>): Promise<T | undefined> {
    if (controller.current) return;
    const current = new AbortController();
    controller.current = current;
    setBusy(true);
    setError(null);
    try {
      const result = await action(current.signal);
      if (mounted.current && !current.signal.aborted) return result;
    } catch (failure) {
      if (mounted.current) setError(toApiError(failure));
    } finally {
      if (controller.current === current) controller.current = null;
      if (mounted.current) setBusy(false);
    }
  }
  return { run, busy, error, setError, mounted, cancel: () => controller.current?.abort() };
}
export function CommandFeedback({ command }: { command: ReturnType<typeof useDocumentCommand> }) {
  return (
    <>
      <DocumentError error={command.error} />
      {command.busy && (
        <>
          <p role="status">문서 작업을 확인하고 있어요.</p>
          <button type="button" onClick={command.cancel}>
            문서 요청 대기 중단
          </button>
        </>
      )}
    </>
  );
}
