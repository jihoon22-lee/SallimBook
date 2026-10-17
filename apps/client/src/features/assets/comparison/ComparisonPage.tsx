import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ApiError, toApiError } from "../../../platform/api";
import { isNativeAuth } from "../../../platform/nativeAuth";
import { formatMonth, isValidMonth, useMonth } from "../../../shared/MonthContext";
import { SessionStatus } from "../../auth/AuthFeedback";
import { useAuth } from "../../auth/AuthProvider";
import { dateLabel, isUuid, MemberLoadError, useHouseholdMembers } from "../../finance/FinanceSupport";
import type { HouseholdMember } from "../../finance/FinanceSupport";
import { amountBases, assetKinds, categories, shareToPercent } from "../model";
import { formatKrw, previousMonth, verificationStates } from "../months/model";
import type { MonthValue } from "../months/model";
import { snapshotOwner } from "../months/ScopeChanges";
import { useAssetComparisonApi } from "./api";
import { ComparisonDates, ComparisonError, ComparisonNumbers, ComparisonStatus, PeriodLabels, ScopeWarning } from "./ComparisonFeedback";
import { scopeReasons, signedKrw } from "./model";
import type { Comparison, ComparisonFilters, ComparisonItem, ComparisonQuery } from "./model";
import { TrendPanel } from "./TrendPanel";

export function SnapshotObservation({ row, members }: { row: MonthValue | null; members: HouseholdMember[] }) {
  return row ? <dl className="metadata-grid observation-grid"><div><dt>당시 이름</dt><dd>{row.name}</dd></div><div><dt>가계 보유금액</dt><dd>{formatKrw(row.owned_amount_krw)}</dd></div><div><dt>입력 금액</dt><dd>{formatKrw(row.input_amount_krw)}</dd></div><div><dt>기준일</dt><dd>{dateLabel(row.as_of_date)}</dd></div><div><dt>확인 상태</dt><dd>{verificationStates[row.verification_state]}</dd></div><div><dt>당시 소유 관계</dt><dd>{snapshotOwner(row, members)}</dd></div><div><dt>당시 분류</dt><dd>{assetKinds[row.kind]} · {categories[row.category]}</dd></div><div><dt>당시 지분·금액 기준</dt><dd>{shareToPercent(row.household_share)}% · {amountBases[row.amount_basis]}</dd></div><div><dt>합계 반영</dt><dd>{row.inclusion_status === "included" ? "합계 포함" : "합계 제외"}</dd></div>{row.change_reason && <div><dt>값 변경 사유</dt><dd>{row.change_reason}</dd></div>}</dl> : <p>이 달의 항목이 없어요. 0원으로 입력한 기록과 달라요.</p>;
}
export function ComparisonItemCard({ item, data, members }: { item: ComparisonItem; data: Comparison; members: HouseholdMember[] }) {
  const name = item.after?.name ?? item.before?.name ?? "자산 항목";
  return <li className="card comparison-item"><div className="item-heading"><h3><Link to={`/assets/${item.asset_id}`}>{name}</Link></h3><span className="status-chip">{item.membership === "added" ? "범위 추가" : item.membership === "removed" ? "범위 제외" : item.membership === "excluded" ? "참고 항목" : item.membership === "unavailable" ? "비교 대기" : item.share_changed ? "지분 변경" : "같은 비교 대상"}</span></div>
    {item.scope_reason && <p className="month-warning">{scopeReasons[item.scope_reason]}</p>}
    <dl className="metadata-grid"><div><dt>항목 보유금액 변화</dt><dd>{item.amount_delta_krw === null ? "비교할 수 없음" : signedKrw(item.amount_delta_krw)}</dd></div><div><dt>순자산에 반영된 변화</dt><dd>{item.net_assets_effect_krw === null ? "비교할 수 없음" : signedKrw(item.net_assets_effect_krw)}</dd></div></dl>
    {item.membership === "added" || item.membership === "removed" ? <p className="muted">범위의 포함·제외에 따른 영향이에요. 신규 저축이나 소비 금액으로 추정하지 않아요.</p> : item.before?.kind === "liability" && <p className="muted">부채 잔액 감소는 순자산에 반대로 반영돼요.</p>}
    <div className="comparison-observations"><section><h4>{data.from_month ? formatMonth(data.from_month) : "이전 비교월 없음"}</h4><SnapshotObservation row={item.before} members={members} /></section><section><h4>{formatMonth(data.to_month)}</h4><SnapshotObservation row={item.after} members={members} /></section></div>
  </li>;
}

