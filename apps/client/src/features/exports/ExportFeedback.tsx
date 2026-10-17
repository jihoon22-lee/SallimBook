import { Link } from "react-router";
import type { ApiError } from "../../platform/api";
import { authErrorMessage } from "../auth/AuthFeedback";
export function ExportError({ error }: { error: ApiError | null }) {
  if (!error) return null;
  const messages: Partial<Record<ApiError["code"], string>> = {
    EXPORT_BUSY: "다른 내보내기나 관련 작업을 처리하고 있어요. 잠시 후 새 내보내기를 요청해 주세요.",
    EXPORT_TIMEOUT: "내보내기 준비 시간이 초과됐어요. 자동으로 다시 요청하지 않았어요. 잠시 후 선택 내용을 확인하고 다시 시작해 주세요.",
    EXPORT_TOO_LARGE: "내보내기 한도를 초과했어요. 문서 선택을 줄이거나 JSON·CSV 중 한 형식을 선택해 주세요. 전체 업무 기록 자체가 한도를 넘으면 운영자의 확인이 필요해요.",
    EXPORT_DOCUMENT_CHANGED: "선택한 문서의 내용이나 연결 상태가 바뀌었어요. 선택 문서를 새로 확인하고 다시 검토해 주세요.",
    EXPORT_CONFLICT: "자료를 준비하는 동안 기록이 변경됐어요. 선택 내용을 확인한 뒤 새 내보내기를 요청해 주세요.",
    DOCUMENT_CONTENT_MISMATCH: "받은 ZIP의 크기·형식·체크섬을 확인하지 못해 파일을 저장하지 않았어요. 다시 시도해도 같으면 운영자에게 알려 주세요.",
    REAUTHENTICATION_REQUIRED: "최근 5분 이내의 계정 인증이 필요해요. 패스키로 이 내보내기를 확인하거나 비밀번호로 다시 인증해 주세요.",
    STEP_UP_REQUIRED: "이 내보내기의 인증이 만료됐어요. 패스키로 다시 확인하거나 비밀번호로 다시 인증해 주세요.",
    REQUEST_CANCELLED: "내보내기 대기를 중단했어요. 서버에서 파일을 발급했을 수 있지만 이 요청으로 새 파일을 저장하지 않아요. 다시 시작하면 새 시점의 자료를 만들어요.",
    NETWORK_UNAVAILABLE: "연결이 끊겨 ZIP을 받지 못했어요. 서버에서 파일을 발급했을 수 있어요. 저장 목록을 확인한 뒤 새 내보내기를 요청해 주세요.",
    NATIVE_AUTH_UNAVAILABLE: "이 앱에서 내보내기 보호 화면을 열 수 없어요. 지원하는 앱 버전을 확인해 주세요.",
  };
  const fallback = error.status === 413 ? messages.EXPORT_TOO_LARGE : error.status === 408 ? messages.EXPORT_TIMEOUT : authErrorMessage(error);
  return <div className="auth-message" role="alert"><p>{messages[error.code] ?? fallback}</p>
    {(error.code === "REAUTHENTICATION_REQUIRED" || error.code === "STEP_UP_REQUIRED") && <Link to="/login">비밀번호로 다시 인증</Link>}
  </div>;
}
