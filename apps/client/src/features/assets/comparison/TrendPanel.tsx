import { useEffect, useId, useMemo, useState } from "react";
import { Link } from "react-router";
import { ApiError, toApiError } from "../../../platform/api";
import { formatMonth } from "../../../shared/MonthContext";
import { dateLabel } from "../../finance/dates";
import { formatKrw, monthStates } from "../months/model";
import { useAssetComparisonApi } from "./api";
import { ComparisonError } from "./ComparisonFeedback";
import { chartCoordinates, monthsBefore, revisionKey, trendValueStates } from "./model";
import type { Comparison, ComparisonFilters, Trend } from "./model";

/** About six month labels along the axis: always the first and last, never crowded together. */
function labelledRows<T extends { index: number }>(rows: T[]): T[] {
  const step = Math.max(1, Math.ceil(rows.length / 6));
  const last = rows.length - 1;
  const picked = rows.filter((row) => row.index % step === 0);
  if (last % step === 0) return picked;
  const kept = picked.filter((row) => last - row.index >= Math.ceil(step * 0.75));
  return [...kept, rows[last]!];
}

export function TrendChart({ data }: { data: Trend }) {
  const id = useId();
  const graph = useMemo(() => chartCoordinates(data.points), [data.points]);
  const [active, setActive] = useState(data.points.length - 1);
  const index = Math.min(Math.max(active, 0), data.points.length - 1);
  const selected = data.points[index];
  const monthLabels = graph ? labelledRows(graph.rows) : [];
  // Targets are as wide as the spacing allows (48 units, about 24px on a phone), never overlapping.
  const hit = graph ? Math.min(24, Math.max(8, 544 / Math.max(graph.rows.length - 1, 1) / 2)) : 0;
  return (
    <>
      <p className="muted">
        차트는 확정된 금액만 이어 그려요. 기록 없음·미입력·미확정 구간은 선을 끊어요.
      </p>
      {graph ? (
        <svg
          className="asset-trend-chart"
          viewBox="0 0 640 250"
          role="img"
          aria-labelledby={`${id}-title ${id}-desc`}
        >
          <title id={`${id}-title`}>
            {data.series_kind === "asset_owned_amount"
              ? "월별 가계 보유금액 추이"
              : "월별 순자산 추이"}
          </title>
          <desc id={`${id}-desc`}>
            확정값만 표시합니다. 각 월을 선택하면 정확한 원 단위 금액과 확인 상태를 아래에서 볼 수
            있습니다.
          </desc>
          <line x1="48" y1="185" x2="592" y2="185" className="chart-axis" />
          <text x="48" y="15" className="chart-label">
            최고 {formatKrw(graph.maximum)}
          </text>
          {monthLabels.map((row) => (
            <text
              key={row.index}
              x={row.x}
              y="204"
              textAnchor="middle"
              className="chart-label chart-month"
            >
              {row.point.month.replace("-", ".")}
            </text>
          ))}
          <text x="48" y="244" className="chart-label">
            최저 {formatKrw(graph.minimum)}
          </text>
          {graph.segments
            .filter((segment) => segment.length > 1)
            .map((segment) => (
              <polyline
                key={segment[0]!.index}
                fill="none"
                className="chart-line"
                points={segment.map((row) => `${row.x},${row.y}`).join(" ")}
              />
            ))}
          {graph.rows.map((row) =>
            row.y === null ? (
              <line key={row.index} x1={row.x} x2={row.x} y1="180" y2="190" className="chart-gap" />
            ) : (
              <g key={row.index}>
                <circle
                  cx={row.x}
                  cy={row.y}
                  r={hit}
                  className="chart-point"
                  tabIndex={0}
                  role="button"
                  aria-label={`${formatMonth(row.point.month)} ${formatKrw(row.point.confirmed_amount_krw)}`}
                  onFocus={() => setActive(row.index)}
                  onMouseEnter={() => setActive(row.index)}
                  onClick={() => setActive(row.index)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setActive(row.index);
                    }
                  }}
                />
                <circle
                  cx={row.x}
                  cy={row.y}
                  r={row.index === index ? 7 : 5}
                  className="chart-dot"
                  aria-hidden="true"
                />
              </g>
            ),
          )}
        </svg>
      ) : (
        <p className="empty-state">
          아직 차트에 표시할 확정 금액이 없어요. 아래에서 각 월의 상태를 확인해 주세요.
        </p>
      )}
      {selected && (
        <div className="chart-inspector">
          <div className="form-field">
            <label htmlFor={`${id}-month`}>차트에서 확인할 월</label>
            <select
              id={`${id}-month`}
              value={index}
              onChange={(event) => setActive(Number(event.target.value))}
            >
              {data.points.map((point, number) => (
                <option value={number} key={point.month}>
                  {formatMonth(point.month)} · {trendValueStates[point.value_state]}
                </option>
              ))}
            </select>
          </div>
          <p aria-live="polite">
            {formatMonth(selected.month)} · {trendValueStates[selected.value_state]} ·{" "}
            {selected.observed_amount_krw === null
              ? "금액 없음"
              : formatKrw(selected.observed_amount_krw)}
            {selected.as_of_date ? ` · 기준일 ${dateLabel(selected.as_of_date)}` : ""}
            {selected.included_in_total === false ? " · 순자산 합계 제외" : ""}
          </p>
        </div>
      )}
    </>
  );
}

