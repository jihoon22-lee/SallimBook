import { Link } from "react-router";
import { formatKrw } from "../assets/months/model";
import { FinanceError } from "../finance/FinanceSupport";
import { economicTypes } from "../fixed/model";
import { BarSeries, ShareBar, type Bar } from "../../shared/Charts";
import { formatKrwShort } from "../../shared/krwShort";
import { formatMonth } from "../../shared/month";
import type { HouseholdTrends, OverviewResource } from "./overviewApi";

const tick = (month: string) => String(Number(month.slice(5)));

/** One bar per month of the plan-based estimate; a month without a known income has no bar. */
export function monthlyMarginBars(plan: HouseholdTrends["plan"]): Bar[] {
  return plan.map((point, index) => ({
    key: point.month,
    tick:
      index === 0 || point.month.endsWith("-01")
        ? point.month.slice(2).replace("-", ".")
        : tick(point.month),
    label: formatMonth(point.month),
    value: point.margin_after_transfers_krw,
  }));
}

/** The server's plan-based estimate; it is never shown as a balance or an amount saved. */
export function PlanMargin({
  overview,
  quiet,
  trend,
}: {
  overview: OverviewResource;
  quiet: boolean;
  /** Month-by-month estimates for the small bars; the panel works without them. */
  trend?: HouseholdTrends["plan"] | null;
}) {
  // A failed refresh keeps the estimate already shown; the holdings section offers the retry.
  const plan = overview.data?.plan;
  // Without one known expected income the margin would read as a deficit, so it waits for one.
  const ready = plan && plan.expected_income_count > plan.expected_income_unknown_count;
  const notes = plan
    ? [
        plan.expected_income_unknown_count > 0 &&
          `금액 미확인 예상 수입 ${plan.expected_income_unknown_count}건`,
        plan.planned_unknown_count > 0 && `금액 미정 계획 ${plan.planned_unknown_count}개`,
        plan.unconverted_count > 0 && `월 환산 미정 ${plan.unconverted_count}개`,
        plan.excluded_known_krw !== "0" && `별도 표시 ${formatKrw(plan.excluded_known_krw)} 제외`,
      ].filter(Boolean)
    : [];
  const short = plan && ready && BigInt(plan.margin_after_transfers_krw) < 0n;
  return (
    <section className="plan-margin" aria-label="계획상 남는 돈">
      {overview.loading && !plan && <p role="status">계획상 남는 돈 확인 중</p>}
      {overview.error && !plan && !quiet && (
        <>
          <FinanceError error={overview.error} />
          <button type="button" onClick={() => void overview.reload()}>
            계획상 남는 돈 다시 확인
          </button>
        </>
      )}
      {plan && !ready && (
        <p>
          예상 수입 금액을 등록하면 계획상 남는 돈을 볼 수 있어요.{" "}
          <Link to="/income/planning">예상 수입 등록</Link>
        </p>
      )}
      {plan && ready && (
        <>
          <div className="flow-head">
            <div>
              <p className="flow-label">계획상 남는 돈</p>
              <p className="flow-figure" title={formatKrw(plan.margin_after_transfers_krw)}>
                {formatKrwShort(plan.margin_after_transfers_krw)}
              </p>
            </div>
            <p className="flow-income">
              예상 수입
              <br />
              <strong>{formatKrw(plan.expected_income_known_krw)}</strong>
            </p>
          </div>
          <ShareBar
            label="예상 수입의 쓰임"
            amount={formatKrw}
            segments={[
              { name: economicTypes.expense, value: plan.spending_known_krw, tone: "spend" },
              { name: economicTypes.loan, value: plan.loan_known_krw, tone: "loan" },
              { name: economicTypes.asset_transfer, value: plan.transfer_known_krw, tone: "save" },
              {
                name: short ? "모자라는 돈" : "남는 돈",
                value: short
                  ? (-BigInt(plan.margin_after_transfers_krw)).toString()
                  : plan.margin_after_transfers_krw,
                tone: short ? "short" : "left",
              },
            ]}
          />
          <p className="muted flow-note">
            연금·저축을 넣기 전에는 {formatKrw(plan.margin_before_transfers_krw)}이에요.
            {notes.length > 0 && ` ${notes.join(" · ")}`}
          </p>
        </>
      )}
      {trend && trend.some((point) => point.margin_after_transfers_krw !== null) && (
        <>
          <p className="flow-subtitle">
            <span>월별 남는 돈</span>
            <Link to="/living/monthly">월별로 보기</Link>
          </p>
          <BarSeries title="월별 계획상 남는 돈" bars={monthlyMarginBars(trend)} />
        </>
      )}
      <p className="muted flow-note">
        등록한 예상 수입과 월 계획으로 계산한 값이에요. 실제 잔액·저축액이 아니에요.
      </p>
    </section>
  );
}
