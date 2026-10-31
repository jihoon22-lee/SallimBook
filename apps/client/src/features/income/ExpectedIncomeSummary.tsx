import type { components } from "@sallimbook/api-client";
import { Link } from "react-router";
import { formatKrw } from "../assets/months/model";
import type { HouseholdMember } from "../finance/FinanceSupport";

/** A current baseline, never a cash receipt for the selected month. */
export function ExpectedIncomeSummary({
  data,
  members,
}: {
  data: components["schemas"]["ExpectedIncomeSummary"] | undefined;
  members: HouseholdMember[];
}) {
  return (
    <section className="expected-income-summary" aria-label="현재 예상 월 수입">
      <div className="item-heading">
        <h2>현재 예상 월 수입</h2>
        <Link to="/income/planning">수입 기준 수정</Link>
      </div>
      {!data ? (
        <p>
          예상 수입은 <Link to="/income/planning">수입 기준</Link>에서 볼 수 있어요.
        </p>
      ) : data.record_count === 0 ? (
        <p>
          매달 예상하는 월급과 부수입을 <Link to="/income/planning">추가해 보세요.</Link>
        </p>
      ) : (
        <>
          <p className="expected-income-total">
            {data.unknown_count ? "입력된 금액 합계 " : "부부 합계 "}
            <strong>
              {data.record_count === data.unknown_count
                ? "금액 미입력"
                : formatKrw(data.known_amount_krw)}
            </strong>
            <span> / 월</span>
          </p>
          <dl className="metric-strip">
            {data.members.map((row) => (
              <div key={row.member_id}>
                <dt>
                  {members.find((m) => m.member_id === row.member_id)?.display_name ?? "구성원"}
                </dt>
                <dd>
                  {row.record_count === row.unknown_count
                    ? "금액 미입력"
                    : formatKrw(row.known_amount_krw)}
                  {row.unknown_count > 0 && <small> · 미입력 {row.unknown_count}건</small>}
                </dd>
              </div>
            ))}
          </dl>
          <p className="muted">
            현재 등록된 수입 기준이에요. 아래 실제 입금 내역과 따로 볼 수 있어요.
          </p>
        </>
      )}
    </section>
  );
}