export function TrendPanel({
  to,
  filters,
  title = "월별 추이",
  comparison,
  refreshComparison,
}: {
  to: string;
  filters: ComparisonFilters;
  title?: string;
  comparison?: Comparison;
  refreshComparison?: () => void;
}) {
  const api = useAssetComparisonApi();
  const id = useId();
  const [span, setSpan] = useState(12);
  const [retry, setRetry] = useState(0);
  const [data, setData] = useState<Trend | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const from = monthsBefore(to, span - 1);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setLoading(true);
    setError(null);
    void api
      .trend({ ...filters, from, to }, controller.signal)
      .then((value) => {
        for (const period of [comparison?.previous, comparison?.current]) {
          if (!period) continue;
          const point = value.points.find((item) => item.month === period.month);
          if (
            point &&
            (revisionKey(point.revision) !== revisionKey(period.revision) ||
              point.state !== period.state)
          )
            throw new ApiError(409, "REVISION_CONFLICT");
        }
        if (!controller.signal.aborted) setData(value);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(toApiError(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [api, filters, from, to, retry, comparison]);
  return (
    <section className="card" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>{title}</h2>
      <div className="form-field">
        <label htmlFor={`${id}-span`}>추이 기간</label>
        <select
          id={`${id}-span`}
          value={span}
          onChange={(event) => setSpan(Number(event.target.value))}
        >
          {[3, 6, 12, 24, 60, 120].map((value) => (
            <option key={value} value={value}>
              최근 {value}개월
            </option>
          ))}
        </select>
      </div>
      <p>
        {formatMonth(from)} ~ {formatMonth(to)}
      </p>
      <ComparisonError error={error} />
      {loading && (
        <p className="loading-state" role="status">
          월별 추이를 불러오고 있어요.
        </p>
      )}
      {error && (
        <button
          type="button"
          onClick={() => {
            if (error.code === "REVISION_CONFLICT" && refreshComparison) refreshComparison();
            else setRetry((value) => value + 1);
          }}
        >
          {error.code === "REVISION_CONFLICT" && refreshComparison
            ? "비교와 추이 함께 다시 확인"
            : "추이 다시 불러오기"}
        </button>
      )}
      {data && (
        <>
          <TrendChart key={`${from}:${to}`} data={data} />
          <div className="table-scroll" tabIndex={0} role="region" aria-label="월별 추이 금액 표">
            <table>
              <caption>
                {data.series_kind === "asset_owned_amount" ? "항목별 가계 보유금액" : "가계 순자산"}{" "}
                · 빈 값과 미확정 구분
              </caption>
              <thead>
                <tr>
                  <th scope="col">월</th>
                  <th scope="col">기록 상태</th>
                  <th scope="col">금액 상태</th>
                  <th scope="col">관찰 금액</th>
                  <th scope="col">기준일</th>
                </tr>
              </thead>
              <tbody>
                {data.points.map((point) => (
                  <tr key={point.month}>
                    <th scope="row">
                      <Link to={`/assets/months/${point.month}`}>{formatMonth(point.month)}</Link>
                    </th>
                    <td>{point.state === "missing" ? "기록 없음" : monthStates[point.state]}</td>
                    <td>
                      {trendValueStates[point.value_state]}
                      {point.included_in_total === false ? " · 합계 제외" : ""}
                    </td>
                    <td>
                      {point.observed_amount_krw === null
                        ? "—"
                        : formatKrw(point.observed_amount_krw)}
                    </td>
                    <td>
                      {point.as_of_date
                        ? dateLabel(point.as_of_date)
                        : [
                              "missing_month",
                              "missing_item",
                              "outside_filter",
                              "missing_value",
                            ].includes(point.value_state)
                          ? "기준일 없음"
                          : point.totals?.item_count === 0
                            ? "포함 항목 없음"
                            : point.dates.mixed_dates
                              ? "여러 기준일"
                              : point.dates.non_month_end_asset_ids.length
                                ? "월말 아닌 날짜 포함"
                                : point.state === "missing" ||
                                    point.dates.missing_date_asset_ids.length
                                  ? "확인 필요"
                                  : "월말 기준"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
