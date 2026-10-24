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
    PERSON_UNAVAILABLE:
      "보관된 가족은 새 기록에 지정할 수 없어요. 가족 관리에서 다시 사용으로 바꿔 주세요.",
    PEOPLE_CLIENT_REQUIRED: "가족 정보를 바꾸려면 앱을 업데이트하거나 웹을 새로 열어 주세요.",
    MEMBER_PERSON_MANAGED: "로그인 구성원 정보는 계정 설정에서 바꿔 주세요.",
    PAYMENT_LINK_CONFIRMATION_REQUIRED: "선택한 종료일 이후의 연결된 납부 계획을 확인해 주세요.",
    PAYMENT_LINKS_CHANGED:
      "연결된 계획이 변경됐어요. 입력한 종료일은 유지했어요. 종료 영향을 다시 확인해 주세요.",
    NOT_FOUND: "항목을 찾을 수 없거나 볼 권한이 없어요. 현재 가계의 목록에서 다시 확인해 주세요.",
    VERSION_CONFLICT:
      "다른 곳에서 정보가 변경됐어요. 작성한 내용은 그대로 두었어요. 서버의 최신 내용을 확인해 주세요.",
    OWNER_UNAVAILABLE: "현재 가계의 구성원을 소유자로 선택해 주세요.",
    INVALID_ASSET: "소유 방식과 소유자, 시작일·종료일을 확인해 주세요.",
    INSURANCE_CASE_IN_USE:
      "변경 이력·진료·비용·청구·지급·첨부가 있는 사건은 삭제할 수 없어요. 사건 상태를 변경해 과거 기록을 보존해 주세요.",
    INSURANCE_POLICY_IN_USE:
      "변경 이력·보장·보험료·청구·지급·첨부·평가액 연결이 있는 계약은 삭제할 수 없어요. 계약 상태를 변경해 과거 기록을 보존해 주세요.",
    ACCOUNT_IN_USE:
      "카드·수입·납부 규칙·월 기록 같은 다른 기록에 연결된 계좌는 삭제할 수 없어요. 계좌 사용 종료로 과거 기록을 보존해 주세요.",
    RULE_IN_USE:
      "보험료로 연결됐거나 납부 기록·처리 이력이 있거나 확정한 월에 걸린 규칙은 삭제할 수 없어요. 규칙 종료로 과거 기록을 보존해 주세요.",
    ASSET_END_IN_FUTURE:
      "보유 종료일은 서울 기준 오늘보다 늦을 수 없어요. 실제로 보유를 끝낸 날짜를 입력해 주세요.",
    FINANCIAL_ASSET_REQUIRED: "계좌와 연결할 금융 자산을 선택해 주세요.",
    ASSET_ALREADY_LINKED:
      "이미 다른 계좌와 연결된 자산이에요. 기존 계좌를 확인하거나 다른 금융 자산을 선택해 주세요.",
    ASSET_KIND_IN_USE:
      "월별 금액 기록이 있어 자산·부채 구분을 바꿀 수 없어요. 원래 구분을 유지하거나 새 항목을 등록해 주세요.",
    ASSET_UNAVAILABLE:
      "사용 종료된 자산은 새 계좌에 연결할 수 없어요. 금융 자산을 다시 불러와 사용 중인 항목을 선택해 주세요.",
    ASSET_IN_USE: "연결된 기록이 있어 삭제할 수 없어요. 사용 종료로 과거 기록을 보존해 주세요.",
    INVALID_ACCOUNT: "계좌 정보와 개설일·종료일을 확인해 주세요.",
    INVALID_ACCOUNT_DATES:
      "종료일은 연결된 계좌의 개설일 이후여야 해요. 개설일과 보유 종료일을 확인해 주세요.",
    FIELD_ENCRYPTION_UNAVAILABLE:
      "계좌번호 보호 설정을 확인하지 못했어요. 번호 저장과 열람은 잠시 사용할 수 없어요.",
    ACCOUNT_NUMBER_UNAVAILABLE: "계좌번호를 열 수 없어요. 잠시 후 다시 확인해 주세요.",
    ACCOUNT_NUMBER_NOT_SET: "등록된 계좌번호가 없어요.",
  };
  const message = messages[error.code];
  return message ? (
    <div className="auth-message" role="alert">
      <p>{message}</p>
    </div>
  ) : (
    <AuthError error={error} />
  );
}

export function useHouseholdMembers(enabled = true) {
  const { domainApi, state } = useAuth();
  const memberKey = state.status === "authenticated" ? state.member.member_id : null;
  const [members, setMembers] = useState<HouseholdMember[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!enabled) {
      setMembers([]);
      setError(null);
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    void domainApi
      .read(
        (client) => client.GET("/api/v1/household/members"),
        () =>
          nativeRequest<HouseholdMember[]>({ method: "GET", path: "/api/v1/household/members" }),
      )
      .then((items) => {
        if (active) setMembers(items);
      })
      .catch((failure) => {
        if (active) setError(toApiError(failure));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [domainApi, retry, enabled, memberKey]);
  return { members, error, loading, retry: () => setRetry((value) => value + 1) };
}

export function MemberLoadError({ error, retry }: { error: ApiError | null; retry: () => void }) {
  return (
    error && (
      <>
        <FinanceError error={error} />
        <button type="button" onClick={retry}>
          구성원 목록 다시 불러오기
        </button>
      </>
    )
  );
}

export function MissingAmount({ monthLink = false }: { monthLink?: boolean }) {
  return (
    <div className="amount-unavailable">
      <p>월별 잔액·평가액은 별도로 확인해야 해요. 아직 금액을 조회하지 않았어요.</p>
      {monthLink && <Link to="/assets/compare">월간 자산 비교 안내</Link>}
    </div>
  );
}

export { isUuid, isDateOnly, todaySeoul, dateLabel } from "./dates";
