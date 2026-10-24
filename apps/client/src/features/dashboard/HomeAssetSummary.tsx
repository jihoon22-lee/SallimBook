import { useEffect, useId, useState } from "react";
import { Link } from "react-router";
import { Icon } from "../../shared/Icon";
import { ApiError, toApiError } from "../../platform/api";
import { formatMonth, useMonth } from "../../shared/MonthContext";
import { useAuth } from "../auth/AuthProvider";
import { useAssetComparisonApi } from "../assets/comparison/api";
import { useAssetsApi } from "../assets/api";
import {
  ComparisonDates,
  ComparisonError,
  ComparisonNotes,
  ComparisonStatus,
  PeriodLabels,
  ScopeWarning,
} from "../assets/comparison/ComparisonFeedback";
import { formatKrw, monthStates } from "../assets/months/model";
import {
  deltaSign,
  latestConfirmedMonth,
  monthsBefore,
  percentLabel,
  signedKrw,
} from "../assets/comparison/model";
import { DeltaText } from "../assets/comparison/ComparisonFeedback";
import type { Comparison } from "../assets/comparison/model";
type HomeAssetView = "month" | "confirmed";

type RecordAction = { to: string; label: string; primary: boolean };

/**
 * The month's record action: start, continue or view, or asset registration when the
 * household has no asset yet. A month that has not started has none.
 */
function useRecordAction(
  month: string,
  currentMonth: string,
  state: Comparison["current"]["state"] | null,
): RecordAction | null {
  const assets = useAssetsApi();
  const [hasAssets, setHasAssets] = useState<boolean | null>(null);
  useEffect(() => {
    setHasAssets(null);
    if (state !== "missing" || month > currentMonth) return;
    let active = true;
    // A failed check still offers the month record, where the asset list is shown again.
    void assets
      .list({ limit: 1 })
      .then((value) => active && setHasAssets(value.items.length > 0))
      .catch(() => active && setHasAssets(true));
    return () => {
      active = false;
    };
  }, [assets, state, month, currentMonth]);
  if (state === null || month > currentMonth) return null;
  const label = month === currentMonth ? "이번 달" : formatMonth(month);
  const to = `/assets/months/${month}`;
  if (state === "confirmed") return { to, label: `${label} 기록 보기`, primary: false };
  if (state === "draft" || state === "reopened")
    return { to, label: `${label} 기록 이어서 확인`, primary: true };
  if (hasAssets === null) return null;
  return hasAssets
    ? { to, label: `${label} 기록 시작`, primary: true }
    : { to: "/assets/new", label: "자산 등록", primary: true };
}

