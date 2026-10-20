import { FilterPanel } from "../../shared/TaskLayout";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { useAuth } from "../auth/AuthProvider";
import { SessionStatus, useMounted } from "../auth/AuthFeedback";
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
import { ClosureReview, useClosureReview } from "../finance/PaymentLinks";
import { AssetMonthlyData } from "../assets/comparison/AssetMonthlyData";
import { AssetSummary, ownerLabel } from "../assets/AssetPages";
import { useAssetsApi } from "../assets/api";
import { AccountEditor } from "./AccountEditor";
import { AccountNumber } from "./AccountNumber";
import { useAccountsApi } from "./api";
import { accountTypes } from "./model";
import type { Account, AccountQuery } from "./model";

function AccountList() {
  const api = useAccountsApi();
  const members = useHouseholdMembers();
  const mounted = useMounted();
  const [params, setParams] = useSearchParams();
  const pending = useRef(params);
  useEffect(() => {
    pending.current = params;
  }, [params]);
  const type = Object.hasOwn(accountTypes, params.get("type") ?? "") ? params.get("type")! : "";
  const owner = isUuid(params.get("owner") ?? "") ? params.get("owner")! : "";
  const status = ["active", "closed", "all"].includes(params.get("status") ?? "")
    ? params.get("status")!
    : "active";
  const query = useMemo<AccountQuery>(
    () => ({
      limit: 50,
      status: status as AccountQuery["status"],
      ...(type ? { account_type: type as Account["account_type"] } : {}),
      ...(owner ? { owner_member_id: owner } : {}),
    }),
    [type, owner, status],
  );
  const [items, setItems] = useState<Account[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const generation = useRef(0);
  const load = useCallback(
    async (after?: string) => {
      const current = ++generation.current;
      setLoading(true);
      setError(null);
      if (!after) {
        setItems([]);
        setCursor(null);
      }
      try {
        const response = await api.list({ ...query, ...(after ? { cursor: after } : {}) });
        if (!mounted.current || current !== generation.current) return;
        setItems((old) =>
          after
            ? [
                ...old,
                ...response.items.filter((item) => !old.some((value) => value.id === item.id)),
              ]
            : response.items,
        );
        setCursor(response.next_cursor);
      } catch (failure) {
        if (mounted.current && current === generation.current) setError(toApiError(failure));
      } finally {
        if (mounted.current && current === generation.current) setLoading(false);
      }
    },
    [api, query, mounted],
  );
  useEffect(() => {
    void load();
    return () => {
      generation.current++;
    };
  }, [load]);
  function filter(key: string, value: string) {
    const next = new URLSearchParams(pending.current);
    if (value) next.set(key, value);
    else next.delete(key);
    pending.current = next;
    setParams(next);
  }
  return (
    <>
      <Link className="button-link" to="/accounts/new">
        계좌 등록
      </Link>
      <FilterPanel
        title="계좌 찾기"
        defaultLabel="사용 중"
        activeCount={[type, owner, status !== "active" ? status : ""].filter(Boolean).length}
      >
        <div className="filter-grid">
          <div className="form-field">
            <label htmlFor="account-type-filter">계좌 유형 필터</label>
            <select
              id="account-type-filter"
              value={type}
              onChange={(event) => filter("type", event.target.value)}
            >
              <option value="">모든 유형</option>
              {Object.entries(accountTypes).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="account-owner-filter">계좌 소유자 필터</label>
            <select
              id="account-owner-filter"
              value={owner}
              onChange={(event) => filter("owner", event.target.value)}
            >
              <option value="">공동·개인 모두</option>
              {members.members.map((member) => (
                <option key={member.member_id} value={member.member_id}>
                  {member.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="account-status-filter">계좌 상태 필터</label>
            <select
              id="account-status-filter"
              value={status}
              onChange={(event) => filter("status", event.target.value)}
            >
              <option value="active">사용 중</option>
              <option value="closed">종료</option>
              <option value="all">모든 상태</option>
            </select>
          </div>
        </div>
        <div className="form-actions">
          <button type="button" disabled={loading} onClick={() => void load()}>
            계좌 목록 다시 불러오기
          </button>
          <button
            type="button"
            onClick={() => {
              pending.current = new URLSearchParams();
              setParams({});
            }}
          >
            계좌 필터 초기화
          </button>
        </div>
      </FilterPanel>
      <MemberLoadError error={members.error} retry={members.retry} />
      <FinanceError error={error} />
      {error && (
        <button type="button" onClick={() => void load()}>
          계좌 다시 확인
        </button>
      )}
      {loading && (
        <p className="loading-state" role="status">
          계좌 목록을 불러오고 있어요.
        </p>
      )}
      {!loading && !error && items.length === 0 && (
        <section className="card">
          <h2>조건에 맞는 계좌가 없어요</h2>
          <p>필터를 바꾸거나 계좌를 등록해 주세요.</p>
        </section>
      )}
      {items.length > 0 && <MissingAmount />}
      <ul className="finance-list task-records">
        {items.map((account) => (
          <li className="card" key={account.id}>
            <div className="item-heading">
              <h2>
                <Link to={`/accounts/${account.id}`}>{account.asset.name}</Link>
              </h2>
              <span className="status-chip">
                {account.status === "closed" ? "종료" : "사용 중"}
              </span>
            </div>
            <dl className="metadata-grid compact-metadata">
              <div>
                <dt>금융기관·유형</dt>
                <dd>
                  {account.institution_name} · {accountTypes[account.account_type]}
                </dd>
              </div>
              <div>
                <dt>계좌번호</dt>
                <dd>{account.masked_number ?? "미등록"}</dd>
              </div>
              <div>
                <dt>소유자</dt>
                <dd>{ownerLabel(account.asset, members.members)}</dd>
              </div>
              <div>
                <dt>용도</dt>
                <dd>{account.purpose || "미입력"}</dd>
              </div>
            </dl>
          </li>
        ))}
      </ul>
      {cursor && (
        <button type="button" disabled={loading} onClick={() => void load(cursor)}>
          계좌 더 보기
        </button>
      )}
    </>
  );
}

function useAccount(id: string) {
  const api = useAccountsApi();
  const [account, setAccount] = useState<Account | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
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
        if (active) setAccount(value);
      })
      .catch((failure) => {
        if (active) {
          setAccount(null);
          setError(toApiError(failure));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, id, retry]);
  return { account, error, loading, reload: () => setRetry((value) => value + 1) };
}

function AccountDetail({ id }: { id: string }) {
  const state = useAccount(id);
  const api = useAssetsApi();
  const members = useHouseholdMembers();
  const mounted = useMounted();
  const location = useLocation();
  const [closing, setClosing] = useState(false);
  const [endedOn, setEndedOn] = useState(todaySeoul);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [formError, setFormError] = useState("");
  const closure = useClosureReview("account", id, endedOn, closing);
  async function close(event: FormEvent) {
    event.preventDefault();
    if (!state.account || busy || !closure.ready) return;
    if (
      !isDateOnly(endedOn) ||
      endedOn < state.account.asset.started_on ||
      (state.account.opened_on && endedOn < state.account.opened_on)
    ) {
      setFormError("종료일은 보유 시작일과 계좌 개설일 이후의 실제 날짜로 입력해 주세요.");
      return;
    }
    setBusy(true);
    setError(null);
    setFormError("");
    try {
      await api.archive(
        state.account.asset_id,
        { ended_on: endedOn, ...closure.proof },
        state.account.asset.version,
      );
      if (mounted.current) {
        setClosing(false);
        state.reload();
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
  if (state.loading && !state.account) return <p role="status">계좌 정보를 불러오고 있어요.</p>;
  if (!state.account)
    return (
      <>
        <FinanceError error={state.error} />
        <button type="button" onClick={state.reload}>
          계좌 다시 확인
        </button>
      </>
    );
  const account = state.account;
  return (
    <>
      {location.state?.saved && <p role="status">계좌 정보를 저장했어요.</p>}
      <section className="card">
        <h2>{account.asset.name}</h2>
        <dl className="metadata-grid">
          <div>
            <dt>금융기관</dt>
            <dd>{account.institution_name}</dd>
          </div>
          <div>
            <dt>계좌 유형</dt>
            <dd>{accountTypes[account.account_type]}</dd>
          </div>
          <div>
            <dt>용도</dt>
            <dd>{account.purpose || "미입력"}</dd>
          </div>
          <div>
            <dt>개설일</dt>
            <dd>{dateLabel(account.opened_on)}</dd>
          </div>
          <div>
            <dt>종료일</dt>
            <dd>{dateLabel(account.closed_on)}</dd>
          </div>
          <div>
            <dt>계좌 상태</dt>
            <dd>{account.status === "closed" ? "종료" : "사용 중"}</dd>
          </div>
        </dl>
        <div className="form-actions">
          <Link className="button-link" to={`/accounts/${id}/edit`}>
            계좌 정보 수정
          </Link>
          {account.status === "active" && (
            <button
              type="button"
              onClick={() => {
                setError(null);
                setClosing(true);
              }}
            >
              계좌 사용 종료하기
            </button>
          )}
          <Link to="/accounts">계좌 목록</Link>
        </div>
      </section>
      <AccountNumber key={account.id} account={account} refresh={state.reload} />
      <section className="card">
        <h2>연결된 금융 자산</h2>
        <p>
          계좌와 이 자산은 하나의 평가액을 공유해요. 수입이나 납부 입력으로 잔액을 자동 변경하지
          않아요.
        </p>
        <AssetSummary asset={account.asset} members={members.members} />
        <MemberLoadError error={members.error} retry={members.retry} />
        <Link to={`/assets/${account.asset_id}`}>연결된 자산 보기</Link>
      </section>
      <AssetMonthlyData assetId={account.asset_id} />
      {closing && (
        <section className="card">
          <h2>계좌 사용 종료</h2>
          <p>연결된 금융 자산도 함께 사용 종료돼요. 계좌 정보와 과거 기록은 보존해요.</p>
          <form className="finance-form" onSubmit={(event) => void close(event)}>
            <div className="form-field">
              <label htmlFor="account-closed">계좌 종료일</label>
              <input
                id="account-closed"
                type="date"
                required
                max="9999-12-31"
                min={
                  account.opened_on && account.opened_on > account.asset.started_on
                    ? account.opened_on
                    : account.asset.started_on
                }
                value={endedOn}
                onChange={(event) => setEndedOn(event.target.value)}
                disabled={busy}
              />
            </div>
            <ClosureReview review={closure} disabled={busy} />
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
                종료 전 최신 계좌 정보 확인
              </button>
            )}
            <div className="form-actions">
              <button
                type="submit"
                disabled={busy || error?.code === "VERSION_CONFLICT" || !closure.ready}
              >
                계좌 사용 종료 확인
              </button>
              <button type="button" disabled={busy} onClick={() => setClosing(false)}>
                계좌 종료 취소
              </button>
            </div>
          </form>
        </section>
      )}
    </>
  );
}
function AccountEdit({ id }: { id: string }) {
  const state = useAccount(id);
  if (state.loading) return <p role="status">수정할 계좌를 불러오고 있어요.</p>;
  return state.account ? (
    <AccountEditor initial={state.account} />
  ) : (
    <>
      <FinanceError error={state.error} />
      <button type="button" onClick={state.reload}>
        계좌 다시 확인
      </button>
    </>
  );
}
export function AccountListPage() {
  const { state } = useAuth();
  return (
    <>
      <div className="intro">
        <p className="eyebrow">우리 집의 금융 계좌</p>
        <h1>계좌 관리</h1>
        <p>은행·증권·연금저축·IRP·DC·ISA를 한곳에서 관리해요.</p>
      </div>
      {state.status === "authenticated" ? <AccountList /> : <SessionStatus />}
    </>
  );
}
export function AccountNewPage() {
  const { state } = useAuth();
  return (
    <>
      <div className="intro">
        <h1>계좌 등록</h1>
        <p>계좌 기본정보와 연결할 금융 자산을 선택해 주세요.</p>
      </div>
      {state.status === "authenticated" ? <AccountEditor /> : <SessionStatus />}
    </>
  );
}
export function AccountDetailPage({ edit = false }: { edit?: boolean }) {
  const { state } = useAuth();
  const { id = "" } = useParams();
  return (
    <>
      <div className="intro">
        <h1>{edit ? "계좌 정보 수정" : "계좌 상세"}</h1>
      </div>
      {state.status === "authenticated" ? (
        edit ? (
          <AccountEdit key={id} id={id} />
        ) : (
          <AccountDetail key={id} id={id} />
        )
      ) : (
        <SessionStatus />
      )}
    </>
  );
}
