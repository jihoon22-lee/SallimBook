import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { MonthPicker, useMonth, formatMonth } from "../../shared/MonthContext";
import { SessionStatus, useMounted } from "../auth/AuthFeedback";
import { useAuth } from "../auth/AuthProvider";
import { dateLabel, FinanceError, isDateOnly, isUuid, MemberLoadError, MissingAmount, todaySeoul, useHouseholdMembers } from "../finance/FinanceSupport";
import type { HouseholdMember } from "../finance/FinanceSupport";
import { AssetEditor } from "./AssetEditor";
import { useAssetsApi } from "./api";
import { amountBases, assetKinds, categories, shareToPercent } from "./model";
import type { Asset, AssetQuery } from "./model";

export function ownerLabel(asset: Asset, members: HouseholdMember[]): string {
  return asset.ownership_kind === "joint" ? "공동 소유" : members.find((member) => member.member_id === asset.owner_member_id)?.display_name ?? "구성원 확인 필요";
}

export function AssetSummary({ asset, members }: { asset: Asset; members: HouseholdMember[] }) {
  return <dl className="metadata-grid">
    <div><dt>구분·분류</dt><dd>{assetKinds[asset.kind]} · {categories[asset.category]}</dd></div>
    <div><dt>소유자</dt><dd>{ownerLabel(asset, members)}</dd></div>
    <div><dt>가계 지분</dt><dd>{shareToPercent(asset.household_share ?? "1")}%</dd></div>
    <div><dt>금액 기준</dt><dd>{amountBases[asset.amount_basis]}</dd></div>
    <div><dt>합계 반영</dt><dd>{asset.inclusion_status === "excluded" ? "합계에서 제외" : "합계에 포함"}</dd></div>
    <div><dt>등록 상태</dt><dd>{asset.status === "archived" ? "사용 종료" : "사용 중"}</dd></div>
    <div><dt>보유 시작일</dt><dd>{dateLabel(asset.started_on)}</dd></div>
    <div><dt>보유 종료일</dt><dd>{dateLabel(asset.ended_on ?? null)}</dd></div>
  </dl>;
}

