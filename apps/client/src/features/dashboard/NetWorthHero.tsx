import { Link } from "react-router";
import { formatKrw } from "../assets/months/model";
import { FinanceError } from "../finance/FinanceSupport";
import { TrendLine, type TrendPoint } from "../../shared/Charts";
import { formatKrwChange, formatKrwShort, krwDifference } from "../../shared/krwShort";
import { formatMonth, useMonth } from "../../shared/MonthContext";
import { StaleNotice } from "../../shared/StaleNotice";
import type { HouseholdTrends, OverviewResource } from "./overviewApi";

type Trends = { data: HouseholdTrends | null; error: unknown; loading: boolean };

export function netAssetPoints(points: HouseholdTrends["net_assets"]): TrendPoint[] {
  return points.map((point, index) => ({
    key: point.month,
    tick:
      index === 0 || point.month.endsWith("-01")
        ? point.month.slice(2).replace("-", ".")
        : String(Number(point.month.slice(5))),
    label: formatMonth(point.month),
    value: point.net_assets_krw,
    solid: point.confirmed,
    detail: point.confirmed ? "확정" : "입력한 금액 기준",
  }));
}

/** The household total from registered records, with how it moved; never gated on a month record. */
export function NetWorthHero({
  overview,
  trends,
  quiet,
}: {
  overview: OverviewResource;
  trends: Trends;
  quiet: boolean;
}) {
  const { month } = useMonth();
  const data = overview.data;
  if (!data)
    return (
      <section className="net-hero" aria-label="저장된 자산 금액">
        {overview.error ? (
          !quiet && (
            <>
              <FinanceError error={overview.error} />
              <button type="button" onClick={() => void overview.reload()}>
                보유 현황 다시 불러오기
              </button>
            </>
          )
        ) : (
          <p role="status">보유 현황 불러오는 중</p>
        )}
      </section>
    );
  const holdings = data.holdings;
  const series = trends.data?.net_assets ?? [];
  // The change is only "since last month" when the series really ends at the month on screen.
  const aligned = series.length > 1 && series.at(-1)!.month === month;
  const previous = aligned ? series[series.length - 2]!.net_assets_krw : null;
  const change =
    previous !== null && holdings.known_count > 0
      ? krwDifference(holdings.net_assets_krw, previous)
      : null;
  const notes = [
    holdings.missing_count > 0 && `금액 미입력 ${holdings.missing_count}개`,
    holdings.stale_count > 0 && `오래된 금액 ${holdings.stale_count}개`,
    holdings.oldest_basis_month &&
      holdings.oldest_basis_month !== month &&
      `가장 오래된 기준 ${formatMonth(holdings.oldest_basis_month)}`,
  ].filter(Boolean);
  return (
    <section className="net-hero" aria-label="저장된 자산 금액" aria-busy={overview.loading}>
      {overview.error && !quiet && <StaleNotice retry={() => void overview.reload()} />}
      <div className="item-heading">
        <h2>등록 기준 순자산</h2>
        <Link to="/assets">자산 전체 보기</Link>
      </div>
      {holdings.item_count === 0 ? (
        <p>
          아직 합계에 넣을 자산·계좌가 없어요. <Link to="/assets/new">자산 등록</Link> ·{" "}
          <Link to="/accounts/new">계좌 등록</Link>
        </p>
      ) : holdings.known_count === 0 ? (
        <p>등록한 {holdings.item_count}개 항목의 금액을 아직 입력하지 않았어요.</p>
      ) : (
        <>
          <p className="net-figure">{formatKrwShort(holdings.net_assets_krw)}</p>
          <p className="net-meta">
            {change !== null && (
              <span className={BigInt(change) < 0n ? "net-change net-change-down" : "net-change"}>
                {change === "0" ? (
                  "지난달과 같음"
                ) : (
                  <>
                    {formatKrwChange(change)} <small>지난달보다</small>
                  </>
                )}
              </span>
            )}
            <span className="muted">{formatKrw(holdings.net_assets_krw)}</span>
          </p>
          {series.length > 1 && (
            <>
              <p className="chart-legend">
                <span>
                  <i className="chart-dot-key" aria-hidden="true" />
                  확정한 달
                </span>
                <span>
                  <i className="chart-dot-key chart-dot-key-open" aria-hidden="true" />
                  입력한 금액 기준
                </span>
              </p>
              <TrendLine
                title={`${formatMonth(series[0]!.month)}부터 ${formatMonth(series.at(-1)!.month)}까지 순자산`}
                points={netAssetPoints(series)}
              />
              <details className="home-detail">
                <summary>월별 금액 표로 보기</summary>
                <div
                  className="table-scroll"
                  role="region"
                  aria-label="월별 순자산 표"
                  tabIndex={0}
                >
                  <table className="flow-table net-table">
                    <thead>
                      <tr>
                        <th scope="col">월</th>
                        <th scope="col">순자산</th>
                        <th scope="col">자산</th>
                        <th scope="col">부채</th>
                        <th scope="col">기준</th>
                      </tr>
                    </thead>
                    <tbody>
                      {series
                        .slice()
                        .reverse()
                        .map((point) => (
                          <tr key={point.month}>
                            <th scope="row">{formatMonth(point.month)}</th>
                            <td>
                              {point.net_assets_krw === null
                                ? "금액 없음"
                                : formatKrw(point.net_assets_krw)}
                            </td>
                            <td>{point.assets_krw === null ? "—" : formatKrw(point.assets_krw)}</td>
                            <td>
                              {point.liabilities_krw === null
                                ? "—"
                                : formatKrw(point.liabilities_krw)}
                            </td>
                            <td>
                              {point.net_assets_krw === null
                                ? ""
                                : point.confirmed
                                  ? "확정"
                                  : `입력한 금액 기준 · 이 달 입력 ${point.entered_count}개`}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </>
          )}
          <dl className="net-totals">
            <div>
              <dt>자산</dt>
              <dd>{formatKrw(holdings.assets_krw)}</dd>
            </div>
            <div>
              <dt>부채</dt>
              <dd>{formatKrw(holdings.liabilities_krw)}</dd>
            </div>
          </dl>
          <p className="muted net-basis">
            항목마다 마지막으로 입력하거나 확인한 금액이에요.
            {notes.length > 0 && ` ${notes.join(" · ")}`}
          </p>
        </>
      )}
      <Link to={`/assets/months/${month}`}>금액 입력·수정</Link>
    </section>
  );
}
