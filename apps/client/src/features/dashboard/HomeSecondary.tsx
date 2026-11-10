import { CurrentExpensePlanSummary } from "../fixed/ExpensePlanSummary";
import { ExpectedIncomeSummary } from "../income/ExpectedIncomeSummary";
import { useHouseholdMembers } from "../finance/FinanceSupport";
import { useCallback, useState } from "react";
import { Link } from "react-router";
import { formatMonth, useMonth } from "../../shared/MonthContext";
import { RelatedLinks } from "../../shared/RelatedLinks";
import { useAuth } from "../auth/AuthProvider";
import { formatKrw } from "../assets/months/model";
import { CashflowError } from "../finance/FinancialFeedback";
import { useResource } from "../finance/queries";
import { useFixedApi } from "../fixed/api";
import { useIncomeApi } from "../income/api";
import { useRetryReport } from "../../shared/RetryFailed";
import { StaleNotice } from "../../shared/StaleNotice";
import { PlanMargin } from "./PlanMargin";
import type { HouseholdTrends, OverviewResource } from "./overviewApi";

function IncomeSummary() {
  const api = useIncomeApi();
  const members = useHouseholdMembers();
  const { month } = useMonth();
  const result = useResource(useCallback(() => api.summary(month), [api, month]));
  const quiet = useRetryReport("home-income", result.error, result.reload);
  // Records already loaded stay visible while a refresh runs or after it fails.
  const ready = result.data !== null;
  return (
    <section className="home-summary-part" aria-label="홈 등록 수입 요약">
      {ready && (
        <ExpectedIncomeSummary data={result.data!.expected} members={members.members} level={3} />
      )}
      <h3>{formatMonth(month)} 실제 입금</h3>
      {!quiet && !ready && <CashflowError error={result.error} />}
      {result.loading && !ready && <p role="status">등록 수입 확인 중</p>}
      {result.error && !quiet && !ready && (
        <button onClick={() => void result.reload()}>홈 수입 다시 확인</button>
      )}
      {result.error && !quiet && ready && <StaleNotice retry={() => void result.reload()} />}
      {ready &&
        (result.data!.totals.record_count === 0 ? (
          <p>
            이 달에 귀속된 실제 수입 기록은 아직 없어요. <Link to="/income/new">수입 입력</Link>
          </p>
        ) : (
          <dl className="metadata-grid compact-metadata">
            <div>
              <dt>근로·부수입 순액</dt>
              <dd>{formatKrw(result.data!.totals.earned_net_krw)}</dd>
            </div>
            <div>
              <dt>보험금 순유입</dt>
              <dd>{formatKrw(result.data!.totals.insurance_net_krw)}</dd>
            </div>
          </dl>
        ))}
      <Link to="/income">수입 내역 보기</Link>
    </section>
  );
}
/** Scheduled and actual payments load only when opened; the plan above is the everyday view. */
function PaymentFacts() {
  const api = useFixedApi();
  const { month } = useMonth();
  const result = useResource(useCallback(() => api.summary(month), [api, month]));
  const ready = result.data !== null;
  return (
    <>
      {!ready && <CashflowError error={result.error} />}
      {result.loading && !ready && <p role="status">고정 납부 확인 중</p>}
      {result.error && !ready && (
        <button onClick={() => void result.reload()}>홈 고정 납부 다시 확인</button>
      )}
      {result.error && ready && <StaleNotice retry={() => void result.reload()} />}
      {ready && (
        <>
          <dl className="metadata-grid compact-metadata">
            <div>
              <dt>금액이 정해진 예정</dt>
              <dd>
                {result.data!.obligation_count
                  ? formatKrw(result.data!.expected_known_krw)
                  : "예정 회차 없음"}
              </dd>
            </div>
            <div>
              <dt>실제 납부</dt>
              <dd>{formatKrw(result.data!.actual_amount_krw)}</dd>
            </div>
          </dl>
          <p className="muted">
            예정액 미정 {result.data!.unknown_expected_count}회차 · 예정{" "}
            {result.data!.obligation_count}회차
          </p>
        </>
      )}
    </>
  );
}
function FixedSummary() {
  const { month } = useMonth();
  const [open, setOpen] = useState(false);
  return (
    <section className="home-summary-part" aria-label="홈 고정 납부 요약">
      <CurrentExpensePlanSummary />
      <details onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary>{formatMonth(month)} 예정·실제 납부</summary>
        {open && <PaymentFacts />}
      </details>
      <Link to="/fixed-payments">월 지출 계획 보기</Link>
    </section>
  );
}
export function HomeSecondary({
  overview,
  overviewQuiet = false,
  trend,
}: {
  /** The household status read shared with the rest of the page, for the plan-based margin. */
  overview?: OverviewResource;
  overviewQuiet?: boolean;
  trend?: HouseholdTrends["plan"] | null;
}) {
  const { state } = useAuth();
  if (state.status === "authenticated")
    return (
      <>
        <section className="card secondary-summary" aria-label="다른 기록 살펴보기">
          <h2>이번 달 돈의 흐름</h2>
          {overview && <PlanMargin overview={overview} quiet={overviewQuiet} trend={trend} />}
        </section>
        <section className="card home-records" aria-label="이번 달 수입·지출 기록">
          <div className="home-monthly-grid">
            <IncomeSummary />
            <FixedSummary />
          </div>
          <p className="muted">
            등록한 기록 기준 · 예정과 실제는 별도이며 계좌 잔액에 자동 반영하지 않아요.
          </p>
          <div className="form-actions">
            <Link to="/insurance/claims">보험 청구 내역</Link>
            <Link to="/insurance/cases?financial=open">진행 중인 보험 기록</Link>
          </div>
        </section>
      </>
    );
  return (
    <section className="card secondary-summary" aria-label="다른 기록 살펴보기">
      <h2>이번 달 돈의 흐름</h2>
      <RelatedLinks
        links={[
          { to: "/income", label: "이번 달 수입", description: "등록 수입과 실제 반환" },
          {
            to: "/fixed-payments",
            label: "등록된 고정 납부",
            description: "예정 회차와 실제 납부",
          },
          { to: "/insurance/cases", label: "진행 보험 사건", description: "치료·청구·실제 지급" },
        ]}
      />
    </section>
  );
}
