import { Link } from "react-router";
import { formatKrw } from "../assets/months/model";
import { AuthenticatedFinance, CashflowError } from "../finance/FinancialFeedback";
import { economicTypes } from "../fixed/model";
import { useHouseholdTrends, type HouseholdTrends } from "../dashboard/overviewApi";
import { StackedColumns, type Column } from "../../shared/Charts";
import { formatKrwChange, krwDifference } from "../../shared/krwShort";
import { formatMonth, useMonth } from "../../shared/MonthContext";

type Point = HouseholdTrends["plan"][number];
const MONTHS = 12;
const parts = [
  ["spending_known_krw", economicTypes.expense, "spend"],
  ["loan_known_krw", economicTypes.loan, "loan"],
  ["transfer_known_krw", economicTypes.asset_transfer, "save"],
] as const;

function columns(plan: Point[]): Column[] {
  return plan.map((point, index) => {
    const left = point.margin_after_transfers_krw;
    return {
      key: point.month,
      tick:
        index === 0 || point.month.endsWith("-01")
          ? point.month.slice(2).replace("-", ".")
          : String(Number(point.month.slice(5))),
      label: formatMonth(point.month),
      segments: [
        ...parts.map(([key, name, tone]) => ({ name, value: point[key], tone })),
        // A month that falls short has no "left" part; the table states the shortfall.
        { name: "남는 돈", value: left !== null && BigInt(left) > 0n ? left : "0", tone: "left" },
      ],
    };
  });
}

/** What changed in the registered plan between two consecutive months, in the household's words. */
function changes(point: Point, before: Point | undefined) {
  if (!before) return "";
  return [
    ["income_known_krw", "예상 수입"] as const,
    ...parts.map(([key, name]) => [key, name] as const),
  ]
    .flatMap(([key, name]) => {
      const difference = krwDifference(point[key], before[key]);
      return difference && difference !== "0" ? [`${name} ${formatKrwChange(difference)}`] : [];
    })
    .join(", ");
}

function Flow() {
  const { currentMonth } = useMonth();
  const trends = useHouseholdTrends(currentMonth, MONTHS);
  const plan = trends.data?.plan;
  if (!plan)
    return trends.error ? (
      <>
        <CashflowError error={trends.error} />
        <button type="button" onClick={() => void trends.reload()}>
          월별 흐름 다시 불러오기
        </button>
      </>
    ) : (
      <p role="status">월별 흐름 불러오는 중</p>
    );
  const drawn = plan.some((point) => point.margin_after_transfers_krw !== null);
  const rows = plan.map((point, index) => ({ point, before: plan[index - 1] })).reverse();
  return (
    <>
      <section className="card" aria-labelledby="monthly-flow-chart">
        <div className="item-heading">
          <h2 id="monthly-flow-chart">매달 예상 수입이 어디로 가는지</h2>
          <p className="chart-legend">
            {[["left", "남는 돈"], ...parts.map(([, name, tone]) => [tone, name]).reverse()].map(
              ([tone, name]) => (
                <span key={tone}>
                  <i className={`chart-key chart-tone-${tone}`} aria-hidden="true" />
                  {name}
                </span>
              ),
            )}
          </p>
        </div>
        {drawn ? (
          <StackedColumns title="월별 예상 수입의 쓰임" columns={columns(plan)} />
        ) : (
          <p>
            예상 수입 금액을 등록하면 달마다 남는 돈을 볼 수 있어요.{" "}
            <Link to="/income/planning">예상 수입 등록</Link>
          </p>
        )}
        <p className="muted">
          그 달 말에 등록돼 있던 예상 수입과 월 계획으로 계산해요. 이번 달은 오늘 기준이에요. 실제
          잔액·저축액이 아니에요.
        </p>
      </section>
      <section className="card" aria-labelledby="monthly-flow-table">
        <h2 id="monthly-flow-table">월별 표</h2>
        <div className="table-scroll" role="region" aria-label="월별 흐름 표" tabIndex={0}>
          <table className="flow-table">
            <thead>
              <tr>
                <th scope="col">월</th>
                <th scope="col">예상 수입</th>
                {parts.map(([, name]) => (
                  <th scope="col" key={name}>
                    {name}
                  </th>
                ))}
                <th scope="col">남는 돈</th>
                <th scope="col">기록한 실제 입금</th>
                <th scope="col">바뀐 점</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ point, before }) => (
                <tr key={point.month}>
                  <th scope="row">{formatMonth(point.month)}</th>
                  <td>
                    {point.income_count === 0
                      ? "등록 전"
                      : point.income_unknown_count === point.income_count
                        ? "금액 미입력"
                        : formatKrw(point.income_known_krw)}
                  </td>
                  {parts.map(([key]) => (
                    <td key={key}>{formatKrw(point[key])}</td>
                  ))}
                  <td className="flow-left">
                    {point.margin_after_transfers_krw === null
                      ? "—"
                      : formatKrw(point.margin_after_transfers_krw)}
                  </td>
                  <td>
                    {point.actual_income_krw === "0"
                      ? "기록 없음"
                      : formatKrw(point.actual_income_krw)}
                  </td>
                  <td className="flow-changes">{changes(point, before)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

export function MonthlyFlowPage() {
  return (
    <AuthenticatedFinance
      title="월별 흐름"
      description="등록한 예상 수입과 월 계획으로 달마다 남는 돈을 살펴요."
    >
      <Flow />
    </AuthenticatedFinance>
  );
}
