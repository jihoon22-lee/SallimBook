import { formatKrw, verificationStates } from "../months/model";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { ApiError, toApiError } from "../../../platform/api";
import { formatMonth, MonthPicker, useMonth } from "../../../shared/MonthContext";
import { MemberLoadError, useHouseholdMembers } from "../../finance/FinanceSupport";
import {
  ComparisonDates,
  ComparisonError,
  ComparisonStatus,
  PeriodLabels,
} from "./ComparisonFeedback";
import { SnapshotObservation } from "./ComparisonPage";
import { useAssetComparisonApi } from "./api";
import { signedKrw } from "./model";
import type { Comparison, ComparisonFilters } from "./model";
import { TrendPanel } from "./TrendPanel";

function MonthlyData({ assetId }: { assetId: string }) {
  const api = useAssetComparisonApi();
  const { month } = useMonth();
  const members = useHouseholdMembers();
  const filters = useMemo<ComparisonFilters>(() => ({ asset_id: assetId }), [assetId]);
  const [data, setData] = useState<Comparison | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    setLoading(true);
    void api
      .all({ ...filters, to: month }, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(toApiError(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [api, filters, month, retry]);
  const item = data?.items.find((value) => value.asset_id === assetId);
  return (
    <>
      <section className="card" aria-labelledby="asset-monthly-title">
        <h2 id="asset-monthly-title">이 자산의 월 기록</h2>
        <MonthPicker />
        <p>
          계좌와 연결된 자산도 같은 원본 금액을 사용해요. 수입·납부·보험금으로 잔액을 자동 가감하지
          않아요.
        </p>
        <ComparisonError error={error} />
        <MemberLoadError error={members.error} retry={members.retry} />
        {loading && (
          <p className="loading-state" role="status">
            이 자산의 월 기록을 확인하고 있어요.
          </p>
        )}
        {error && (
          <button type="button" onClick={() => setRetry((value) => value + 1)}>
            자산 월 기록 다시 불러오기
          </button>
        )}
        {data && (
          <>
            <div className="selected-month-amount" aria-label="선택 월 가계 보유분">
              <p>{formatMonth(month)} · 가계 보유분</p>
              <strong>
                {item?.after ? formatKrw(item.after.owned_amount_krw) : "월 기록 없음"}
              </strong>
              <p>
                {item?.after
                  ? verificationStates[item.after.verification_state]
                  : "0원으로 입력한 기록과 달라요."}
                {item?.after?.inclusion_status === "excluded" ? " · 합계 제외" : ""}
              </p>
            </div>
            <PeriodLabels data={data} />
            <ComparisonStatus data={data} />
            {item ? (
              <>
                <p>
                  항목 보유금액 변화:{" "}
                  {item.amount_delta_krw === null
                    ? "비교할 수 없음"
                    : signedKrw(item.amount_delta_krw)}
                </p>
                {item.share_changed && (
                  <p className="month-warning">가계 지분이 달라 동일 범위 변화에서는 제외돼요.</p>
                )}
                <div className="comparison-observations">
                  <section>
                    <h3>{data.from_month ? formatMonth(data.from_month) : "이전 기록 없음"}</h3>
                    <SnapshotObservation row={item.before} members={members.members} />
                  </section>
                  <section>
                    <h3>{formatMonth(month)}</h3>
                    <SnapshotObservation row={item.after} members={members.members} />
                  </section>
                </div>
              </>
            ) : (
              <p>선택한 두 월에 이 항목의 기록이 없어요. 금액을 0원으로 채우지 않아요.</p>
            )}
            <ComparisonDates data={data} />
          </>
        )}
        <div className="form-actions">
          <Link to={`/assets/months/${month}?asset_id=${assetId}`}>월 기록 입력·정정</Link>
          <Link to={`/assets/compare?to=${month}&asset_id=${assetId}`}>이 자산의 비교 상세</Link>
        </div>
      </section>
      {data && (
        <TrendPanel
          to={month}
          filters={filters}
          comparison={data}
          refreshComparison={() => setRetry((value) => value + 1)}
          title="이 자산의 보유금액 추이"
        />
      )}
    </>
  );
}
export function AssetMonthlyData({ assetId }: { assetId: string }) {
  return <MonthlyData assetId={assetId} />;
}
