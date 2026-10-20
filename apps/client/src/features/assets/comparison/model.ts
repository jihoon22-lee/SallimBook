import type { components, operations } from "@sallimbook/api-client";
import { isValidMonth } from "../../../shared/MonthContext";
import { formatKrw } from "../months/model";
export type Comparison = components["schemas"]["AssetComparisonResponse"];
export type ComparisonItem = components["schemas"]["ComparisonItem"];
export type ComparisonQuery = operations["getAssetComparison"]["parameters"]["query"];
export type Trend = components["schemas"]["AssetTrendResponse"];
export type TrendPoint = components["schemas"]["AssetTrendPoint"];
export type TrendQuery = operations["getAssetTrends"]["parameters"]["query"];
export type ComparisonFilters = components["schemas"]["ComparisonFilters"];
export function signedKrw(value: string | null): string {
  return value !== null && /^[1-9][0-9]{0,19}$/.test(value)
    ? `+${formatKrw(value)}`
    : formatKrw(value);
}
export function percentLabel(value: string | null): string {
  return value === null
    ? "계산하지 않음"
    : `${value === "0.00" || value.startsWith("-") ? "" : "+"}${value}%`;
}
export function monthsBefore(month: string, count: number): string {
  if (!isValidMonth(month) || !Number.isInteger(count) || count < 0 || count > 119) return "";
  const index = Math.max(
    0,
    (Number(month.slice(0, 4)) - 1) * 12 + Number(month.slice(5)) - 1 - count,
  );
  return `${String(Math.floor(index / 12) + 1).padStart(4, "0")}-${String((index % 12) + 1).padStart(2, "0")}`;
}
export const scopeReasons: Record<NonNullable<ComparisonItem["scope_reason"]>, string> = {
  previously_held_added: "이전에 보유한 항목이 새 비교 대상에 포함됨",
  started_after_previous_period: "이전 비교월 이후 보유를 시작한 항목",
  ended_before_current_period: "확인 월 전에 보유가 종료된 항목",
  not_in_previous_scope: "이전 비교 범위에 없던 항목",
  not_in_current_scope: "현재 비교 범위에서 제외됨 · 사유 확인 필요",
  inclusion_changed: "순자산 합계 포함 여부 변경",
  filter_membership_changed: "소유자·분류 등 선택한 필터의 대상 변경",
  household_share_changed: "가계 지분 변경 · 동일 범위 변화에서 제외",
  excluded_from_total: "순자산 합계에서 제외된 참고 금액",
};
export const trendValueStates: Record<TrendPoint["value_state"], string> = {
  missing_month: "월 기록 없음",
  missing_item: "이 달의 항목 없음",
  outside_filter: "필터 범위 밖",
  missing_value: "금액 미입력",
  unconfirmed: "미확정 참고값",
  verified: "확정값",
};
export function revisionKey(
  value: components["schemas"]["MonthReference"] | null | undefined,
): string {
  return JSON.stringify(
    value ? [value.month, value.revision_id, value.revision_no, value.version] : null,
  );
}
export function comparisonIdentity(value: Comparison): string {
  return JSON.stringify([
    value.from_month,
    value.to_month,
    value.previous?.revision ?? null,
    value.current.revision,
    value.state,
    value.item_count,
  ]);
}
/** Amounts stay BigInt. Only bounded pixel coordinates become Number for SVG rendering. */
export function chartCoordinates(points: TrendPoint[]) {
  const amounts = points.flatMap((point) =>
    point.confirmed_amount_krw === null ? [] : [BigInt(point.confirmed_amount_krw)],
  );
  if (!amounts.length) return null;
  const minimum = amounts.reduce((a, b) => (a < b ? a : b));
  const maximum = amounts.reduce((a, b) => (a > b ? a : b));
  const range = maximum - minimum;
  const rows = points.map((point, index) => ({
    point,
    index,
    x: points.length < 2 ? 320 : 48 + (index * 544) / (points.length - 1),
    y:
      point.confirmed_amount_krw === null
        ? null
        : range === 0n
          ? 105
          : 185 - Number(((BigInt(point.confirmed_amount_krw) - minimum) * 16000n) / range) / 100,
  }));
  const segments: (typeof rows)[] = [];
  let segment: typeof rows = [];
  for (const row of rows) {
    if (row.y === null) {
      if (segment.length) segments.push(segment);
      segment = [];
    } else segment.push(row);
  }
  if (segment.length) segments.push(segment);
  return { minimum: minimum.toString(), maximum: maximum.toString(), rows, segments };
}
