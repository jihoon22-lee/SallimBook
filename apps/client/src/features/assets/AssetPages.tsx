import { LastModified } from "../../shared/RecordActor";
import { NameSearch } from "../../shared/NameSearch";
import { TaskPanel } from "../../shared/TaskLayout";
import { AssetAccountLink } from "../finance/RelatedRecords";
import { DateInput } from "../../shared/DateInput";
import { Icon } from "../../shared/Icon";
import { DocumentPanel } from "../documents/DocumentPanel";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { stateFlag, useRouteNotice } from "../../shared/routeNotice";
import { ApiError, toApiError } from "../../platform/api";
import { MonthPicker, useMonth, formatMonth } from "../../shared/MonthContext";
import { SessionStatus, useMounted } from "../auth/AuthFeedback";
import { useAuth } from "../auth/AuthProvider";
import {
  dateLabel,
  FinanceError,
  isDateOnly,
  isUuid,
  MemberLoadError,
  MissingAmount,
  todaySeoul,
  useHouseholdMembers,
} from "../finance/FinanceSupport";
import type { HouseholdMember } from "../finance/FinanceSupport";
import { ClosureReview, useAssetClosure } from "../finance/PaymentLinks";
import { AssetMonthlyData } from "./comparison/AssetMonthlyData";
import { AssetEditor } from "./AssetEditor";
import { futureEndMessage, StoredFutureEnd } from "./AssetFields";
import { MisregistrationDelete } from "./MisregistrationDelete";
import { useAssetsApi } from "./api";
import { amountBases, assetKinds, categories, shareToPercent } from "./model";
import type { Asset, AssetQuery } from "./model";
import { usePagedList } from "../finance/queries";

export function ownerLabel(asset: Asset, members: HouseholdMember[]): string {
  return asset.ownership_kind === "joint"
    ? "공동 소유"
    : (members.find((member) => member.member_id === asset.owner_member_id)?.display_name ??
        "구성원 확인 필요");
}

export function AssetSummary({ asset, members }: { asset: Asset; members: HouseholdMember[] }) {
  return (
    <dl className="metadata-grid">
      <div>
        <dt>구분·분류</dt>
        <dd>
          {assetKinds[asset.kind]} · {categories[asset.category]}
        </dd>
      </div>
      <div>
        <dt>소유자</dt>
        <dd>{ownerLabel(asset, members)}</dd>
      </div>
      <div>
        <dt>가계 지분</dt>
        <dd>{shareToPercent(asset.household_share ?? "1")}%</dd>
      </div>
      <div>
        <dt>금액 기준</dt>
        <dd>{amountBases[asset.amount_basis]}</dd>
      </div>
      <div>
        <dt>합계 반영</dt>
        <dd>{asset.inclusion_status === "excluded" ? "합계에서 제외" : "합계에 포함"}</dd>
      </div>
      <div>
        <dt>등록 상태</dt>
        <dd>{asset.status === "archived" ? "사용 종료" : "사용 중"}</dd>
      </div>
      <div>
        <dt>보유 시작일</dt>
        <dd>{dateLabel(asset.started_on)}</dd>
      </div>
      <div>
        <dt>보유 종료일</dt>
        <dd>{dateLabel(asset.ended_on ?? null)}</dd>
      </div>
      <LastModified record={asset} />
    </dl>
  );
}