function ComparisonWorkspace() {
  const api = useAssetComparisonApi(); const members = useHouseholdMembers(); const { month, setMonth } = useMonth(); const [params, setParams] = useSearchParams(); const pending = useRef(params);
  useEffect(() => { pending.current = params; }, [params]);
  const to = params.get("to") ?? month; const from = params.get("from") ?? (isValidMonth(to) ? previousMonth(to) : null);
  const kind = Object.hasOwn(assetKinds, params.get("kind") ?? "") ? params.get("kind")! : "";
  const category = Object.hasOwn(categories, params.get("category") ?? "") ? params.get("category")! : "";
  const owner = params.get("owner") === "joint" || isUuid(params.get("owner") ?? "") ? params.get("owner")! : "";
  const assetId = params.get("asset_id") ?? "";
  const valid = isValidMonth(to) && (from === null || (isValidMonth(from) && from < to)) && (!assetId || isUuid(assetId));
  useEffect(() => { if (isValidMonth(to)) setMonth(to); }, [to, setMonth]);
  const filters = useMemo<ComparisonFilters>(() => ({ ...(kind ? { kind: kind as ComparisonFilters["kind"] } : {}), ...(category ? { category: category as ComparisonFilters["category"] } : {}), ...(owner === "joint" ? { ownership_kind: "joint" as const } : owner ? { ownership_kind: "individual" as const, owner_member_id: owner } : {}), ...(assetId ? { asset_id: assetId } : {}) }), [kind, category, owner, assetId]);
  const query = useMemo<ComparisonQuery>(() => ({ ...filters, to, ...(from ? { from } : {}) }), [filters, to, from]);
  const [data, setData] = useState<Comparison | null>(null); const [error, setError] = useState<ApiError | null>(null); const [loading, setLoading] = useState(true); const [retry, setRetry] = useState(0);
  useEffect(() => { const controller = new AbortController(); setData(null); setError(null); setLoading(valid);
    if (!valid) return;
    void api.all(query, controller.signal).then((result) => { if (!controller.signal.aborted) setData(result); }).catch((failure) => { if (!controller.signal.aborted) setError(toApiError(failure)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); }); return () => controller.abort();
  }, [api, query, valid, retry]);
  function filter(name: string, value: string) { const next = new URLSearchParams(pending.current); if (value) next.set(name, value); else next.delete(name); pending.current = next; setParams(next); }
  return <><section className="card finance-filters" aria-labelledby="comparison-filter-title"><h2 id="comparison-filter-title">비교할 월과 대상</h2><div className="filter-grid">
    <div className="form-field"><label htmlFor="comparison-to">확인할 월</label><input id="comparison-to" type="month" min="0001-01" max="9999-12" value={to} onChange={(event) => { if (isValidMonth(event.target.value)) filter("to", event.target.value); }} /></div>
    <div className="form-field"><label htmlFor="comparison-from">비교할 이전 월</label><input id="comparison-from" type="month" min="0001-01" max={previousMonth(to) ?? undefined} value={from ?? ""} disabled={to === "0001-01"} onChange={(event) => { if (isValidMonth(event.target.value)) filter("from", event.target.value); }} /></div>
    <div className="form-field"><label htmlFor="comparison-kind">비교 자산·부채 필터</label><select id="comparison-kind" value={kind} onChange={(event) => filter("kind", event.target.value)}><option value="">자산·부채 모두</option>{Object.entries(assetKinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div>
    <div className="form-field"><label htmlFor="comparison-category">비교 분류 필터</label><select id="comparison-category" value={category} onChange={(event) => filter("category", event.target.value)}><option value="">모든 분류</option>{Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div>
    <div className="form-field"><label htmlFor="comparison-owner">비교 소유자 필터</label><select id="comparison-owner" value={owner} onChange={(event) => filter("owner", event.target.value)}><option value="">모든 소유자</option><option value="joint">공동 소유</option>{members.members.map((member) => <option key={member.member_id} value={member.member_id}>{member.display_name}</option>)}</select></div>
    </div><p className="muted">필터는 각 월 당시의 소유 관계와 분류에 적용돼요. 가계 지분을 중복해서 곱하지 않아요.</p>{assetId && <p>선택한 자산 한 건을 비교하고 있어요.</p>}
    <MemberLoadError error={members.error} retry={members.retry} /><div className="form-actions"><button type="button" onClick={() => { pending.current = new URLSearchParams({ to }); setParams(pending.current); }}>비교 필터 초기화</button><button type="button" disabled={loading || !valid} onClick={() => setRetry((value) => value + 1)}>비교 다시 불러오기</button></div></section>
    {!valid && <p role="alert">올바른 월과 자산을 선택해 주세요. 이전 비교월은 확인할 월보다 앞서야 해요.</p>}
    <ComparisonError error={error} />{loading && <p role="status">월별 자산을 비교하고 있어요.</p>}
    {data && <><section className="card" aria-labelledby="comparison-summary-title"><h2 id="comparison-summary-title">월간 자산 변화</h2><PeriodLabels data={data} /><ComparisonStatus data={data} /><ComparisonNumbers data={data} /><ScopeWarning data={data} /><ComparisonDates data={data} /><div className="form-actions"><Link to={`/assets/months/${to}`}>확인 월 기록</Link>{from && <Link to={`/assets/months/${from}`}>이전 비교월 기록</Link>}</div></section>
      <section aria-labelledby="comparison-items-title"><h2 id="comparison-items-title">항목별 변화</h2><p className="muted">금액과 기준일은 각 월 기록의 값이에요. 현재 자산 기본정보로 과거 기록을 바꾸지 않아요.</p>{data.items.length === 0 ? <p>선택한 비교 범위에 항목이 없어요.</p> : <ul className="finance-list">{data.items.map((item) => <ComparisonItemCard key={item.asset_id} item={item} data={data} members={members.members} />)}</ul>}</section>
    </>}
    {data && <TrendPanel to={to} filters={filters} comparison={data} refreshComparison={() => setRetry((value) => value + 1)} title="선택한 범위의 순자산 추이" />}
  </>;
}
export function AssetComparisonPage() {
  const { state } = useAuth(); const { month } = useMonth();
  return <><div className="intro"><p className="eyebrow">기록한 금액의 변화</p><h1>월간 자산 비교</h1><p>전체 변화와 같은 비교 대상의 변화를 나눠 확인해요.</p></div>{state.status !== "authenticated" ? <><p>{formatMonth(month)} · 서울 기준</p><SessionStatus /></> : isNativeAuth() ? <section className="card"><h2>앱의 비교 연결 준비 중</h2><p>검증된 네이티브 비교 연결을 준비하고 있어요. 웹에서 월간 비교를 확인할 수 있어요.</p></section> : <ComparisonWorkspace />}</>;
}
