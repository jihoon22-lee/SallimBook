import { Link } from "react-router";
import { formatKrw } from "../assets/months/model";
import { FinanceError } from "../finance/FinanceSupport";
import { economicTypes } from "../fixed/model";
import type { OverviewResource } from "./overviewApi";

/** The server's plan-based estimate; it is never shown as a balance or an amount saved. */
export function PlanMargin({ overview, quiet }: { overview: OverviewResource; quiet: boolean }) {
  const plan = overview.error ? null : overview.data?.plan;
  // Without one known expected income the margin would read as a deficit, so it waits for one.
  const ready = plan && plan.expected_income_count > plan.expected_income_unknown_count;
  const notes = plan
    ? [
        plan.expected_income_unknown_count > 0 &&
          `금액 미확인 예상 수입 ${plan.expected_income_unknown_count}건`,
        plan.planned_unknown_count > 0 && `금액 미정 계획 ${plan.planned_unknown_count}개`,
        plan.unconverted_count > 0 && `월 환산 미정 ${plan.unconverted_count}개`,
      ].filter(Boolean)
    : [];
  return (
    <section className="plan-margin" aria-label="월 계획 기준 여유">
      <h3>월 계획 기준 여유</h3>
      {overview.loading && !plan && <p role="status">계획 기준 여유 확인 중</p>}
      {overview.error && !quiet && (
        <>
          <FinanceError error={overview.error} />
          <button type="button" onClick={() => void overview.reload()}>
            계획 기준 여유 다시 확인
          </button>
        </>
      )}
      {plan && !ready && (
        <p>
          예상 수입 금액을 등록하면 월 계획 기준 여유를 볼 수 있어요.{" "}
          <Link to="/income/planning">예상 수입 등록</Link>
        </p>
      )}
      {plan && ready && (
        <>
          <dl className="metric-strip">
            <div className="metric-primary">
              <dt>연금·저축 이동 전</dt>
              <dd>{formatKrw(plan.margin_before_transfers_krw)}</dd>
            </div>
            <div>
              <dt>이동 후</dt>
              <dd>{formatKrw(plan.margin_after_transfers_krw)}</dd>
            </div>
          </dl>
          <p className="plan-margin-terms">
            확인된 예상 수입 {formatKrw(plan.expected_income_known_krw)} − {economicTypes.expense}{" "}
            {formatKrw(plan.spending_known_krw)} − {economicTypes.loan}{" "}
            {formatKrw(plan.loan_known_krw)} · {economicTypes.asset_transfer}{" "}
            {formatKrw(plan.transfer_known_krw)}
          </p>
          {notes.length > 0 && <p className="muted">{notes.join(" · ")}</p>}
        </>
      )}
      <p className="muted">등록한 예상 수입과 월 계획 기준이에요. 실제 잔액·저축액이 아니에요.</p>
    </section>
  );
}