function AssetList() {
  const api = useAssetsApi();
  const members = useHouseholdMembers();
  const mounted = useMounted();
  const [params, setParams] = useSearchParams();
  const pendingParams = useRef(params);
  useEffect(() => { pendingParams.current = params; }, [params]);
  const [items, setItems] = useState<Asset[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const generation = useRef(0);
  const kind = ["asset", "liability"].includes(params.get("kind") ?? "") ? params.get("kind")! : "";
  const category = Object.hasOwn(categories, params.get("category") ?? "") ? params.get("category")! : "";
  const owner = params.get("owner") ?? "";
  const inclusion = ["included", "excluded"].includes(params.get("inclusion") ?? "") ? params.get("inclusion")! : "";
  const status = ["active", "archived", "all"].includes(params.get("status") ?? "") ? params.get("status")! : "active";
  const query = useMemo<AssetQuery>(() => ({ limit: 50, status: status as AssetQuery["status"],
    ...(kind ? { kind: kind as AssetQuery["kind"] } : {}), ...(category ? { category: category as AssetQuery["category"] } : {}),
    ...(owner === "joint" ? { ownership_kind: "joint" as const } : isUuid(owner) ? { ownership_kind: "individual" as const, owner_member_id: owner } : {}),
    ...(inclusion ? { inclusion_status: inclusion as AssetQuery["inclusion_status"] } : {}) }), [kind, category, owner, inclusion, status]);
  const load = useCallback(async (after?: string) => {
    const requestGeneration = ++generation.current;
    setLoading(true); setError(null);
    if (!after) { setItems([]); setCursor(null); }
    try {
      const response = await api.list({ ...query, ...(after ? { cursor: after } : {}) });
      if (!mounted.current || generation.current !== requestGeneration) return;
      setItems((old) => after ? [...old, ...response.items.filter((item) => !old.some((existing) => existing.id === item.id))] : response.items);
      setCursor(response.next_cursor);
    } catch (failure) { if (mounted.current && generation.current === requestGeneration) setError(toApiError(failure)); }
    finally { if (mounted.current && generation.current === requestGeneration) setLoading(false); }
  }, [api, query, mounted]);
  useEffect(() => { void load(); return () => { generation.current++; }; }, [load]);
  function filter(name: string, value: string) { const next = new URLSearchParams(pendingParams.current); if (value) next.set(name, value); else next.delete(name); pendingParams.current = next; setParams(next); }

  return <>
    <div className="form-actions"><Link className="button-link" to="/assets/new">자산·부채 등록</Link><Link className="button-link secondary-button" to="/accounts">계좌 관리</Link></div>
    <section className="card finance-filters" aria-labelledby="asset-filter-title"><h2 id="asset-filter-title">자산 찾기</h2><p className="muted">기본정보 목록은 현재 등록 상태를 기준으로 보여줘요. 월별 금액과는 별개예요.</p>
      <div className="filter-grid">
        <div className="form-field"><label htmlFor="asset-kind-filter">자산·부채 필터</label><select id="asset-kind-filter" value={kind} onChange={(event) => filter("kind", event.target.value)}><option value="">전체</option>{Object.entries(assetKinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div>
        <div className="form-field"><label htmlFor="asset-category-filter">분류 필터</label><select id="asset-category-filter" value={category} onChange={(event) => filter("category", event.target.value)}><option value="">전체 분류</option>{Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div>
        <div className="form-field"><label htmlFor="asset-owner-filter">소유자 필터</label><select id="asset-owner-filter" value={owner} onChange={(event) => filter("owner", event.target.value)}><option value="">전체 소유자</option><option value="joint">공동 소유</option>{members.members.map((member) => <option key={member.member_id} value={member.member_id}>{member.display_name}</option>)}</select></div>
        <div className="form-field"><label htmlFor="asset-inclusion-filter">합계 포함 필터</label><select id="asset-inclusion-filter" value={inclusion} onChange={(event) => filter("inclusion", event.target.value)}><option value="">포함·제외 모두</option><option value="included">합계에 포함</option><option value="excluded">합계에서 제외</option></select></div>
        <div className="form-field"><label htmlFor="asset-status-filter">등록 상태 필터</label><select id="asset-status-filter" value={status} onChange={(event) => filter("status", event.target.value)}><option value="active">사용 중</option><option value="archived">사용 종료</option><option value="all">모든 상태</option></select></div>
      </div>
      <MemberLoadError error={members.error} retry={members.retry} />
      <div className="form-actions"><button type="button" disabled={loading} onClick={() => void load()}>자산 목록 다시 불러오기</button><button type="button" className="secondary-button" onClick={() => { pendingParams.current = new URLSearchParams(); setParams({}); }}>필터 초기화</button></div>
    </section>
    <FinanceError error={error} />
    {loading && <p role="status">자산 목록을 불러오고 있어요.</p>}
    {!loading && !error && items.length === 0 && <section className="card"><h2>조건에 맞는 자산이 없어요</h2><p>필터를 바꾸거나 자산·부채를 등록해 주세요. 빈 목록을 0원 자산으로 표시하지 않아요.</p></section>}
    <ul className="finance-list">{items.map((asset) => <li key={asset.id} className="card"><div className="item-heading"><h2><Link to={`/assets/${asset.id}`}>{asset.name}</Link></h2><span className="status-chip">{asset.status === "archived" ? "사용 종료" : "사용 중"}</span></div><AssetSummary asset={asset} members={members.members} /><MissingAmount /></li>)}</ul>
    {cursor && <button type="button" disabled={loading} onClick={() => void load(cursor)}>자산 더 보기</button>}
  </>;
}

function useAsset(id: string) {
  const api = useAssetsApi();
  const [asset, setAsset] = useState<Asset | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setAsset(null); setError(null); setLoading(true);
    if (!isUuid(id)) { setError(new ApiError(404, "NOT_FOUND")); setLoading(false); return; }
    void api.get(id).then((value) => { if (active) setAsset(value); }).catch((failure) => { if (active) setError(toApiError(failure)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, api, retry]);
  return { asset, error, loading, setAsset, reload: () => setRetry((value) => value + 1) };
}

function AssetDetail({ id }: { id: string }) {
  const state = useAsset(id);
  const members = useHouseholdMembers();
  const api = useAssetsApi();
  const mounted = useMounted();
  const [closing, setClosing] = useState(false);
  const [endedOn, setEndedOn] = useState(todaySeoul);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [formError, setFormError] = useState("");
  const location = useLocation();
  async function archive(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!state.asset || busy) return;
    if (!isDateOnly(endedOn) || endedOn < state.asset.started_on) { setFormError("종료일은 보유 시작일 이후의 실제 날짜로 입력해 주세요."); return; }
    setBusy(true); setError(null); setFormError("");
    try { const result = await api.archive(id, { ended_on: endedOn, closure_ack: false }, state.asset.version); if (mounted.current) { state.setAsset(result); setClosing(false); } }
    catch (failure) { if (mounted.current) setError(toApiError(failure)); }
    finally { if (mounted.current) setBusy(false); }
  }
  if (state.loading) return <p role="status">자산 정보를 불러오고 있어요.</p>;
  if (!state.asset) return <><FinanceError error={state.error} /><div className="form-actions"><button type="button" onClick={state.reload}>자산 다시 확인</button><Link to="/assets">자산 목록</Link></div></>;
  const asset = state.asset;
  return <>
    {location.state?.saved && <p role="status">자산 정보를 저장했어요.</p>}
    <section className="card"><h2>{asset.name}</h2><AssetSummary asset={asset} members={members.members} /><MemberLoadError error={members.error} retry={members.retry} />
      {asset.note && <div className="plain-note"><h3>메모</h3><p>{asset.note}</p></div>}<MissingAmount monthLink />
      <div className="form-actions"><Link className="button-link" to={`/assets/${id}/edit`}>자산 정보 수정</Link>{asset.status === "active" && <button type="button" className="secondary-button" onClick={() => { setError(null); setClosing(true); }}>사용 종료하기</button>}<Link className="button-link secondary-button" to="/assets">자산 목록</Link></div>
    </section>
    {closing && <section className="card" aria-labelledby="asset-archive-title"><h2 id="asset-archive-title">자산 사용 종료</h2><p>자산 항목과 과거 연결 기록은 남겨두고 사용 종료 상태로 바꿔요.</p>
      <form className="finance-form" onSubmit={(event) => void archive(event)}><div className="form-field"><label htmlFor="asset-ended-on">종료일</label><input id="asset-ended-on" type="date" value={endedOn} onChange={(event) => setEndedOn(event.target.value)} min={asset.started_on} max="9999-12-31" required disabled={busy} /></div>
        {formError && <p role="alert">{formError}</p>}<FinanceError error={error} />
        {error?.code === "VERSION_CONFLICT" && <button type="button" onClick={() => { setError(null); state.reload(); }}>최신 자산 정보 다시 확인</button>}
        <div className="form-actions"><button type="submit" disabled={busy || error?.code === "VERSION_CONFLICT"}>{busy ? "종료 처리 중…" : "사용 종료 확인"}</button><button type="button" className="secondary-button" disabled={busy} onClick={() => setClosing(false)}>종료 취소</button></div>
      </form>
    </section>}
  </>;
}

function AssetEdit({ id }: { id: string }) {
  const state = useAsset(id);
  if (state.loading) return <p role="status">수정할 자산을 불러오고 있어요.</p>;
  return state.asset ? <AssetEditor key={state.asset.id} initial={state.asset} /> : <><FinanceError error={state.error} /><button type="button" onClick={state.reload}>자산 다시 확인</button></>;
}

export function AssetListPage() {
  const { state } = useAuth();
  const { month } = useMonth();
  return <><div className="intro"><p className="eyebrow">우리 집의 기본정보</p><h1>자산과 부채</h1><p>소유자와 지분, 보유 기간을 함께 관리해요.</p></div><MonthPicker /><p className="month-action"><Link to={`/assets/months/${month}`}>{formatMonth(month)} 월 기록 확인</Link></p>{state.status === "authenticated" ? <AssetList /> : <SessionStatus />}</>;
}
export function AssetNewPage() {
  const { state } = useAuth();
  return <><div className="intro"><p className="eyebrow">우리 집의 기본정보</p><h1>자산·부채 등록</h1><p>같은 공동 자산은 한 번만 등록해요. 금액은 월별로 별도 확인해야 해요.</p></div>{state.status === "authenticated" ? <AssetEditor /> : <SessionStatus />}</>;
}
export function AssetDetailPage({ edit = false }: { edit?: boolean }) {
  const { state } = useAuth();
  const { id = "" } = useParams();
  return <><div className="intro"><p className="eyebrow">우리 집의 기본정보</p><h1>{edit ? "자산 정보 수정" : "자산 상세"}</h1></div>{state.status === "authenticated" ? edit ? <AssetEdit key={id} id={id} /> : <AssetDetail key={id} id={id} /> : <SessionStatus />}</>;
}
