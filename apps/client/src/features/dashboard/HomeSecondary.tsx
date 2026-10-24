import { useCallback } from "react";
import { Link } from "react-router";
import { formatMonth, useMonth } from "../../shared/MonthContext";
import { RelatedLinks } from "../../shared/RelatedLinks";
import { useAuth } from "../auth/AuthProvider";
import { formatKrw } from "../assets/months/model";
import { CashflowError } from "../finance/FinancialFeedback";
import { useResource } from "../finance/queries";
import { useFixedApi } from "../fixed/api";
import { useIncomeApi } from "../income/api";

function IncomeSummary() {
  const api = useIncomeApi();
  const { month } = useMonth();
  const result = useResource(useCallback(() => api.summary(month), [api, month]));
  const ready = result.data && !result.loading && !result.error;
  return (
    <section className="home-summary-part" aria-label="홈 등록 수입 요약">
      <h3>등록 수입</h3>
      <CashflowError error={result.error} />
      {result.loading && <p role="status">등록 수입 확인 중</p>}
      {result.error && <button onClick={() => void result.reload()}>홈 수입 다시 확인</button>}
      {ready &&
        (result.data!.totals.record_count === 0 ? (
          <p>
            이 달에 등록한 수입 기록이 없어요. <Link to="/income/new">수입 입력</Link>
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
      <Link to="/income">수입 원본 확인</Link>
    </section>
  );
}
function FixedSummary() {
  const api = useFixedApi();
  const { month } = useMonth();
  const result = useResource(useCallback(() => api.summary(month), [api, month]));
  const ready = result.data && !result.loading && !result.error;
  return (
    <section className="home-summary-part" aria-label="홈 고정 납부 요약">
      <h3>등록된 고정 납부</h3>
      <CashflowError error={result.error} />
      {result.loading && <p role="status">고정 납부 확인 중</p>}
      {result.error && <button onClick={() => void result.reload()}>홈 고정 납부 다시 확인</button>}
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
      <Link to="/fixed-payments">예정·실제 납부 확인</Link>
    </section>
  );
}
export function HomeSecondary() {
  const { state } = useAuth();
  const { month, currentMonth } = useMonth();
  return (
    <section className="card secondary-summary" aria-label="다른 기록 살펴보기">
      <h2>{month === currentMonth ? "이번 달 요약" : `${formatMonth(month)} 요약`}</h2>
      {state.status === "authenticated" ? (
        <>
          <div className="home-monthly-grid">
            <IncomeSummary />
            <FixedSummary />
          </div>
          <p className="muted">
            등록한 기록 기준 · 예정과 실제는 별도이며 계좌 잔액에 자동 반영하지 않아요.
          </p>
          <div className="form-actions">
            <Link to="/insurance/claims">보험 청구 작업함</Link>
            <Link to="/insurance/cases?financial=open">사건과 청구 원본 확인</Link>
          </div>
        </>
      ) : (
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
      )}
    </section>
  );
}
