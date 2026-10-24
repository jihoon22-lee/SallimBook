import { DateInput } from "../../shared/DateInput";
import { OptionalFields } from "../../shared/OptionalFields";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { useMounted } from "../auth/AuthFeedback";
import { FinanceError, MemberLoadError, useHouseholdMembers } from "../finance/FinanceSupport";
import { AssetFields } from "../assets/AssetFields";
import { useAssetsApi } from "../assets/api";
import { assetInput, newAssetDraft } from "../assets/model";
import type { Asset } from "../assets/model";
import { useAccountsApi } from "./api";
import { accountDraft, accountInput, accountLabels, accountTypes } from "./model";
import type { Account, AccountDraft, AccountPatch } from "./model";
import { useUnsavedChangesGuard } from "../../shared/UnsavedChanges";

export function AccountEditor({ initial }: { initial?: Account }) {
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const api = useAccountsApi();
  const assetsApi = useAssetsApi();
  const navigate = useNavigate();
  const mounted = useMounted();
  const members = useHouseholdMembers();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => accountDraft(initial));
  const [mode, setMode] = useState("new");
  const [asset, setAsset] = useState(newAssetDraft(true));
  const [assetId, setAssetId] = useState("");
  const [available, setAvailable] = useState<Asset[]>([]);
  const [assetError, setAssetError] = useState<ApiError | null>(null);
  const [assetLoading, setAssetLoading] = useState(false);
  const [assetRetry, setAssetRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const flight = useRef(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [formError, setFormError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [latest, setLatest] = useState<Account | null>(null);
  useEffect(() => {
    if (initial || mode !== "existing") return;
    let active = true;
    setAssetLoading(true);
    setAssetError(null);
    void (async () => {
      const all: Asset[] = [];
      let cursor: string | null = null;
      do {
        const response = await assetsApi.list({
          kind: "asset",
          category: "financial",
          status: "active",
          limit: 100,
          ...(cursor ? { cursor } : {}),
        });
        all.push(...response.items);
        cursor = response.next_cursor;
      } while (cursor && active);
      // Any account, closed ones included, already owns its asset; the server's 409 stays final.
      const linked = new Set<string>();
      let accountCursor: string | null = null;
      const seen = new Set<string>();
      do {
        const response = await api.list({
          status: "all",
          limit: 200,
          ...(accountCursor ? { cursor: accountCursor } : {}),
        });
        for (const account of response.items) linked.add(account.asset_id);
        accountCursor = response.next_cursor;
        if (accountCursor) {
          if (seen.has(accountCursor)) throw new ApiError(0, "REQUEST_FAILED");
          seen.add(accountCursor);
        }
      } while (accountCursor && active);
      if (active)
        setAvailable(
          all.filter(
            (item) => item.status === "active" && item.ended_on === null && !linked.has(item.id),
          ),
        );
    })()
      .catch((failure) => {
        if (active) setAssetError(toApiError(failure));
      })
      .finally(() => {
        if (active) setAssetLoading(false);
      });
    return () => {
      active = false;
    };
  }, [initial, mode, api, assetsApi, assetRetry]);
  const changed = base
    ? (Object.keys(draft) as (keyof AccountDraft)[]).filter(
        (key) => draft[key] !== accountDraft(base)[key],
      )
    : [];
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (flight.current || conflict) return;
    const input = accountInput(draft);
    const linked =
      mode === "new" ? assetInput(asset) : available.find((item) => item.id === assetId);
    if (
      !input ||
      (!base && !linked) ||
      (input.opened_on &&
        (base?.closed_on ?? linked?.ended_on) &&
        input.opened_on > (base?.closed_on ?? linked?.ended_on)!)
    ) {
      setFormError("계좌 기본정보와 금융 자산, 개설일·종료일을 확인해 주세요.");
      return;
    }
    const before = base ? accountInput(accountDraft(base))! : null;
    const patch = before
      ? (Object.fromEntries(
          Object.entries(input).filter(
            ([key, value]) => value !== before[key as keyof typeof before],
          ),
        ) as AccountPatch)
      : null;
    if (patch && Object.keys(patch).length === 0) {
      setFormError("변경한 내용이 없어요.");
      return;
    }
    flight.current = true;
    setBusy(true);
    setError(null);
    setFormError("");
    try {
      const saved =
        base && patch
          ? await api.update(base.id, patch, base.version)
          : await api.create({
              ...input,
              ...(mode === "new" ? { asset: assetInput(asset)! } : { asset_id: assetId }),
            });
      if (mounted.current) {
        guard.release();
        navigate(`/accounts/${saved.id}`, { replace: true, state: { saved: true } });
      }
    } catch (failure) {
      if (mounted.current) {
        const value = toApiError(failure);
        setError(value);
        if (value.code === "VERSION_CONFLICT") setConflict(true);
      }
    } finally {
      flight.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function loadLatest() {
    if (!base || flight.current) return;
    flight.current = true;
    setBusy(true);
    setError(null);
    try {
      const value = await api.get(base.id);
      if (mounted.current) setLatest(value);
    } catch (failure) {
      if (mounted.current) setError(toApiError(failure));
    } finally {
      flight.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  function resolve(keep: boolean) {
    if (!latest) return;
    const next = accountDraft(latest);
    if (keep) for (const field of changed) Object.assign(next, { [field]: draft[field] });
    setBase(latest);
    setDraft(next);
    setLatest(null);
    setConflict(false);
    setError(null);
  }
  return (
    <section className="card">
      <p>
        계좌는 금융 자산 하나와 연결해요. 계좌 잔액과 자산 평가액을 두 번 합산하지 않아요.
        계좌번호는 저장 후 별도로 관리할 수 있어요.
      </p>
      <form
        onInput={() => setDirty(true)}
        className="finance-form"
        onSubmit={(event) => void submit(event)}
      >
        <fieldset className="finance-fields" disabled={busy}>
          <legend>계좌 기본정보</legend>
          <div className="form-field">
            <label htmlFor="account-institution">금융기관</label>
            <input
              id="account-institution"
              required
              maxLength={120}
              value={draft.institution_name}
              onChange={(event) => setDraft({ ...draft, institution_name: event.target.value })}
            />
          </div>
          <div className="form-field">
            <label htmlFor="account-type">계좌 유형</label>
            <select
              id="account-type"
              required
              value={draft.account_type}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  account_type: event.target.value as AccountDraft["account_type"],
                })
              }
            >
              <option value="">유형 선택</option>
              {Object.entries(accountTypes).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </fieldset>
        {base ? (
          <p>
            연결된 자산:{" "}
            <Link to={`/assets/${base.asset_id}/edit`}>{base.asset.name} 기본정보 수정</Link>
          </p>
        ) : (
          <>
            <div className="form-field">
              <label htmlFor="account-asset-mode">금융 자산 연결</label>
              <select
                id="account-asset-mode"
                disabled={busy}
                value={mode}
                onChange={(event) => setMode(event.target.value)}
              >
                <option value="new">새 금융 자산과 함께 등록</option>
                <option value="existing">기존 금융 자산에 연결</option>
              </select>
            </div>
            {mode === "new" ? (
              <>
                <MemberLoadError error={members.error} retry={members.retry} />
                <AssetFields
                  value={asset}
                  onChange={setAsset}
                  members={members.members}
                  financial
                  disabled={busy || members.loading || Boolean(members.error)}
                />
              </>
            ) : (
              <>
                <div className="form-field">
                  <label htmlFor="account-asset">연결할 금융 자산</label>
                  <select
                    id="account-asset"
                    required
                    disabled={busy || assetLoading}
                    value={assetId}
                    onChange={(event) => setAssetId(event.target.value)}
                  >
                    <option value="">금융 자산 선택</option>
                    {available.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                        {item.status === "archived" ? " (사용 종료)" : ""}
                      </option>
                    ))}
                  </select>
                  {!assetLoading && !assetError && available.length === 0 && (
                    <p className="muted">
                      연결할 수 있는 사용 중 금융 자산이 없어요. 새 금융 자산과 함께 등록해 주세요.
                    </p>
                  )}
                </div>
                <FinanceError error={assetError} />
                <button
                  type="button"
                  disabled={busy || assetLoading}
                  onClick={() => setAssetRetry((value) => value + 1)}
                >
                  금융 자산 다시 불러오기
                </button>
                <p className="muted">
                  사용 중인 금융 자산만 연결할 수 있어요. 이미 계좌에 연결된 자산은 다시 연결할 수
                  없어요.
                </p>
              </>
            )}
          </>
        )}
        <fieldset disabled={busy} className="finance-fields">
          <OptionalFields
            title="계좌 용도·개설일"
            hasError={Boolean(formError)}
            hasValues={Boolean(draft.purpose || draft.opened_on)}
          >
            <div className="form-field">
              <label htmlFor="account-purpose">용도 (선택)</label>
              <input
                id="account-purpose"
                maxLength={500}
                value={draft.purpose}
                onChange={(event) => setDraft({ ...draft, purpose: event.target.value })}
              />
              <p className="muted">전체 계좌번호는 용도에 입력하지 마세요.</p>
            </div>
            <div className="form-field">
              <label htmlFor="account-opened">개설일 (선택)</label>
              <DateInput
                id="account-opened"
                min="0001-01-01"
                max={base?.closed_on || "9999-12-31"}
                value={draft.opened_on}
                onChange={(event) => setDraft({ ...draft, opened_on: event.target.value })}
              />
            </div>
          </OptionalFields>
        </fieldset>
        {formError && <p role="alert">{formError}</p>}
        <FinanceError error={error} />
        {conflict && (
          <section className="conflict-panel">
            <h2>서버 변경과 내 수정 확인</h2>
            <p>작성한 내용을 보존했어요. 최신 값을 확인한 뒤 다시 저장해 주세요.</p>
            <button type="button" disabled={busy} onClick={() => void loadLatest()}>
              서버의 최신 계좌 정보 확인
            </button>
            {latest && (
              <>
                <div
                  className="table-scroll"
                  tabIndex={0}
                  role="region"
                  aria-label="계좌 수정 비교 표"
                >
                  <table>
                    <caption>내가 바꾼 계좌 정보</caption>
                    <thead>
                      <tr>
                        <th>항목</th>
                        <th>내 수정</th>
                        <th>서버 최신 값</th>
                      </tr>
                    </thead>
                    <tbody>
                      {changed.map((key) => (
                        <tr key={key}>
                          <th scope="row">{accountLabels[key]}</th>
                          <td>
                            {key === "account_type" && draft.account_type
                              ? accountTypes[draft.account_type]
                              : draft[key] || "미입력"}
                          </td>
                          <td>
                            {key === "account_type"
                              ? accountTypes[latest.account_type]
                              : accountDraft(latest)[key] || "미입력"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p>내 수정 유지는 바꾼 항목만 유지하고, 나머지는 서버의 최신 값으로 가져와요.</p>
                <div className="form-actions">
                  <button type="button" onClick={() => resolve(true)}>
                    비교한 내 계좌 수정 유지
                  </button>
                  <button type="button" onClick={() => resolve(false)}>
                    내 계좌 수정 버리고 서버 값 사용
                  </button>
                </div>
              </>
            )}
          </section>
        )}
        <div className="form-actions">
          <button
            type="submit"
            disabled={
              busy ||
              conflict ||
              (!base &&
                (mode === "new"
                  ? members.loading || Boolean(members.error)
                  : assetLoading || Boolean(assetError)))
            }
          >
            {busy ? "저장 중…" : base ? "계좌 수정 저장" : "계좌 등록"}
          </button>
          <Link
            replace
            to={base ? `/accounts/${base.id}` : "/accounts"}
            aria-disabled={busy}
            onClick={(event) => {
              if (busy) event.preventDefault();
            }}
          >
            취소하고 돌아가기
          </Link>
        </div>
      </form>
    </section>
  );
}
