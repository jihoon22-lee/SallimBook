import type { components } from "@sallimbook/api-client";
import { useCallback } from "react";
import { useResource } from "../finance/queries";
import { CashflowError } from "../finance/FinancialFeedback";
import { formatKrw } from "../assets/months/model";
import { useRetryReport } from "../../shared/RetryFailed";
import { useExpensePlanApi } from "./expensePlanApi";
import { economicTypes } from "./model";

type Summary = components["schemas"]["PlanSummaryResponse"];
type Subtotal = components["schemas"]["PlanSubtotal"];

function subtotalText(row: Subtotal | undefined) {
  if (!row) return formatKrw("0");
  const unknown = row.unknown_count ? ` · 미정 ${row.unknown_count}개` : "";
  return `${formatKrw(row.known_krw)}${unknown}`;
}

export function ExpensePlanSummary({
  data,
  compact = false,
}: {
  data: Summary;
  compact?: boolean;
}) {
  const byType = new Map(data.economic_types.map((row) => [row.key, row]));
  return (
    <section className="expense-plan-summary" aria-label="현재 월 지출 계획">
      <h3>현재 월 지출 계획</h3>
      {/* Loan payments and savings transfers stay apart from spending, never folded into it. */}
      {data.economic_types.length > 0 && (
        <dl className="metadata-grid compact-metadata plan-split">
          {(Object.keys(economicTypes) as (keyof typeof economicTypes)[]).map((key) => (
            <div key={key} data-economic={key}>
              <dt>{economicTypes[key]}</dt>
              <dd>{subtotalText(byType.get(key))}</dd>
            </div>
          ))}
        </dl>
      )}
      <p className="plan-total">
        월 계획 합계 <strong>{formatKrw(data.combined_known_krw)}</strong>
        <span className="muted">
          {" "}
          (고정 {formatKrw(data.fixed_known_krw)} · 변동 예산 {formatKrw(data.budget_known_krw)})
        </span>
      </p>
      <p className="muted">
        지원·급여 관련 등 별도 표시 {formatKrw(data.excluded_known_krw)} · 등록 {data.plan_count}개
        {data.included_unknown_count > 0
          ? ` · 합계 포함 금액 미정 ${data.included_unknown_count}개`
          : ""}
        {data.excluded_unknown_count > 0
          ? ` · 별도 표시 금액 미정 ${data.excluded_unknown_count}개`
          : ""}
        {data.unconverted_count > 0 ? ` · 월 환산 미정 ${data.unconverted_count}개` : ""}
      </p>
      {!compact && data.categories.length > 0 && (
        <details className="plan-categories">
          <summary>분류별 소계 {data.categories.length}개</summary>
          <ul>
            {data.categories.map((row) => (
              <li key={row.key}>
                <span>
                  {row.key} <small>{row.count}개</small>
                </span>
                <strong>{subtotalText(row)}</strong>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

export function CurrentExpensePlanSummary({ compact = false }: { compact?: boolean }) {
  const api = useExpensePlanApi();
  const result = useResource(useCallback(() => api.summary(), [api]));
  const quiet = useRetryReport("expense-plan-summary", result.error, result.reload);
  return (
    <>
      {!quiet && <CashflowError error={result.error} />}
      {result.loading && <p role="status">월 계획 확인 중</p>}
      {result.error && !quiet && (
        <button onClick={() => void result.reload()}>월 계획 다시 불러오기</button>
      )}
      {result.data && !result.error && !result.loading && (
        <ExpensePlanSummary data={result.data} compact={compact} />
      )}
    </>
  );
}