function AssetList() {
  const api = useAssetsApi();
  const members = useHouseholdMembers();
  const [params, setParams] = useSearchParams();
  const pendingParams = useRef(params);
  useEffect(() => {
    pendingParams.current = params;
  }, [params]);
  const kind = ["asset", "liability"].includes(params.get("kind") ?? "") ? params.get("kind")! : "";
  const category = Object.hasOwn(categories, params.get("category") ?? "")
    ? params.get("category")!
    : "";
  const owner = params.get("owner") ?? "";
  const inclusion = ["included", "excluded"].includes(params.get("inclusion") ?? "")
    ? params.get("inclusion")!
    : "";
  const status = ["active", "archived", "all"].includes(params.get("status") ?? "")
    ? params.get("status")!
    : "active";
  const q = params.get("q") ?? "";
  const query = useMemo<AssetQuery>(
    () => ({
      limit: 50,
      ...(q ? { q } : {}),
      status: status as AssetQuery["status"],
      ...(kind ? { kind: kind as AssetQuery["kind"] } : {}),
      ...(category ? { category: category as AssetQuery["category"] } : {}),
      ...(owner === "joint"
        ? { ownership_kind: "joint" as const }
        : isUuid(owner)
          ? { ownership_kind: "individual" as const, owner_member_id: owner }
          : {}),
      ...(inclusion ? { inclusion_status: inclusion as AssetQuery["inclusion_status"] } : {}),
    }),
    [kind, category, owner, inclusion, status, q],
  );
  const { items, cursor, loading, error, reload, more } = usePagedList(
    useCallback(
      (after?: string) => api.list({ ...query, ...(after ? { cursor: after } : {}) }),
      [api, query],
    ),
    undefined,
    "assets",
  );
  function filter(name: string, value: string) {
    const next = new URLSearchParams(pendingParams.current);
    if (value) next.set(name, value);
    else next.delete(name);
    pendingParams.current = next;
    setParams(next);
  }

  const filterCount = [
    kind,
    category,
    owner === "joint" || isUuid(owner) ? owner : "",
    inclusion,
    status !== "active" ? status : "",
  ].filter(Boolean).length;
  return (
    <>
      <NameSearch label="자산·부채 이름 검색" />
      <div className="form-actions">
        <Link className="button-link" to="/assets/new">
          자산·부채 등록
        </Link>
        <Link className="button-link secondary-button" to="/accounts">
          계좌 관리
        </Link>
      </div>
      <details className="card finance-filters asset-filter-panel">
        <summary>
          <span>
            <Icon name="filter" size={17} /> 자산 찾기
          </span>
          <span className="muted">
            {filterCount ? `조건 ${filterCount}개 적용` : "사용 중 · 추가 조건 없음"}
          </span>
        </summary>
        <p className="muted">
          기본정보 목록은 현재 등록 상태를 기준으로 보여줘요. 월별 금액과는 별개예요.
        </p>
        <div className="filter-grid">
          <div className="form-field">
            <label htmlFor="asset-kind-filter">자산·부채 필터</label>
            <select
              id="asset-kind-filter"
              value={kind}
              onChange={(event) => filter("kind", event.target.value)}
            >
              <option value="">전체</option>
              {Object.entries(assetKinds).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="asset-category-filter">분류 필터</label>
            <select
              id="asset-category-filter"
              value={category}
              onChange={(event) => filter("category", event.target.value)}
            >
              <option value="">전체 분류</option>
              {Object.entries(categories).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="asset-owner-filter">소유자 필터</label>
            <select
              id="asset-owner-filter"
              value={owner}
              onChange={(event) => filter("owner", event.target.value)}
            >
              <option value="">전체 소유자</option>
              <option value="joint">공동 소유</option>
              {members.members.map((member) => (
                <option key={member.member_id} value={member.member_id}>
                  {member.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="asset-inclusion-filter">합계 포함 필터</label>
            <select
              id="asset-inclusion-filter"
              value={inclusion}
              onChange={(event) => filter("inclusion", event.target.value)}
            >
              <option value="">포함·제외 모두</option>
              <option value="included">합계에 포함</option>
              <option value="excluded">합계에서 제외</option>
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="asset-status-filter">등록 상태 필터</label>
            <select
              id="asset-status-filter"
              value={status}
              onChange={(event) => filter("status", event.target.value)}
            >
              <option value="active">사용 중</option>
              <option value="archived">사용 종료</option>
              <option value="all">모든 상태</option>
            </select>
          </div>
        </div>
        <div className="form-actions">
          <button type="button" disabled={loading} onClick={() => void reload()}>
            자산 목록 다시 불러오기
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              pendingParams.current = new URLSearchParams();
              setParams({});
            }}
          >
            필터 초기화
          </button>
        </div>
      </details>
      <MemberLoadError error={members.error} retry={members.retry} />
      <FinanceError error={error} />
      {error && (
        <button type="button" onClick={() => void reload()}>
          자산 목록 다시 불러오기
        </button>
      )}
      {loading && (
        <p className="loading-state" role="status">
          자산 목록을 불러오고 있어요.
        </p>
      )}
      {!loading && !error && items.length === 0 && (
        <section className="card empty-state">
          <span className="empty-state-icon">
            <Icon name="assets" size={25} />
          </span>
          <h2>조건에 맞는 자산이 없어요</h2>
          <p>필터를 바꾸거나 자산·부채를 등록해 주세요. 빈 목록을 0원 자산으로 표시하지 않아요.</p>
        </section>
      )}
      {items.length > 0 && (
        <div className="list-heading">
          <h2>등록된 자산·부채</h2>
          <span className="muted">불러온 항목 {items.length}개</span>
        </div>
      )}
      {items.length > 0 && <MissingAmount />}
      <ul className="finance-list asset-records">
        {items.map((asset) => (
          <li key={asset.id} className="card asset-record">
            <div className="item-heading">
              <div className="record-heading">
                <span className="record-icon">
                  <Icon name={asset.kind === "liability" ? "cashflow" : "assets"} />
                </span>
                <div>
                  <h2>
                    <Link to={`/assets/${asset.id}`}>{asset.name}</Link>
                  </h2>
                  <p className="record-subline">
                    {categories[asset.category]} · {ownerLabel(asset, members.members)}
                  </p>
                </div>
              </div>
              <span className="status-chip">
                {asset.status === "archived" ? "사용 종료" : "사용 중"}
              </span>
            </div>
            <details className="record-details">
              <summary>소유·지분·보유기간 자세히</summary>
              <AssetSummary asset={asset} members={members.members} />
            </details>
          </li>
        ))}
      </ul>
      {cursor && (
        <button type="button" disabled={loading} onClick={() => void more()}>
          자산 더 보기
        </button>
      )}
    </>
  );
}

function useAsset(id: string) {
  const api = useAssetsApi();
  const [asset, setAsset] = useState<Asset | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const loadedId = useRef(id);
  useEffect(() => {
    let active = true;
    if (loadedId.current !== id) {
      setAsset(null);
      loadedId.current = id;
    }
    setError(null);
    setLoading(true);
    if (!isUuid(id)) {
      setError(new ApiError(404, "NOT_FOUND"));
      setLoading(false);
      return;
    }
    void api
      .get(id)
      .then((value) => {
        if (active) setAsset(value);
      })
      .catch((failure) => {
        if (active) setError(toApiError(failure));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [id, api, retry]);
  return { asset, error, loading, setAsset, reload: () => setRetry((value) => value + 1) };
}

function AssetDetail({ id }: { id: string }) {
  const state = useAsset(id);
  const members = useHouseholdMembers();
  const api = useAssetsApi();
  const mounted = useMounted();
  const [closing, setClosing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const navigate = useNavigate();
  const [endedOn, setEndedOn] = useState(todaySeoul);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [formError, setFormError] = useState("");
  const saved = useRouteNotice(stateFlag("saved"));
  const closure = useAssetClosure(state.asset, endedOn, closing);
  async function archive(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!state.asset || busy || !closure.ready) return;
    if (!isDateOnly(endedOn) || endedOn < state.asset.started_on) {
      setFormError("종료일은 보유 시작일 이후의 실제 날짜로 입력해 주세요.");
      return;
    }
    if (endedOn > todaySeoul()) {
      setFormError(futureEndMessage);
      return;
    }
    setBusy(true);
    setError(null);
    setFormError("");
    try {
      const result = await api.archive(
        id,
        { ended_on: endedOn, ...closure.proof },
        state.asset.version,
      );
      if (mounted.current) {
        state.setAsset(result);
        setClosing(false);
      }
    } catch (failure) {
      if (mounted.current) {
        const error = toApiError(failure);
        setError(error);
        if (
          error.code === "PAYMENT_LINKS_CHANGED" ||
          error.code === "PAYMENT_LINK_CONFIRMATION_REQUIRED"
        )
          closure.refresh();
      }
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  if (state.loading && !state.asset) return <p role="status">자산 정보를 불러오고 있어요.</p>;
  if (!state.asset)
    return (
      <>
        <FinanceError error={state.error} />
        <div className="form-actions">
          <button type="button" onClick={state.reload}>
            자산 다시 확인
          </button>
          <Link to="/assets">자산 목록</Link>
        </div>
      </>
    );
  const asset = state.asset;
  return (
    <>
      {saved && <p role="status">자산 정보를 저장했어요.</p>}
      {state.loading && <p role="status">기존 내용을 유지하며 자산 정보를 다시 확인하고 있어요.</p>}
      <FinanceError error={state.error} />
      {state.error && (
        <button type="button" disabled={state.loading} onClick={state.reload}>
          자산 다시 확인
        </button>
      )}
      <section className="card">
        <h2>{asset.name}</h2>
        <AssetSummary asset={asset} members={members.members} />
        <MemberLoadError error={members.error} retry={members.retry} />
        {asset.ended_on && asset.ended_on > todaySeoul() && (
          <StoredFutureEnd to={`/assets/${id}/edit`} />
        )}
        {asset.note && (
          <div className="plain-note">
            <h3>메모</h3>
            <p>{asset.note}</p>
          </div>
        )}
        <div className="form-actions">
          <Link className="button-link" to={`/assets/${id}/edit`}>
            자산 정보 수정
          </Link>
          {asset.status === "active" && (
            <button
              type="button"
              className="secondary-button"
              onClick={() => {
                setError(null);
                setDeleting(false);
                setClosing(true);
              }}
            >
              사용 종료하기
            </button>
          )}
          <button
            type="button"
            className="danger-button"
            disabled={state.loading || Boolean(state.error)}
            onClick={() => {
              setError(null);
              setClosing(false);
              setDeleting(true);
            }}
          >
            오등록 삭제 검토
          </button>
          <Link className="button-link secondary-button" to="/assets">
            자산 목록
          </Link>
        </div>
      </section>
      {deleting && (
        <MisregistrationDelete
          id="asset-delete"
          title="오등록 자산 삭제 확인"
          ackLabel="잘못 등록한 자산이며 실제 삭제할 것을 확인했어요."
          actionLabel="오등록 자산 삭제"
          inUseCode="ASSET_IN_USE"
          remove={() => api.delete(asset.id, asset.version)}
          done={() => navigate("/assets", { replace: true, state: { deleted: "asset" } })}
          cancel={() => setDeleting(false)}
          reload={() => {
            setDeleting(false);
            state.reload();
          }}
        >
          <p>
            월 기록·계좌·납부 규칙·문서에 연결되지 않은 오등록 자산만 실제로 삭제할 수 있어요. 사용
            이력이 있으면 사용 종료를 이용해 주세요.
          </p>
          {asset.category === "financial" && (
            <p className="muted">
              계좌로 등록한 금융 자산은 계좌 상세에서 계좌와 함께 삭제할 수 있어요.
            </p>
          )}
        </MisregistrationDelete>
      )}
      <DocumentPanel kind="asset" id={id} />
      {asset.category === "financial" && <AssetAccountLink assetId={id} />}
      <AssetMonthlyData assetId={id} />
      {closing && (
        <TaskPanel label="자산 사용 종료">
          <h2 id="asset-archive-title">자산 사용 종료</h2>
          <p>자산 항목과 과거 연결 기록은 남겨두고 사용 종료 상태로 바꿔요.</p>
          <form className="finance-form" onSubmit={(event) => void archive(event)}>
            <div className="form-field">
              <label htmlFor="asset-ended-on">종료일</label>
              <DateInput
                id="asset-ended-on"
                value={endedOn}
                onChange={(event) => setEndedOn(event.target.value)}
                min={asset.started_on}
                max={todaySeoul()}
                required
                disabled={busy}
              />
            </div>
            {asset.category === "financial" && <ClosureReview review={closure} disabled={busy} />}
            {formError && <p role="alert">{formError}</p>}
            <FinanceError error={error} />
            {error?.code === "VERSION_CONFLICT" && (
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  state.reload();
                }}
              >
                최신 자산 정보 다시 확인
              </button>
            )}
            <div className="form-actions">
              <button
                type="submit"
                disabled={busy || error?.code === "VERSION_CONFLICT" || !closure.ready}
              >
                {busy ? "종료 처리 중…" : "사용 종료 확인"}
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={busy}
                onClick={() => setClosing(false)}
              >
                종료 취소
              </button>
            </div>
          </form>
        </TaskPanel>
      )}
    </>
  );
}

function AssetEdit({ id }: { id: string }) {
  const state = useAsset(id);
  if (state.loading && !state.asset) return <p role="status">수정할 자산을 불러오고 있어요.</p>;
  return state.asset ? (
    <AssetEditor key={state.asset.id} initial={state.asset} />
  ) : (
    <>
      <FinanceError error={state.error} />
      <button type="button" onClick={state.reload}>
        자산 다시 확인
      </button>
    </>
  );
}

export function AssetListPage() {
  const { state } = useAuth();
  const { month, currentMonth } = useMonth();
  const deleted = useRouteNotice(stateFlag("deleted", "asset"));
  return (
    <>
      <div className="intro">
        <p className="eyebrow">우리 집의 기본정보</p>
        <h1>자산과 부채</h1>
        <p>소유자와 지분, 보유 기간을 함께 관리해요.</p>
      </div>
      {deleted && <p role="status">자산이 삭제된 것을 확인했어요.</p>}
      <MonthPicker />
      <div className="form-actions month-action">
        <Link className="button-link" to={`/assets/months/${currentMonth}`}>
          이번 달 기록하기
        </Link>
        <Link to={`/assets/months/${month}`}>{formatMonth(month)} 월 기록 확인</Link>
      </div>
      {state.status === "authenticated" ? <AssetList /> : <SessionStatus />}
    </>
  );
}
export function AssetNewPage() {
  const { state } = useAuth();
  return (
    <>
      <div className="intro">
        <p className="eyebrow">우리 집의 기본정보</p>
        <h1>자산·부채 등록</h1>
        <p>같은 공동 자산은 한 번만 등록해요. 금액은 월별로 별도 확인해야 해요.</p>
      </div>
      {state.status === "authenticated" ? <AssetEditor /> : <SessionStatus />}
    </>
  );
}
export function AssetDetailPage({ edit = false }: { edit?: boolean }) {
  const { state } = useAuth();
  const { id = "" } = useParams();
  return (
    <>
      <div className="intro">
        <p className="eyebrow">우리 집의 기본정보</p>
        <h1>{edit ? "자산 정보 수정" : "자산 상세"}</h1>
      </div>
      {state.status === "authenticated" ? (
        edit ? (
          <AssetEdit key={id} id={id} />
        ) : (
          <AssetDetail key={id} id={id} />
        )
      ) : (
        <SessionStatus />
      )}
    </>
  );
}
