import type { components } from "@sallimbook/api-client";
import { useCallback } from "react";
import { useResource } from "../finance/queries";
import { CashflowError } from "../finance/FinancialFeedback";
import { formatKrw } from "../assets/months/model";
import { useExpensePlanApi } from "./expensePlanApi";
export function ExpensePlanSummary({
  data,
}: {
  data: components["schemas"]["PlanSummaryResponse"];
}) {
  return (
    <section aria-label="현재 월 지출 계획">
      <h3>현재 월 지출 계획</h3>
      <dl className="metadata-grid compact-metadata">
        <div>
          <dt>고정 지출 계획</dt>
          <dd>{formatKrw(data.fixed_known_krw)}</dd>
        </div>
        <div>
          <dt>변동 예산</dt>
          <dd>{formatKrw(data.budget_known_krw)}</dd>
        </div>
        <div>
          <dt>월 계획 합계</dt>
          <dd>{formatKrw(data.combined_known_krw)}</dd>
        </div>
        <div>
          <dt>지원·급여 관련 등 별도 표시</dt>
          <dd>{formatKrw(data.excluded_known_krw)}</dd>
        </div>
      </dl>
      <p className="muted">
        등록 {data.plan_count}개 · 합계 포함 금액 미정 {data.included_unknown_count}개 · 별도 표시
        금액 미정 {data.excluded_unknown_count}개
        {data.unconverted_count > 0 ? ` · 월 환산 미정 ${data.unconverted_count}개` : ""}
      </p>
    </section>
  );
}
export function CurrentExpensePlanSummary() {
  const api = useExpensePlanApi();
  const result = useResource(useCallback(() => api.summary(), [api]));
  return (
    <>
      <CashflowError error={result.error} />
      {result.loading && <p role="status">월 계획 확인 중</p>}
      {result.error && <button onClick={() => void result.reload()}>월 계획 다시 불러오기</button>}
      {result.data && !result.error && !result.loading && <ExpensePlanSummary data={result.data} />}
    </>
  );
}
