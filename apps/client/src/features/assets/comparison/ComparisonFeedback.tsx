import { Link } from "react-router";
import type { ApiError } from "../../../platform/api";
import { formatMonth } from "../../../shared/MonthContext";
import { FinanceError } from "../../finance/FinanceSupport";
import { formatKrw, monthStates } from "../months/model";
import { deltaSign, percentLabel, signedKrw } from "./model";
import type { Comparison } from "./model";
/** Colors a net-asset change by its sign; the +/- text still carries the meaning. */
export function DeltaText({ value, text }: { value: string | null; text: string }) {
  return (
    <span className="money-delta" data-sign={deltaSign(value)}>
      {text}
    </span>
  );
}
export function ComparisonError({ error }: { error: ApiError | null }) {
  if (!error) return null;
  const messages: Partial<Record<ApiError["code"], string>> = {
    INVALID_COMPARISON_RANGE: "비교할 이전 월은 확인할 월보다 앞서야 해요.",
    INVALID_TREND_RANGE: "시작·종료 월과 최대 120개월 범위를 확인해 주세요.",
    INVALID_COMPARISON_FILTERS: "공동 소유와 개인 소유자 필터를 함께 사용할 수 없어요.",
    REVISION_CONFLICT:
      "조회 도중 월 기록이 변경됐어요. 서로 다른 기록을 합치지 않았어요. 최신 내용을 다시 불러와 주세요.",
    TOTAL_OUT_OF_RANGE: "비교 가능한 금액 범위를 넘었어요. 월 기록과 포함 항목을 확인해 주세요.",
  };
  return messages[error.code] ? (
    <div className="auth-message" role="alert">
      <p>{messages[error.code]}</p>
    </div>
  ) : (
    <FinanceError error={error} />
  );
}
export function ComparisonStatus({ data }: { data: Comparison }) {
  if (data.state === "available") return null;
  return (
    <div className="month-warning" role="status">
      {data.state === "current_missing" ? (
        <p>확인할 월의 기록이 없어요. 자산이 0원으로 줄어든 것으로 계산하지 않아요.</p>
      ) : data.state === "no_previous_month" ? (
        <p>
          이전 비교월의 기록이 없어 비교할 수 없어요. 첫 기록을 0원 대비 증가로 표시하지 않아요.
        </p>
      ) : (
        <p>작성 중이거나 정정 중인 월이 있어요. 두 월을 확정하기 전에는 증감을 계산하지 않아요.</p>
      )}
      <Link to={`/assets/months/${data.to_month}`}>확인 월 기록 열기</Link>
      {data.from_month && (
        <span>
          {" "}
          · <Link to={`/assets/months/${data.from_month}`}>이전 비교월 기록 열기</Link>
        </span>
      )}
    </div>
  );
}
export function ComparisonNumbers({ data }: { data: Comparison }) {
  const current = data.current.totals;
  const previous = data.previous?.totals;
  return (
    <>
      <dl className="metadata-grid comparison-numbers">
        <div>
          <dt>확인 월 순자산</dt>
          <dd>
            {!current
              ? "월 기록 없음"
              : current.net_assets_krw === null
                ? "금액 확인 필요"
                : formatKrw(current.net_assets_krw)}
          </dd>
        </div>
        <div>
          <dt>이전 비교월 순자산</dt>
          <dd>
            {!previous
              ? "월 기록 없음"
              : previous.net_assets_krw === null
                ? "금액 확인 필요"
                : formatKrw(previous.net_assets_krw)}
          </dd>
        </div>
        <div>
          <dt>전체 순자산 변화</dt>
          <dd>
            <DeltaText
              value={data.total_delta_krw}
              text={
                data.total_delta_krw === null ? "비교할 수 없음" : signedKrw(data.total_delta_krw)
              }
            />
          </dd>
        </div>
        <div>
          <dt>동일 범위 변화</dt>
          <dd>
            <DeltaText
              value={data.common_scope_delta_krw}
              text={
                data.common_scope_delta_krw === null
                  ? "비교할 수 없음"
                  : signedKrw(data.common_scope_delta_krw)
              }
            />
          </dd>
        </div>
        <div>
          <dt>순자산 증감률</dt>
          <dd>
            <DeltaText value={data.change_percent} text={percentLabel(data.change_percent)} />
          </dd>
        </div>
      </dl>
      <ComparisonNotes data={data} />
    </>
  );
}
export function ComparisonNotes({ data }: { data: Comparison }) {
  const percentReason =
    data.change_percent_unavailable_reason === "zero_previous_total"
      ? "이전 순자산이 0원이어서 증감률을 계산하지 않아요."
      : data.change_percent_unavailable_reason === "negative_previous_total"
        ? "이전 순자산이 음수여서 증감률을 계산하지 않아요. 원 단위 변화를 확인해 주세요."
        : "두 월의 확정 기록이 필요해요.";
  return (
    <>
      {data.change_percent === null && <p className="muted">{percentReason}</p>}
      {data.state === "unconfirmed" && (
        <p className="muted">
          위에 보이는 월 금액은 현재 작성본의 참고 합계예요. 미확인 금액을 포함할 수 있어요.
        </p>
      )}
      <p className="muted">
        동일 범위는 양쪽 월에 포함되고 가계 지분이 같은 항목이에요. 자산 변화는 수입·지출을 모두
        반영한 저축액이나 투자 수익률이 아니에요.
      </p>
    </>
  );
}
export function ScopeWarning({ data }: { data: Comparison }) {
  return data.scope_changed ? (
    <div className="month-warning">
      <p>비교 대상 또는 가계 지분이 달라요. 전체 변화와 동일 범위 변화를 구분해 주세요.</p>
      <p>
        추가 {data.added_asset_ids.length}개 · 제외 {data.removed_asset_ids.length}개 · 지분 변경{" "}
        {data.changed_share_asset_ids.length}개
      </p>
    </div>
  ) : null;
}
export function ComparisonDates({ data }: { data: Comparison }) {
  const periods = [data.previous, data.current].filter((period) => period !== null);
  const warnings = periods.filter(
    (period) =>
      period.dates.mixed_dates ||
      period.dates.non_month_end_asset_ids.length > 0 ||
      period.dates.missing_date_asset_ids.length > 0,
  );
  return (
    warnings.length > 0 && (
      <section className="date-warning">
        <h3>기준일 확인</h3>
        <ul>
          {warnings.map((period) => (
            <li key={period.month}>
              {formatMonth(period.month)}:{" "}
              {period.dates.mixed_dates ? "서로 다른 기준일이 섞여 있어요. " : ""}월말이 아닌 항목{" "}
              {period.dates.non_month_end_asset_ids.length}개 · 기준일 미입력{" "}
              {period.dates.missing_date_asset_ids.length}개
            </li>
          ))}
        </ul>
        <p className="muted">월중에 확인한 금액을 월말 잔액으로 바꾸어 해석하지 않아요.</p>
      </section>
    )
  );
}
export function PeriodLabels({ data }: { data: Comparison }) {
  return (
    <p className="muted">
      {data.from_month ? formatMonth(data.from_month) : "이전 월 없음"} (
      {data.previous?.state && data.previous.state !== "missing"
        ? monthStates[data.previous.state]
        : "기록 없음"}
      ) → {formatMonth(data.to_month)} (
      {data.current.state === "missing" ? "기록 없음" : monthStates[data.current.state]})
    </p>
  );
}
