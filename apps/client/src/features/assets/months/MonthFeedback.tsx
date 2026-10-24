import { useId } from "react";
import type { ApiError } from "../../../platform/api";
import { FinanceError } from "../../finance/FinanceSupport";
import { readFailedMessage } from "../../auth/AuthFeedback";
import type { MonthRecord } from "./model";
import { formatKrw, monthStates } from "./model";
import { RecordActor } from "../../../shared/RecordActor";
export function MonthError({ error }: { error: ApiError | null }) {
  if (!error) return null;
  const messages: Partial<Record<ApiError["code"], string>> = {
    MONTH_NOT_FOUND: "이 달은 아직 작성본을 만들지 않았어요.",
    MONTH_ALREADY_EXISTS: "다른 곳에서 이미 작성본을 만들었어요. 현재 월 기록을 확인해 주세요.",
    PREVIOUS_MONTH_UNCONFIRMED:
      "전월 확정 기록이 없어 불러올 값이 없어요. 전월을 먼저 확정하거나 이번 달 값을 직접 입력해 주세요.",
    MONTH_IN_FUTURE:
      "아직 시작하지 않은 달은 기록할 수 없어요. 이번 달이나 지난 달을 선택해 주세요.",
    MONTH_CONFIRMED:
      "이미 확정된 월이에요. 최신 기록을 확인하고 필요하면 사유를 남겨 정정본을 열어 주세요.",
    MONTH_NOT_CONFIRMED: "확정한 월만 정정본으로 열 수 있어요. 현재 기록을 다시 확인해 주세요.",
    VERSION_CONFLICT:
      "다른 곳에서 기록이 변경됐어요. 작성한 내용은 유지했어요. 최신 내용을 비교한 뒤 다시 저장해 주세요.",
    REVISION_CONFLICT:
      "다른 정정본이 열렸거나 조회 도중 기록이 바뀌었어요. 작성한 내용은 유지했어요. 현재 월 기록과 비교해 주세요.",
    VALUE_CONFLICT:
      "자산 범위를 반영하면서 입력 행이 바뀌었어요. 작성한 내용은 유지했어요. 최신 행의 지분과 금액 기준을 비교해 주세요.",
    INVALID_AS_OF_DATE:
      "선택한 월 안에서 실제 확인한 날짜를 입력해 주세요. 미래 날짜는 사용할 수 없어요.",
    NO_CARRIED_VALUE:
      "현재 행에는 변동 없음을 확인할 불러온 금액이 없어요. 최신 값을 확인하고 직접 금액을 입력해 주세요.",
    MONTH_SCOPE_CHANGED:
      "현재 자산 목록이나 지분이 바뀌었어요. 자산 범위 반영 내용을 확인한 뒤 다시 확정해 주세요.",
    MONTH_UNVERIFIED: "합계에 포함된 미입력·미확인 항목을 모두 확인한 뒤 확정할 수 있어요.",
    AS_OF_DATE_ACK_REQUIRED:
      "월말과 다른 기준일이 있어요. 실제 확인 날짜를 검토하고 확인란을 선택해 주세요.",
    SCOPE_ACK_REQUIRED:
      "전월과 포함 항목 또는 가계 지분이 달라요. 최신 비교 범위를 확인하고 확인란을 선택해 주세요.",
    TOTAL_OUT_OF_RANGE: "합산 가능한 금액 범위를 넘었어요. 금액과 포함 항목을 확인해 주세요.",
    IDEMPOTENCY_CONFLICT:
      "이전 요청과 내용이 달라 저장하지 않았어요. 최신 기록을 확인한 뒤 변경 내용을 다시 검토해 주세요.",
    INVALID_IDEMPOTENCY_KEY: "요청 식별자를 확인하지 못했어요. 현재 기록을 다시 확인해 주세요.",
    OPERATION_IN_PROGRESS:
      "같은 요청이 처리 중이에요. 자동으로 다시 저장하지 않아요. 잠시 후 현재 기록을 확인해 주세요.",
    REQUEST_CANCELLED:
      "요청 대기를 중단했어요. 서버에 반영됐을 수 있으니 현재 기록을 확인해 주세요. 같은 내용으로 다시 요청하면 같은 식별자를 사용해요.",
    NETWORK_UNAVAILABLE:
      "서버의 처리 결과를 확인하지 못했어요. 자동으로 다시 저장하지 않아요. 현재 기록을 확인하거나 같은 요청을 다시 확인해 주세요.",
    REQUEST_FAILED:
      "요청 결과를 확인하지 못했어요. 자동으로 다시 저장하지 않아요. 현재 기록을 확인한 뒤 진행해 주세요.",
  };
  // The wording for a lost save would be wrong for a read that failed to load.
  const message =
    error.read && (error.code === "NETWORK_UNAVAILABLE" || error.code === "REQUEST_FAILED")
      ? readFailedMessage
      : messages[error.code];
  return message ? (
    <div className="auth-message" role="alert">
      <p>{message}</p>
    </div>
  ) : (
    <FinanceError error={error} />
  );
}
export function MonthSummary({ record }: { record: MonthRecord }) {
  const totals = record.totals;
  const titleId = useId();
  return (
    <section className="card month-summary" aria-labelledby={titleId}>
      <div className="item-heading">
        <h2 id={titleId}>이번 기록의 합계</h2>
        <span className="status-chip">
          {monthStates[record.state]} · {record.revision_no}차 기록
        </span>
      </div>
      <dl className="metadata-grid compact-metadata">
        <div>
          <dt>자산 합계</dt>
          <dd>{totals.assets_krw === null ? "미입력 항목 있음" : formatKrw(totals.assets_krw)}</dd>
        </div>
        <div>
          <dt>부채 합계</dt>
          <dd>
            {totals.liabilities_krw === null
              ? "미입력 항목 있음"
              : formatKrw(totals.liabilities_krw)}
          </dd>
        </div>
        <div>
          <dt>순자산</dt>
          <dd>
            {totals.net_assets_krw === null ? "합계 확인 필요" : formatKrw(totals.net_assets_krw)}
          </dd>
        </div>
        <div>
          <dt>확인한 포함 항목</dt>
          <dd>
            {totals.verified_count} / {totals.item_count}개
          </dd>
        </div>
      </dl>
      <p className="muted">
        미입력 {totals.missing_count}개 · 불러온 값 미확인 {totals.carried_count}개
      </p>
      {totals.provisional && (
        <p className="month-warning">
          임시 합계예요. 미입력 금액은 0원이 아니며, 불러온 값은 아직 확인하지 않았어요.
        </p>
      )}
      {!totals.provisional && record.state !== "confirmed" && (
        <p>포함 항목의 금액 확인을 마쳤어요. 월 확정 전 기준일과 비교 범위를 확인해 주세요.</p>
      )}
      {record.confirmed_at && (
        <p>
          <RecordActor
            memberId={record.confirmed_by_member_id}
            at={record.confirmed_at}
            label="월 확정"
          />
        </p>
      )}
      {record.reopened_reason && <p>정정 사유: {record.reopened_reason}</p>}
    </section>
  );
}