/** Sits in the card's title row so today's consumables stay above the 390px navigation. */
function HomeAssetViews({
  view,
  setView,
  hintId,
}: {
  view: HomeAssetView;
  setView: (view: HomeAssetView) => void;
  hintId: string;
}) {
  const { month, currentMonth } = useMonth();
  const views: [HomeAssetView, string][] = [
    ["month", month === currentMonth ? "이번 달" : formatMonth(month)],
    ["confirmed", "최근 확정 비교"],
  ];
  return (
    <div
      className="segmented-control"
      role="group"
      aria-label="자산 변화 보기"
      aria-describedby={hintId}
    >
      {views.map(([value, label]) => (
        <button
          key={value}
          type="button"
          aria-pressed={view === value}
          onClick={() => setView(value)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function CurrentAssetSummary({ view, hintId }: { view: HomeAssetView; hintId: string }) {
  const api = useAssetComparisonApi();
  const { month, currentMonth } = useMonth();
  const [data, setData] = useState<Comparison | null>(null);
  const [target, setTarget] = useState(month);
  const [noConfirmed, setNoConfirmed] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const end = month > currentMonth ? currentMonth : month;
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    setNoConfirmed(false);
    setLoading(true);
    void (async () => {
      let to = month;
      if (view === "confirmed") {
        // Server values only: the client picks the month by state and never computes a delta.
        const trend = await api.trend({ from: monthsBefore(end, 23), to: end }, controller.signal);
        const confirmed = latestConfirmedMonth(trend.points);
        if (confirmed === null) {
          if (!controller.signal.aborted) setNoConfirmed(true);
          return;
        }
        to = confirmed;
      }
      const value = await api.comparison({ to, limit: 1 }, controller.signal);
      if (!controller.signal.aborted) {
        setTarget(to);
        setData(value);
      }
    })()
      .catch((failure) => {
        if (!controller.signal.aborted) setError(toApiError(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [api, month, end, view, retry]);
  const monthLabel = month === currentMonth ? "이번 달" : formatMonth(month);
  const action = useRecordAction(
    month,
    currentMonth,
    view === "month" && data ? data.current.state : null,
  );
  const compare = (className?: string) => (
    <Link
      className={className}
      to={`/assets/compare?to=${target}`}
      aria-label="월간 비교 자세히 보기"
    >
      월간 비교 <Icon name="arrow-right" size={14} />
    </Link>
  );
  const totals = data?.current.totals;
  const periods = data ? [data.previous, data.current].filter((period) => period !== null) : [];
  const dateCaution = periods.some((period) => period.dates.missing_date_asset_ids.length > 0)
    ? "기준일 미입력"
    : periods.some((period) => period.dates.mixed_dates)
      ? "서로 다른 기준일"
      : periods.some((period) => period.dates.non_month_end_asset_ids.length > 0)
        ? "월말 외 기준일"
        : null;
  // The 390px home keeps today's consumables above the navigation, so the hint for an
  // unconfirmed month stays in the change line instead of a paragraph of its own.
  const unconfirmedMonth = view === "month" && data?.state === "unconfirmed";
  // The shown month can be confirmed already while only the month before it is still open.
  const onlyPreviousOpen = unconfirmedMonth && data?.current.state === "confirmed";
  const previousOpen = data?.previous?.state === "draft" || data?.previous?.state === "reopened";
  const recordAction =
    onlyPreviousOpen && data?.previous
      ? { to: `/assets/months/${data.previous.month}`, label: "전월 기록 확인", primary: true }
      : action;
  const recordPrimary = Boolean(
    recordAction && (recordAction.primary || data?.state !== "available"),
  );
  return (
    <>
      {unconfirmedMonth && (
        <span className="sr-only" id={hintId}>
          {onlyPreviousOpen
            ? "전월 기록을 확정하면 비교해요."
            : `${monthLabel} 기록을 확정하면 전월과 비교해요.`}{" "}
          확정된 비교는 &apos;최근 확정 비교&apos;에서 볼 수 있어요.
        </span>
      )}
      <ComparisonError error={error} />
      {loading && (
        <p className="loading-state" role="status">
          월간 자산 변화를 불러오고 있어요.
        </p>
      )}
      {error && (
        <button type="button" onClick={() => setRetry((value) => value + 1)}>
          홈 자산 정보 다시 확인
        </button>
      )}
      {noConfirmed && (
        <>
          <p className="muted">
            최근 24개월 안에 연속으로 확정한 두 달이 없어요. 두 달을 확정하면 여기에서 비교할 수
            있어요.
          </p>
          <div className="form-actions home-card-actions">
            <Link to={`/assets/months/${end}`}>{formatMonth(end)} 기록 확인</Link>
            <Link to="/assets">자산 관리</Link>
          </div>
        </>
      )}
      {!data && !noConfirmed && (
        <div className="form-actions home-card-actions">
          <Link
            className="button-link"
            to={`/assets/compare?to=${month}`}
            aria-label="월간 비교 자세히 보기"
          >
            월간 비교 <Icon name="arrow-right" size={14} />
          </Link>
          <Link to={`/assets/months/${month}`}>이 달 기록 확인</Link>
          <Link to="/assets">자산 관리</Link>
        </div>
      )}
      {data && (
        <>
          {view === "confirmed" && (
            <p className="muted">
              {formatMonth(data.from_month ?? monthsBefore(target, 1))} → {formatMonth(target)} 확정
              기록 비교
            </p>
          )}
          <div className="asset-hero">
            <span className="metric-label">
              {totals?.provisional
                ? `임시 순자산 · 미확인 ${totals.missing_count + totals.carried_count}개`
                : "확인 월 순자산"}
            </span>
            <strong className="asset-hero-value">
              {!totals
                ? "월 기록 없음"
                : totals.net_assets_krw === null
                  ? "금액 확인 필요"
                  : formatKrw(totals.net_assets_krw)}
            </strong>
            <div className="asset-hero-change">
              <span>전체 순자산 변화</span>
              <strong className="money-delta" data-sign={deltaSign(data.total_delta_krw)}>
                {data.total_delta_krw !== null
                  ? signedKrw(data.total_delta_krw)
                  : unconfirmedMonth
                    ? onlyPreviousOpen
                      ? "전월 확정 후 비교"
                      : "확정 후 비교"
                    : "비교할 수 없음"}
              </strong>
            </div>
          </div>
          {totals && (
            <>
              <dl className="asset-mini-totals">
                <div>
                  <dt>총자산</dt>
                  <dd>{formatKrw(totals.assets_krw)}</dd>
                </div>
                <div>
                  <dt>부채</dt>
                  <dd>{formatKrw(totals.liabilities_krw)}</dd>
                </div>
              </dl>
              <p className="snapshot-check" role="status">
                {totals.provisional ? "임시 합계" : "확인한 합계"} · 확인 {totals.verified_count}/
                {totals.item_count}개 · 미입력 {totals.missing_count}개 · 전월값 미확인{" "}
                {totals.carried_count}개
              </p>
            </>
          )}
          <div className="snapshot-notices">
            {(data.current.state === "draft" || data.current.state === "reopened") && (
              <span className="notice-badge">확인 월 {monthStates[data.current.state]}</span>
            )}
            {data.state !== "available" && (
              <span className="notice-badge">
                {data.state === "current_missing"
                  ? "확인 월 기록 없음"
                  : data.state === "no_previous_month"
                    ? "이전 월 기록 없음"
                    : "미확정 월 · 증감 미계산"}
              </span>
            )}
            {data.scope_changed && <span className="notice-badge">비교 대상·지분 변경</span>}
            {previousOpen && !onlyPreviousOpen && (
              <span className="notice-badge">전월도 미확정</span>
            )}
            {dateCaution && <span className="notice-badge">{dateCaution}</span>}
          </div>
          <div className="asset-detail-actions">
            <details className="home-detail">
              <summary>비교 기준과 상세 금액</summary>
              <PeriodLabels data={data} />
              <ComparisonStatus data={data} />
              <dl className="metadata-grid">
                <div>
                  <dt>이전 비교월 순자산</dt>
                  <dd>
                    {data.previous?.totals
                      ? data.previous.totals.net_assets_krw === null
                        ? "금액 확인 필요"
                        : formatKrw(data.previous.totals.net_assets_krw)
                      : "월 기록 없음"}
                  </dd>
                </div>
                <div>
                  <dt>동일 범위 변화</dt>
                  <dd>
                    <DeltaText
                      value={data.common_scope_delta_krw}
                      text={
                        data.common_scope_delta_krw === null
                          ? "비교할 수 없음"
                          : signedKrw(data.common_scope_delta_krw)
                      }
                    />
                  </dd>
                </div>
                <div>
                  <dt>순자산 증감률</dt>
                  <dd>
                    <DeltaText
                      value={data.change_percent}
                      text={percentLabel(data.change_percent)}
                    />
                  </dd>
                </div>
              </dl>
              <ScopeWarning data={data} />
              <ComparisonDates data={data} />
              <ComparisonNotes data={data} />
              {/* One primary action stays beside the summary; the others live here. */}
              <div className="form-actions">
                {recordAction && !recordPrimary && (
                  <Link to={recordAction.to}>{recordAction.label}</Link>
                )}
                {recordPrimary && compare()}
                {previousOpen && !onlyPreviousOpen && data.previous && (
                  <Link to={`/assets/months/${data.previous.month}`}>전월 기록 확인</Link>
                )}
              </div>
            </details>
            {recordPrimary && recordAction ? (
              <Link className="button-link" to={recordAction.to}>
                {recordAction.label}
              </Link>
            ) : (
              compare("button-link")
            )}
          </div>
        </>
      )}
    </>
  );
}
export function HomeAssetSummary() {
  const { state } = useAuth();
  const { month } = useMonth();
  // Component state only: reopening home starts again at the selected month.
  const [view, setView] = useState<HomeAssetView>("month");
  const hintId = useId();
  const authenticated = state.status === "authenticated";
  return (
    <section className="card home-assets" aria-labelledby="assets-title">
      <div className="section-title">
        <div>
          <p className="eyebrow">
            {authenticated ? "월간 기록" : `월간 기록 · ${formatMonth(month)}`}
          </p>
          <h2 id="assets-title">자산의 변화</h2>
        </div>
        {authenticated ? (
          <HomeAssetViews view={view} setView={setView} hintId={hintId} />
        ) : (
          <span className="section-icon">
            <Icon name="assets" size={22} />
          </span>
        )}
      </div>
      {authenticated ? (
        <CurrentAssetSummary view={view} hintId={hintId} />
      ) : state.status === "loading" ? (
        <p role="status">로그인 상태를 확인하고 있어요.</p>
      ) : (
        <>
          <p className="empty-value" aria-label="로그인 후 자산 기록 확인">
            —
          </p>
          <p>로그인하면 우리 가계의 월간 자산 변화를 확인할 수 있어요.</p>
          <Link to="/login">로그인하기</Link>
        </>
      )}
      {state.status !== "authenticated" && (
        <div className="form-actions home-card-actions">
          <Link
            className="button-link"
            to={`/assets/compare?to=${month}`}
            aria-label="월간 비교 자세히 보기"
          >
            월간 비교 <Icon name="arrow-right" size={14} />
          </Link>
          <Link to={`/assets/months/${month}`}>이 달 기록 확인</Link>
          <Link to="/assets">자산 관리</Link>
        </div>
      )}
    </section>
  );
}
