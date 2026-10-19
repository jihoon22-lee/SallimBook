import type { ReactNode } from "react";
import { Link } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import { SessionStatus } from "../auth/AuthFeedback";
import { MonthError } from "../assets/months/MonthFeedback";
import type { ApiError } from "../../platform/api";

export function AuthenticatedFinance({
  title,
  children,
  description,
  navigation,
}: {
  title: string;
  description: string;
  children: ReactNode;
  navigation?: ReactNode;
}) {
  const { state } = useAuth();
  return (
    <>
      <div className="intro">
        <p className="eyebrow">함께 기록하는 생활비</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {navigation}
      {state.status === "authenticated" ? children : <SessionStatus />}
    </>
  );
}
export function CashflowError({ error }: { error: ApiError | null }) {
  if (!error) return null;
  const messages: Partial<Record<ApiError["code"], string>> = {
    LOAN_UNAVAILABLE: "사용 중인 부채 항목을 선택해 주세요.",
    CARD_UNAVAILABLE: "사용 중인 납부 카드를 선택해 주세요.",
    RULE_PERIOD_OVERLAP:
      "기존 마지막 적용일 뒤이면서 종료 적용일 전인 날짜를 선택해 주세요. 종료일을 연장하거나 지난 규칙을 덮어쓰지 않아요.",
    PAST_RULE_CHANGE: "지난 적용기간은 덮어쓸 수 없어요. 오늘 이후의 새 적용일을 선택해 주세요.",
    GENERATION_TOO_LARGE: "규칙 하나를 지정하거나 생성 기간을 줄여 주세요.",
    OBLIGATION_SUPERSEDED: "다른 규칙으로 대체된 회차예요. 현재 적용 중인 회차를 확인해 주세요.",
    OBLIGATION_HAS_PAYMENT:
      "실제 납부나 수동 처리 이력이 있어 예정일 변경·건너뛰기를 할 수 없어요. 현재 납부를 확인해 주세요.",
    INVALID_OBLIGATION_STATE:
      "현재 회차 상태에서는 이 작업을 할 수 없어요. 최신 내용을 확인해 주세요.",
    ACTUAL_PAYMENT_REQUIRED: "실제 납부를 먼저 기록한 뒤 수동 완료할 수 있어요.",
    OBLIGATION_CLOSED:
      "건너뛰거나 수동 완료한 회차에는 추가 납부할 수 없어요. 먼저 회차를 재개해 주세요.",
    INVALID_PAYMENT_SPLIT: "실제 납부액과 원금·이자 합계가 같아야 해요.",
    INCOME_DUPLICATE_SUSPECTED:
      "같은 월·구성원·종류의 월합계와 일별 기록이 함께 있어요. 기존 기록을 확인하고 중복 여부를 검토해 주세요.",
    INCOME_HAS_RETURNS:
      "활성 반환 기록이 있어 원본을 정정하거나 무효로 바꿀 수 없어요. 반환 기록을 먼저 확인해 주세요.",
    RETURN_EXCEEDS_ORIGINAL:
      "이미 기록한 반환을 포함하면 원본 수입보다 커져요. 현재 원본과 반환 내역을 다시 확인해 주세요.",
    SOURCE_DOMAIN_REQUIRED: "이 기록은 연결된 원본 영역에서 관리해 주세요.",
    INCOME_VOID: "이미 무효 처리된 기록이에요. 현재 기록을 확인해 주세요.",
    CONVERSION_TOTAL_MISMATCH: "전환 전후의 합계가 같아야 해요. 원 단위 금액을 확인해 주세요.",
    INCOMPLETE_CONVERSION:
      "같은 범위의 수입이 변경됐어요. 원본 전체를 다시 불러와 전환 내용을 검토해 주세요.",
    INVALID_CONVERSION: "같은 월·구성원·종류의 모든 활성 수입을 반대 날짜 정밀도로 전환해 주세요.",
    ACCOUNT_UNAVAILABLE:
      "사용 중인 계좌를 선택해 주세요. 종료된 계좌에는 새 기록을 연결할 수 없어요.",
    MEMBER_UNAVAILABLE: "현재 가계의 구성원을 선택해 주세요.",
    INVALID_OCCURRED_DATE: "실제 발생일은 서울 기준 오늘을 넘을 수 없어요.",
    INVALID_INCOME: "수입 종류·구성원·날짜 정밀도와 금액을 확인해 주세요.",
    INVALID_REVERSAL: "반환할 원본 수입과 금액을 확인해 주세요.",
    CARD_IN_USE:
      "연결된 기록이 있는 카드는 삭제할 수 없어요. 사용 종료로 과거 기록을 보존해 주세요.",
    PAYMENT_LINK_CONFIRMATION_REQUIRED: "선택한 종료일 이후의 연결된 납부 계획을 확인해 주세요.",
    PAYMENT_LINKS_CHANGED:
      "연결된 계획이 변경됐어요. 입력한 종료일은 유지했어요. 종료 영향을 다시 확인해 주세요.",
    INVALID_CARD: "카드의 일반정보와 결제계좌를 확인해 주세요.",
    INVALID_CARD_DATES:
      "카드 사용 종료일은 사용 시작일과 같거나 늦어야 하며, 서울 기준 오늘을 넘을 수 없어요.",
  };
  return messages[error.code] ? (
    <div className="auth-message" role="alert">
      <p>{messages[error.code]}</p>
    </div>
  ) : (
    <MonthError error={error} />
  );
}
export function SaveControls({
  busy,
  cancel,
  label,
  disabled = false,
  backTo,
  onDismiss,
}: {
  busy: boolean;
  cancel: () => void;
  label: string;
  disabled?: boolean;
  backTo?: string;
  onDismiss?: () => void;
}) {
  return (
    <div className="form-actions save-actions">
      <button type="submit" disabled={busy || disabled}>
        {busy ? "결과 확인 중…" : label}
      </button>
      {busy ? (
        <button type="button" className="secondary-button" onClick={cancel}>
          요청 대기 중단
        </button>
      ) : onDismiss ? (
        <button type="button" className="secondary-button" onClick={onDismiss}>
          입력 취소
        </button>
      ) : backTo ? (
        <Link className="button-link secondary-button" to={backTo}>
          입력 취소
        </Link>
      ) : null}
    </div>
  );
}
export function RecordedMoneyNotice() {
  return (
    <p className="muted">
      직접 등록한 금전 기록이에요. 계좌 잔액과 월별 자산 평가액은 자동으로 바뀌지 않아요.
    </p>
  );
}
