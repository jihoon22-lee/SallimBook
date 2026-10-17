import { useEffect, useState } from "react";
import type { components } from "@sallimbook/api-client";
import { Link } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { nativeRequest } from "../../platform/nativeAuth";
import { AuthError } from "../auth/AuthFeedback";
import { useAuth } from "../auth/AuthProvider";

export type HouseholdMember = components["schemas"]["MemberResponse"];

export function FinanceError({ error }: { error: ApiError | null }) {
  if (!error) return null;
  const messages: Partial<Record<ApiError["code"], string>> = {
    NOT_FOUND: "항목을 찾을 수 없거나 볼 권한이 없어요. 현재 가계의 목록에서 다시 확인해 주세요.",
    VERSION_CONFLICT: "다른 곳에서 정보가 변경됐어요. 작성한 내용은 그대로 두었어요. 서버의 최신 내용을 확인해 주세요.",
    OWNER_UNAVAILABLE: "현재 가계의 구성원을 소유자로 선택해 주세요.",
    INVALID_ASSET: "소유 방식과 소유자, 시작일·종료일을 확인해 주세요.",
    FINANCIAL_ASSET_REQUIRED: "계좌와 연결할 금융 자산을 선택해 주세요.",
    ASSET_ALREADY_LINKED: "이미 다른 계좌와 연결된 자산이에요. 기존 계좌를 확인하거나 다른 금융 자산을 선택해 주세요.",
    ASSET_KIND_IN_USE: "월별 금액 기록이 있어 자산·부채 구분을 바꿀 수 없어요. 원래 구분을 유지하거나 새 항목을 등록해 주세요.",
    ASSET_UNAVAILABLE: "사용 종료된 자산은 새 계좌에 연결할 수 없어요. 금융 자산을 다시 불러와 사용 중인 항목을 선택해 주세요.",
    ASSET_IN_USE: "연결된 기록이 있어 삭제할 수 없어요. 사용 종료로 과거 기록을 보존해 주세요.",
    INVALID_ACCOUNT: "계좌 정보와 개설일·종료일을 확인해 주세요.",
    INVALID_ACCOUNT_DATES: "종료일은 연결된 계좌의 개설일 이후여야 해요. 개설일과 보유 종료일을 확인해 주세요.",
    FIELD_ENCRYPTION_UNAVAILABLE: "계좌번호 보호 설정을 확인하지 못했어요. 번호 저장과 열람은 잠시 사용할 수 없어요.",
    ACCOUNT_NUMBER_UNAVAILABLE: "계좌번호를 열 수 없어요. 잠시 후 다시 확인해 주세요.",
    ACCOUNT_NUMBER_NOT_SET: "등록된 계좌번호가 없어요.",
  };
  const message = messages[error.code];
  return message ? <div className="auth-message" role="alert"><p>{message}</p></div> : <AuthError error={error} />;
}

export function useHouseholdMembers() {
  const { domainApi } = useAuth();
  const [members, setMembers] = useState<HouseholdMember[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(null);
    void domainApi.read((client) => client.GET("/api/v1/household/members"), () => nativeRequest<HouseholdMember[]>({ method: "GET", path: "/api/v1/household/members" }))
      .then((items) => { if (active) setMembers(items); })
      .catch((failure) => { if (active) setError(toApiError(failure)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [domainApi, retry]);
  return { members, error, loading, retry: () => setRetry((value) => value + 1) };
}

export function MemberLoadError({ error, retry }: { error: ApiError | null; retry: () => void }) {
  return error && <><FinanceError error={error} /><button type="button" onClick={retry}>구성원 목록 다시 불러오기</button></>;
}

export function MissingAmount({ monthLink = false }: { monthLink?: boolean }) {
  return <div className="amount-unavailable"><p>월별 잔액·평가액은 별도로 확인해야 해요. 아직 금액을 조회하지 않았어요.</p>
    {monthLink && <Link to="/assets/compare">월간 자산 비교 안내</Link>}
  </div>;
}

export { isUuid, isDateOnly, todaySeoul, dateLabel } from "./dates";
