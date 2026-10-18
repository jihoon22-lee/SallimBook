import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Icon } from "../../shared/Icon";
import { ApiError, toApiError } from "../../platform/api";
import { formatMonth, useMonth } from "../../shared/MonthContext";
import { useAuth } from "../auth/AuthProvider";
import { useAssetComparisonApi } from "../assets/comparison/api";
import { ComparisonDates, ComparisonError, ComparisonNotes, ComparisonStatus, PeriodLabels, ScopeWarning } from "../assets/comparison/ComparisonFeedback";
import { formatKrw, monthStates } from "../assets/months/model";
import { percentLabel, signedKrw } from "../assets/comparison/model";
import type { Comparison } from "../assets/comparison/model";
function CurrentAssetSummary() {
  const api = useAssetComparisonApi(); const { month } = useMonth(); const [data, setData] = useState<Comparison | null>(null); const [error, setError] = useState<ApiError | null>(null); const [loading, setLoading] = useState(true); const [retry, setRetry] = useState(0);
  useEffect(() => { const controller = new AbortController(); setData(null); setError(null); setLoading(true);
    void api.comparison({ to: month, limit: 1 }, controller.signal).then((value) => { if (!controller.signal.aborted) setData(value); }).catch((failure) => { if (!controller.signal.aborted) setError(toApiError(failure)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); }); return () => controller.abort();
  }, [api, month, retry]);
  const totals = data?.current.totals;
  const dateCaution = data && [data.previous, data.current].some((period) => period && (period.dates.mixed_dates || period.dates.non_month_end_asset_ids.length > 0 || period.dates.missing_date_asset_ids.length > 0));
  return <><ComparisonError error={error} />{loading && <p className="loading-state" role="status">월간 자산 변화를 불러오고 있어요.</p>}{error && <button type="button" onClick={() => setRetry((value) => value + 1)}>홈 자산 정보 다시 확인</button>}{!data && <div className="form-actions home-card-actions"><Link className="button-link" to={`/assets/compare?to=${month}`} aria-label="월간 비교 자세히 보기">월간 비교 <Icon name="arrow-right" size={14} /></Link><Link to={`/assets/months/${month}`}>이 달 기록 확인</Link><Link to="/assets">자산 관리</Link></div>}{data && <>
    <div className="asset-hero"><span className="metric-label">확인 월 순자산</span><strong className="asset-hero-value">{!totals ? "월 기록 없음" : totals.net_assets_krw === null ? "금액 확인 필요" : formatKrw(totals.net_assets_krw)}</strong><div className="asset-hero-change"><span>전체 순자산 변화</span><strong>{data.total_delta_krw === null ? "비교할 수 없음" : signedKrw(data.total_delta_krw)}</strong></div></div>
    {totals && <><dl className="asset-mini-totals"><div><dt>총자산</dt><dd>{formatKrw(totals.assets_krw)}</dd></div><div><dt>부채</dt><dd>{formatKrw(totals.liabilities_krw)}</dd></div></dl><p className="snapshot-check" role="status">{totals.provisional ? "임시 합계" : "확인한 합계"} · 확인 {totals.verified_count}/{totals.item_count}개 · 미입력 {totals.missing_count}개 · 전월값 미확인 {totals.carried_count}개</p></>}
    <div className="snapshot-notices">{(data.current.state === "draft" || data.current.state === "reopened") && <span className="notice-badge">확인 월 {monthStates[data.current.state]}</span>}{data.state !== "available" && <span className="notice-badge">{data.state === "current_missing" ? "확인 월 기록 없음" : data.state === "no_previous_month" ? "이전 월 기록 없음" : "미확정 월 · 증감 미계산"}</span>}{data.scope_changed && <span className="notice-badge">비교 대상·지분 변경</span>}{dateCaution && <span className="notice-badge">기준일 확인 필요</span>}</div>
    <div className="asset-detail-actions"><details className="home-detail"><summary>비교 기준과 상세 금액</summary><PeriodLabels data={data} /><ComparisonStatus data={data} /><dl className="metadata-grid"><div><dt>이전 비교월 순자산</dt><dd>{data.previous?.totals ? data.previous.totals.net_assets_krw === null ? "금액 확인 필요" : formatKrw(data.previous.totals.net_assets_krw) : "월 기록 없음"}</dd></div><div><dt>동일 범위 변화</dt><dd>{data.common_scope_delta_krw === null ? "비교할 수 없음" : signedKrw(data.common_scope_delta_krw)}</dd></div><div><dt>순자산 증감률</dt><dd>{percentLabel(data.change_percent)}</dd></div></dl><ScopeWarning data={data} /><ComparisonDates data={data} /><ComparisonNotes data={data} /><div className="form-actions"><Link to={`/assets/months/${month}`}>이 달 기록 확인</Link><Link to="/assets">자산 관리</Link></div></details><Link className="button-link" to={`/assets/compare?to=${month}`} aria-label="월간 비교 자세히 보기">월간 비교 <Icon name="arrow-right" size={14} /></Link></div>
  </>}</>;

}
export function HomeAssetSummary() {
  const { state } = useAuth(); const { month } = useMonth();
  return <section className="card home-assets" aria-labelledby="assets-title"><div className="section-title"><div><p className="eyebrow">월간 기록 · {formatMonth(month)}</p><h2 id="assets-title">자산의 변화</h2></div><span className="section-icon"><Icon name="assets" size={22} /></span></div>
    {state.status === "authenticated" ? <CurrentAssetSummary /> : state.status === "loading" ? <p role="status">로그인 상태를 확인하고 있어요.</p> : <><p className="empty-value" aria-label="로그인 후 자산 기록 확인">—</p><p>로그인하면 우리 가계의 월간 자산 변화를 확인할 수 있어요.</p><Link to="/login">로그인하기</Link></>}
    {state.status !== "authenticated" && <div className="form-actions home-card-actions"><Link className="button-link" to={`/assets/compare?to=${month}`} aria-label="월간 비교 자세히 보기">월간 비교 <Icon name="arrow-right" size={14} /></Link><Link to={`/assets/months/${month}`}>이 달 기록 확인</Link><Link to="/assets">자산 관리</Link></div>}
  </section>;
}
