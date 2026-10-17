import { useEffect, useState } from "react";
import { Link } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { formatMonth, useMonth } from "../../shared/MonthContext";
import { useAuth } from "../auth/AuthProvider";
import { useAssetComparisonApi } from "../assets/comparison/api";
import { ComparisonDates, ComparisonError, ComparisonNumbers, ComparisonStatus, PeriodLabels, ScopeWarning } from "../assets/comparison/ComparisonFeedback";
import { formatKrw } from "../assets/months/model";
import type { Comparison } from "../assets/comparison/model";
function CurrentAssetSummary() {
  const api = useAssetComparisonApi(); const { month } = useMonth(); const [data, setData] = useState<Comparison | null>(null); const [error, setError] = useState<ApiError | null>(null); const [loading, setLoading] = useState(true); const [retry, setRetry] = useState(0);
  useEffect(() => { const controller = new AbortController(); setData(null); setError(null); setLoading(true);
    void api.comparison({ to: month, limit: 1 }, controller.signal).then((value) => { if (!controller.signal.aborted) setData(value); }).catch((failure) => { if (!controller.signal.aborted) setError(toApiError(failure)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); }); return () => controller.abort();
  }, [api, month, retry]);
  return <><ComparisonError error={error} />{loading && <p role="status">월간 자산 변화를 불러오고 있어요.</p>}{error && <button type="button" onClick={() => setRetry((value) => value + 1)}>홈 자산 정보 다시 확인</button>}{data && <><PeriodLabels data={data} /><ComparisonStatus data={data} />{data.current.totals && <><p role="status">{data.current.totals.provisional ? "임시 합계" : "확인한 합계"} · 확인 {data.current.totals.verified_count}/{data.current.totals.item_count}개 · 미입력 {data.current.totals.missing_count}개 · 전월값 미확인 {data.current.totals.carried_count}개</p><dl className="metadata-grid"><div><dt>총자산</dt><dd>{formatKrw(data.current.totals.assets_krw)}</dd></div><div><dt>부채</dt><dd>{formatKrw(data.current.totals.liabilities_krw)}</dd></div></dl></>}<ComparisonNumbers data={data} /><ScopeWarning data={data} /><ComparisonDates data={data} /></>}</>;
}
export function HomeAssetSummary() {
  const { state } = useAuth(); const { month } = useMonth();
  return <section className="card" aria-labelledby="assets-title"><p className="eyebrow">월간 기록 · {formatMonth(month)}</p><h2 id="assets-title">자산의 변화</h2>
    {state.status === "authenticated" ? <CurrentAssetSummary /> : state.status === "loading" ? <p role="status">로그인 상태를 확인하고 있어요.</p> : <><p className="empty-value" aria-label="로그인 후 자산 기록 확인">—</p><p>로그인하면 우리 가계의 월간 자산 변화를 확인할 수 있어요.</p><Link to="/login">로그인하기</Link></>}
    <div className="form-actions"><Link className="button-link" to={`/assets/compare?to=${month}`}>월간 비교 자세히 보기</Link><Link to={`/assets/months/${month}`}>이 달 기록 확인</Link><Link to="/assets">자산 관리</Link></div>
  </section>;
}
