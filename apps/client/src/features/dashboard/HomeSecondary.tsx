import { Icon } from "../../shared/Icon";
import { useCallback } from "react";
import { Link } from "react-router";
import { formatMonth, useMonth } from "../../shared/MonthContext";
import { RelatedLinks } from "../../shared/RelatedLinks";
import { useAuth } from "../auth/AuthProvider";
import { formatKrw } from "../assets/months/model";
import { CashflowError } from "../finance/FinancialFeedback";
import { allPages, useResource } from "../finance/queries";
import { useFixedApi } from "../fixed/api";
import { useIncomeApi } from "../income/api";
import { useInsuranceApi } from "../insurance/api";
import { InsuranceError } from "../insurance/InsuranceSupport";
import { useInsuranceEventsApi } from "../insurance/events/api";
import { claimStates } from "../insurance/events/model";
function IncomeSummary() {
  const api = useIncomeApi();
  const { month } = useMonth();
  const result = useResource(useCallback(() => api.summary(month), [api, month]));
  return (
    <section className="card summary-tile">
      <div className="summary-tile-heading">
        <Icon name="cashflow" />
        <h2>등록 수입</h2>
      </div>
      <p>{formatMonth(month)} · 등록 기준</p>
      <CashflowError error={result.error} />
      {result.loading && (
        <p className="loading-state" role="status">
          등록 수입 확인 중
        </p>
      )}
      {result.error && <button onClick={() => void result.reload()}>홈 수입 다시 확인</button>}
      {result.data && !result.loading && !result.error && (
        <dl className="metadata-grid">
          <div>
            <dt>근로·부수입 순액</dt>
            <dd>{formatKrw(result.data.totals.earned_net_krw)}</dd>
          </div>
          <div>
            <dt>보험금 순유입</dt>
            <dd>{formatKrw(result.data.totals.insurance_net_krw)}</dd>
          </div>
        </dl>
      )}
      <p className="muted">실제 수령과 반환을 반영해요. 계좌 잔액을 자동으로 바꾸지 않아요.</p>
      <Link to="/income">수입 원본 확인</Link>
    </section>
  );
}
function FixedSummary() {
  const api = useFixedApi();
  const { month } = useMonth();
  const result = useResource(useCallback(() => api.summary(month), [api, month]));
  return (
    <section className="card summary-tile">
      <div className="summary-tile-heading">
        <Icon name="calendar" />
        <h2>등록된 고정 납부</h2>
      </div>
      <p>{formatMonth(month)} · 등록 기준</p>
      <CashflowError error={result.error} />
      {result.loading && (
        <p className="loading-state" role="status">
          고정 납부 확인 중
        </p>
      )}
      {result.error && <button onClick={() => void result.reload()}>홈 고정 납부 다시 확인</button>}
      {result.data && !result.loading && !result.error && (
        <>
          <dl className="metadata-grid">
            <div>
              <dt>금액이 정해진 예정</dt>
              <dd>{formatKrw(result.data.expected_known_krw)}</dd>
            </div>
            <div>
              <dt>실제 납부</dt>
              <dd>{formatKrw(result.data.actual_amount_krw)}</dd>
            </div>
          </dl>
          <p>
            예정액 미정 {result.data.unknown_expected_count}회차 · 예정{" "}
            {result.data.obligation_count}회차
          </p>
        </>
      )}
      <p className="muted">
        예정과 실제를 더하지 않아요. 원금 상환·연금 납입은 상세에서 소비와 구분해요.
      </p>
      <Link to="/fixed-payments">예정·실제 납부 확인</Link>
    </section>
  );
}
function InsuranceSummary() {
  const api = useInsuranceApi();
  const events = useInsuranceEventsApi();
  const result = useResource(
    useCallback(async () => {
      const [cases, claims] = await Promise.all([
        allPages((cursor) => api.cases({ financial_state: "open", cursor, limit: 200 })),
        allPages((cursor) => events.listInsuranceClaims({ query: { cursor, limit: 200 } })),
      ]);
      return {
        cases,
        claims: claims.filter((c) => c.claim_state !== "closed" && c.claim_state !== "withdrawn"),
      };
    }, [api, events]),
  );
  return (
    <section className="card summary-tile">
      <div className="summary-tile-heading">
        <Icon name="insurance" />
        <h2>진행 보험 사건·청구</h2>
      </div>
      <p>현재 등록 상태 · 자산 선택 월과 별도</p>
      <InsuranceError error={result.error} />
      {result.loading && (
        <p className="loading-state" role="status">
          사건과 청구 확인 중
        </p>
      )}
      {result.error && <button onClick={() => void result.reload()}>홈 보험 상태 다시 확인</button>}
      {result.data && !result.loading && !result.error && (
        <>
          <p className="summary-counts">
            정산 진행 사건 <strong>{result.data.cases.length}</strong>건 · 종료 전 청구{" "}
            <strong>{result.data.claims.length}</strong>건
          </p>
          <ul>
            {result.data.claims.slice(0, 3).map((row) => (
              <li key={row.id}>
                <Link to={`/insurance/claims/${row.id}`}>
                  {row.claim_reference || "접수번호 미입력"} ·{" "}
                  {claimStates[row.claim_state ?? "draft"]}
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="muted">청구·결정 상태만으로 실제 보험금 수령을 만들지 않아요.</p>
      <Link to="/insurance/cases?financial_state=open">사건과 청구 원본 확인</Link>
    </section>
  );
}
export function HomeSecondary() {
  const { state } = useAuth();
  return (
    <section className="secondary-summary" aria-label="다른 기록 살펴보기">
      {state.status === "authenticated" ? (
        <div className="home-secondary-grid">
          <IncomeSummary />
          <FixedSummary />
          <InsuranceSummary />
        </div>
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
