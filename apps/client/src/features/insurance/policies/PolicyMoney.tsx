import { Link } from "react-router";
import { formatKrw } from "../../assets/months/model";
import { useInsuranceSummary, type InsuranceSummary } from "../../dashboard/overviewApi";
import { formatMonth } from "../../../shared/month";
import { sharePercent } from "../../../shared/krwShort";
import { InsuranceError } from "../InsuranceSupport";

type Row = InsuranceSummary["policies"][number];

/** How the paid total was put together, so an estimate never reads as a ledger. */
function basis(row: Row) {
  const parts = [
    row.paid_before_krw !== null &&
      `직접 입력 ${formatKrw(row.paid_before_krw)}(${row.paid_through}까지)`,
    row.estimated_from_month !== null &&
      `${formatMonth(row.estimated_from_month)}부터 ${row.estimated_months}개월 계획 금액 ${formatKrw(row.paid_estimated_krw)}`,
    row.unknown_months > 0 && `금액 미정 ${row.unknown_months}개월 제외`,
  ].filter(Boolean);
  return parts.join(" + ").replace(" + 금액", " · 금액");
}

function Ratio({ paid, received }: { paid: string; received: string }) {
  return (
    <dl className="ratio-rows">
      <div>
        <dt>낸 보험료</dt>
        <dd>
          <span className="ratio-track">
            <span className="ratio-paid" style={{ width: "100%" }} />
          </span>
          <b>{formatKrw(paid)}</b>
        </dd>
      </div>
      <div>
        <dt>받은 보험금</dt>
        <dd>
          <span className="ratio-track">
            <span
              className="ratio-received"
              style={{ width: `${sharePercent(received, paid)}%` }}
            />
          </span>
          <b>{formatKrw(received)}</b>
        </dd>
      </div>
    </dl>
  );
}

/** One policy's premiums paid against benefits actually received. */
export function PolicyMoney({ policyId }: { policyId: string }) {
  const summary = useInsuranceSummary();
  const row = summary.data?.policies.find((item) => item.policy_id === policyId);
  return (
    <section className="card" aria-labelledby="policy-money-title">
      <h2 id="policy-money-title">낸 보험료와 받은 보험금</h2>
      {!summary.data && summary.loading && <p role="status">보험료와 보험금 확인 중</p>}
      {!summary.data && summary.error && (
        <>
          <InsuranceError error={summary.error} />
          <button type="button" onClick={() => void summary.reload()}>
            보험료와 보험금 다시 확인
          </button>
        </>
      )}
      {row &&
        (row.paid_total_krw === null ? (
          <>
            <p>
              받은 보험금 <strong>{formatKrw(row.received_krw)}</strong>
            </p>
            <p className="muted">
              낸 보험료를 아직 알 수 없어요. 계약 정보에 &lsquo;이미 낸 보험료&rsquo;를 적거나
              아래에서 보험료 항목을 연결하면 회수율을 볼 수 있어요.
            </p>
          </>
        ) : (
          <>
            <p className="panel-figure">
              <strong>{row.recovery_percent === null ? "—" : `${row.recovery_percent}%`}</strong>
              <span className="muted">낸 보험료 대비 받은 보험금</span>
            </p>
            <Ratio paid={row.paid_total_krw} received={row.received_krw} />
            <p className="muted">
              낸 보험료는 {basis(row)}이에요. 실제 납부 기록이 아니라 등록한 내용으로 계산한
              추정이에요.
            </p>
          </>
        ))}
    </section>
  );
}

/** Every policy side by side, for the insurance home. */
export function InsuranceMoney() {
  const summary = useInsuranceSummary();
  const data = summary.data;
  if (!data)
    return summary.error ? (
      <section className="card" aria-label="낸 보험료와 받은 보험금">
        <InsuranceError error={summary.error} />
        <button type="button" onClick={() => void summary.reload()}>
          보험료와 보험금 다시 확인
        </button>
      </section>
    ) : null;
  if (data.policy_count === 0) return null;
  const known = data.paid_unknown_count < data.policy_count;
  return (
    <section className="card" aria-labelledby="insurance-money-title">
      <h2 id="insurance-money-title">낸 보험료와 받은 보험금</h2>
      {known ? (
        <>
          <p className="panel-figure">
            <strong>{data.recovery_percent === null ? "—" : `${data.recovery_percent}%`}</strong>
            <span className="muted">
              낸 보험료 대비 받은 보험금
              {data.monthly_premium_krw !== "0" && ` · 매달 ${formatKrw(data.monthly_premium_krw)}`}
            </span>
          </p>
          <Ratio paid={data.paid_total_krw} received={data.matched_received_krw} />
          {data.paid_unknown_count > 0 && (
            <p className="muted">
              낸 보험료를 모르는 계약 {data.paid_unknown_count}개와 계약을 지정하지 않은 보험금은
              비율에서 뺐어요.
            </p>
          )}
        </>
      ) : (
        <p className="muted">
          계약에 &lsquo;이미 낸 보험료&rsquo;를 적거나 보험료 항목을 연결하면 낸 보험료 대비 받은
          보험금을 볼 수 있어요.
        </p>
      )}
      <div className="table-scroll" role="region" aria-label="계약별 보험료와 보험금" tabIndex={0}>
        <table className="flow-table">
          <thead>
            <tr>
              <th scope="col">계약</th>
              <th scope="col">매달 보험료</th>
              <th scope="col">낸 보험료</th>
              <th scope="col">받은 보험금</th>
              <th scope="col">회수율</th>
            </tr>
          </thead>
          <tbody>
            {data.policies.map((row) => (
              <tr key={row.policy_id}>
                <th scope="row">
                  <Link to={`/insurance/policies/${row.policy_id}`}>
                    {row.insurer} · {row.product_name}
                  </Link>
                </th>
                <td>
                  {row.monthly_premium_krw === "0" ? "—" : formatKrw(row.monthly_premium_krw)}
                </td>
                <td>
                  {row.paid_total_krw === null ? "알 수 없음" : formatKrw(row.paid_total_krw)}
                </td>
                <td>{formatKrw(row.received_krw)}</td>
                <td>{row.recovery_percent === null ? "—" : `${row.recovery_percent}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.unassigned_received_krw !== "0" && (
        <p className="muted">
          계약을 지정하지 않은 보험금 {formatKrw(data.unassigned_received_krw)}은 비율에 넣지
          않았어요.
        </p>
      )}
      <p className="muted">
        낸 보험료는 직접 적은 금액과 연결한 보험료 항목으로 계산한 추정이에요. 받은 보험금은 실제
        수령에서 반환을 뺀 금액이에요.
      </p>
    </section>
  );
}
