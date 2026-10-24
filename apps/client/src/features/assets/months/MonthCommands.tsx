import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router";
import { formatMonth, seoulMonth } from "../../../shared/MonthContext";
import { useAssetsApi } from "../api";
import { amountBases, shareToPercent } from "../model";
import type { Asset } from "../model";
import type { HouseholdMember } from "../../finance/FinanceSupport";
import { ScopeChanges, assetScope } from "./ScopeChanges";
import { dateLabel } from "../../finance/dates";
import { useAssetMonthsApi } from "./api";
import { MonthError, MonthSummary } from "./MonthFeedback";
import {
  carryCandidates,
  formatKrw,
  monthEnd,
  previousMonth,
  scopeDifferences,
  scopeIdentity,
} from "./model";
import type { MonthRecord, MonthValue } from "./model";
import { useIdempotencyKey, useMonthCommand } from "./useMonthCommand";
import { ApiError, toApiError } from "../../../platform/api";
import { useUnsavedChangesGuard } from "../../../shared/UnsavedChanges";

type RecordActionProps = {
  initial: MonthRecord;
  reload: () => Promise<MonthRecord>;
  close: () => void;
};
function useReview(initial: MonthRecord) {
  const [base, setBase] = useState(initial);
  const [latest, setLatest] = useState<MonthRecord | null>(null);
  return { base, setBase, latest, setLatest };
}
function RecordComparison({
  before,
  after,
  adopt,
}: {
  before: MonthRecord;
  after: MonthRecord;
  adopt: () => void;
}) {
  const byId = new Map(before.values.map((row) => [row.asset_id, row]));
  const changed = after.values.filter((row) => {
    const old = byId.get(row.asset_id);
    return (
      !old ||
      old.input_amount_krw !== row.input_amount_krw ||
      old.as_of_date !== row.as_of_date ||
      old.verification_state !== row.verification_state ||
      scopeIdentity(old) !== scopeIdentity(row)
    );
  });
  const removed = before.values.filter(
    (row) => !after.values.some((item) => item.asset_id === row.asset_id),
  );
  return (
    <section className="conflict-panel">
      <h3>최신 월 기록 확인</h3>
      <p>
        {before.revision_no}차 기록에서 현재 {after.revision_no}차 기록으로 확인했어요. 변경된 항목{" "}
        {changed.length}개 · 제외된 항목 {removed.length}개예요.
      </p>
      <MonthSummary record={after} />
      {changed.length + removed.length > 0 && (
        <ul>
          {changed.map((row) => (
            <li key={row.asset_id}>
              {row.name}: {formatKrw(byId.get(row.asset_id)?.input_amount_krw ?? null)} →{" "}
              {formatKrw(row.input_amount_krw)}, 기준일 {dateLabel(row.as_of_date)}, 지분{" "}
              {shareToPercent(row.household_share)}%, {amountBases[row.amount_basis]}
              {row.inclusion_status === "excluded" ? " · 합계 제외" : ""}
            </li>
          ))}
          {removed.map((row) => (
            <li key={row.asset_id}>{row.name}: 현재 범위에서 제외됨</li>
          ))}
        </ul>
      )}
      <button type="button" onClick={adopt}>
        최신 기록 기준으로 다시 검토
      </button>
    </section>
  );
}

export function CreateMonthDraft({
  month,
  reload,
}: {
  month: string;
  reload: () => Promise<MonthRecord>;
}) {
  const api = useAssetMonthsApi();
  const command = useMonthCommand();
  const [copyPrevious, setCopyPrevious] = useState(true);
  const [priorRefresh, setPriorRefresh] = useState(0);
  const prior = usePreviousConfirmation(month, priorRefresh);
  const copyAvailable = prior.loading || Boolean(prior.error) || prior.exists;
  const copyRequested = copyPrevious && copyAvailable;
  const [ackUnconfirmed, setAckUnconfirmed] = useState(false);
  // The acknowledgment does not change the request body, so the key fingerprint stays as is.
  const key = useIdempotencyKey(JSON.stringify(["draft", month, copyRequested]));
  const priorMonth = previousMonth(month);
  const unconfirmedPrior =
    copyPrevious && !prior.loading && !prior.error && prior.exists && !prior.record;
  async function create(event: FormEvent) {
    event.preventDefault();
    const result = await command.run((signal) =>
      api.draft(month, { copy_previous: copyRequested }, key, signal),
    );
    if (result.ok && command.mounted.current) await reload().catch(() => undefined);
  }
  if (month > seoulMonth())
    return (
      <section className="card">
        <h2>아직 시작하지 않은 달이에요</h2>
        <p>{formatMonth(month)}이 시작되면 이 달의 자산 기록을 만들 수 있어요.</p>
        <Link to={`/assets/months/${seoulMonth()}`}>이번 달 기록으로 이동</Link>
      </section>
    );
  return (
    <section className="card">
      <h2>이 달의 자산 기록 시작</h2>
      <p>
        이 달에 하루라도 보유한 자산과 부채를 확인해요. 종료한 자산도 종료한 달의 마지막 금액은 직접
        확인해요.
      </p>
      <form className="finance-form" onSubmit={(event) => void create(event)}>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={copyRequested}
            disabled={command.busy || !copyAvailable}
            onChange={(event) => setCopyPrevious(event.target.checked)}
          />
          전월 마지막 확정본의 금액 불러오기
        </label>
        <p className="muted">
          불러온 금액은 미확인 상태이며 기준일은 비워요. 전월 확정값이 없거나 금액 입력 기준이
          바뀌었으면 미입력으로 남겨요.
        </p>
        {copyPrevious && prior.loading && <p role="status">전월 기록 상태를 확인하고 있어요.</p>}
        {copyPrevious && prior.error && (
          <>
            <MonthError error={prior.error} />
            <button type="button" onClick={() => setPriorRefresh((value) => value + 1)}>
              전월 기록 상태 다시 확인
            </button>
          </>
        )}
        {unconfirmedPrior && priorMonth && (
          <section className="month-warning">
            <h3>전월 기록이 아직 확정되지 않았어요</h3>
            <p>
              {formatMonth(priorMonth)} 기록을 확정하면 그 금액을 미확인 값으로 불러올 수 있어요.
              지금 시작하면 모든 항목이 미입력으로 시작하고, 나중에 "전월 확정값 불러오기"로 손대지
              않은 미입력 항목만 채울 수 있어요.
            </p>
            <Link to={`/assets/months/${priorMonth}`}>전월 먼저 확정하기</Link>
            <label className="checkbox-field">
              <input
                type="checkbox"
                checked={ackUnconfirmed}
                disabled={command.busy}
                onChange={(event) => setAckUnconfirmed(event.target.checked)}
              />
              전월 확정값 없이 시작하는 것을 확인했어요.
            </label>
          </section>
        )}
        {copyPrevious && !prior.loading && !prior.error && !prior.exists && (
          <p className="muted">
            전월 기록이 없어 불러올 금액이 없어요. 모든 항목을 이번 달에 직접 확인해요.
          </p>
        )}
        <MonthError error={command.error} />
        <div className="form-actions">
          <button
            type="submit"
            disabled={
              command.busy ||
              (copyPrevious && (prior.loading || Boolean(prior.error))) ||
              (unconfirmedPrior && !ackUnconfirmed)
            }
          >
            {command.busy ? "작성본 만드는 중…" : "월 작성본 만들기"}
          </button>
          {command.busy && (
            <button type="button" onClick={command.cancel}>
              요청 대기 중단
            </button>
          )}
          {command.error && (
            <button
              type="button"
              disabled={command.busy}
              onClick={() => void reload().catch(() => undefined)}
            >
              현재 월 기록 다시 확인
            </button>
          )}
        </div>
      </form>
    </section>
  );
}

function usePreviousConfirmation(month: string, refresh: number) {
  const api = useAssetMonthsApi();
  const [record, setRecord] = useState<MonthRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [exists, setExists] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    const priorMonth = previousMonth(month);
    setLoading(true);
    setRecord(null);
    setError(null);
    setExists(false);
    void (async () => {
      if (!priorMonth) return;
      let cursor: number | null = null;
      const seen = new Set<number>();
      do {
        const history = await api.history(
          priorMonth,
          { limit: 200, ...(cursor === null ? {} : { cursor }) },
          controller.signal,
        );
        if (cursor === null && history.items.length > 0 && !controller.signal.aborted)
          setExists(true);
        const confirmed = history.items.find((item) => item.state === "confirmed");
        if (confirmed) {
          const value = await api.all(priorMonth, controller.signal, confirmed.revision_no);
          if (!controller.signal.aborted) setRecord(value);
          return;
        }
        cursor = history.next_cursor;
        if (cursor !== null) {
          if (seen.has(cursor)) throw new ApiError(0, "REQUEST_FAILED");
          seen.add(cursor);
        }
      } while (cursor !== null && !controller.signal.aborted);
    })()
      .catch((failure) => {
        const value = toApiError(failure);
        if (!controller.signal.aborted && value.code !== "MONTH_NOT_FOUND") setError(value);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [api, month, refresh]);
  return { record, exists, loading, error };
}

export function ConfirmMonth({
  initial,
  reload,
  close,
  confirmed,
}: RecordActionProps & { confirmed?: () => void }) {
  const api = useAssetMonthsApi();
  const command = useMonthCommand();
  const review = useReview(initial);
  const [priorRefresh, setPriorRefresh] = useState(0);
  const prior = usePreviousConfirmation(initial.month, priorRefresh);
  const [ackDates, setAckDates] = useState(false);
  const [ackScope, setAckScope] = useState(false);
  const [forceScope, setForceScope] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const difference = useMemo(
    () => scopeDifferences(prior.record, review.base),
    [prior.record, review.base],
  );
  const scopeChanged =
    forceScope ||
    (difference.hasPrevious &&
      difference.added.length + difference.removed.length + difference.changedShare.length > 0);
  const nonMonthEnd = review.base.values.filter(
    (row) => row.inclusion_status === "included" && row.as_of_date !== monthEnd(initial.month),
  );
  const body = {
    revision_id: review.base.revision_id,
    acknowledge_non_month_end_dates: ackDates,
    acknowledge_scope_change: ackScope,
  };
  const key = useIdempotencyKey(
    JSON.stringify(["confirm", initial.month, review.base.version, body]),
  );
  const ineligible =
    review.base.state === "confirmed" ||
    review.base.totals.provisional ||
    (review.base.state === "draft" && review.base.scope_stale);
  async function confirm(event: FormEvent) {
    event.preventDefault();
    if (
      ineligible ||
      prior.loading ||
      prior.error ||
      blocked ||
      (nonMonthEnd.length > 0 && !ackDates) ||
      (scopeChanged && !ackScope)
    )
      return;
    const result = await command.run((signal) =>
      api.confirm(initial.month, body, review.base.version, key, signal),
    );
    if (!command.mounted.current) return;
    if (result.ok) {
      confirmed?.();
      close();
      await reload().catch(() => undefined);
    } else if (result.error.code === "SCOPE_ACK_REQUIRED") {
      setForceScope(true);
      setAckScope(false);
      setPriorRefresh((value) => value + 1);
    } else if (result.error.status === 409 && result.error.code !== "OPERATION_IN_PROGRESS")
      setBlocked(true);
  }
  async function compare() {
    const result = await command.run(() => reload());
    if (result.ok && command.mounted.current) review.setLatest(result.value);
  }
  function adopt() {
    if (!review.latest) return;
    review.setBase(review.latest);
    review.setLatest(null);
    setAckDates(false);
    setAckScope(false);
    setBlocked(false);
    setForceScope(false);
    setPriorRefresh((value) => value + 1);
    command.setError(null);
  }
  return (
    <section className="card month-action-panel" aria-labelledby="month-confirm-title">
      <h2 id="month-confirm-title">월 확정 전 확인</h2>
      <MonthSummary record={review.base} />
      <p>확정하면 직접 덮어쓸 수 없어요. 이후 수정은 사유를 남기는 새 정정본으로 진행해요.</p>
      {ineligible && (
        <p className="month-warning">
          미입력·미확인 항목이나 자산 범위 변경을 먼저 확인해 주세요. 이미 확정한 기록은 다시
          확정하지 않아요.
        </p>
      )}
      <form className="finance-form" onSubmit={(event) => void confirm(event)}>
        {nonMonthEnd.length > 0 && (
          <section>
            <h3>월말과 다른 실제 기준일</h3>
            <ul>
              {nonMonthEnd.map((row) => (
                <li key={row.asset_id}>
                  {row.name}: {dateLabel(row.as_of_date)}
                </li>
              ))}
            </ul>
            <label className="checkbox-field">
              <input
                type="checkbox"
                disabled={command.busy}
                checked={ackDates}
                onChange={(event) => setAckDates(event.target.checked)}
              />
              월말과 다른 기준일을 확인했어요.
            </label>
          </section>
        )}
        <section>
          <h3>전월 확정본과 비교 범위</h3>
          {prior.loading ? (
            <p role="status">전월 확정본을 확인하고 있어요.</p>
          ) : prior.error ? (
            <>
              <MonthError error={prior.error} />
              <button type="button" onClick={() => setPriorRefresh((value) => value + 1)}>
                전월 확정본 다시 확인
              </button>
            </>
          ) : !prior.record ? (
            <p>전월 확정본이 없어 비교할 수 없어요. 0원 대비 증가로 표시하지 않아요.</p>
          ) : scopeChanged ? (
            <>
              <p>
                포함 항목이나 지분이 달라졌어요. 이 변화만으로 저축·투자 수익을 판단하지 않아요.
              </p>
              <ul>
                {difference.added.map((row) => (
                  <li key={row.asset_id}>새 비교 대상: {row.name}</li>
                ))}
                {difference.removed.map((row) => (
                  <li key={row.asset_id}>비교 대상에서 제외: {row.name}</li>
                ))}
                {difference.changedShare.map((row) => (
                  <li key={row.asset_id}>
                    가계 지분 변경: {row.name} · 현재 기록 {shareToPercent(row.household_share)}%
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p>전월 확정본과 포함 항목·가계 지분이 같아요.</p>
          )}
          {scopeChanged && (
            <label className="checkbox-field">
              <input
                type="checkbox"
                disabled={command.busy || prior.loading || Boolean(prior.error)}
                checked={ackScope}
                onChange={(event) => setAckScope(event.target.checked)}
              />
              전월과 달라진 포함 항목·가계 지분을 확인했어요.
            </label>
          )}
        </section>
        <MonthError error={command.error} />
        {command.error && (
          <button type="button" disabled={command.busy} onClick={() => void compare()}>
            확정 전 현재 기록 상태 확인
          </button>
        )}
        {review.latest && (
          <RecordComparison before={review.base} after={review.latest} adopt={adopt} />
        )}
        <div className="form-actions">
          <button
            type="submit"
            disabled={
              command.busy ||
              ineligible ||
              prior.loading ||
              Boolean(prior.error) ||
              blocked ||
              (nonMonthEnd.length > 0 && !ackDates) ||
              (scopeChanged && !ackScope)
            }
          >
            확인하고 월 확정
          </button>
          {command.busy && (
            <button type="button" onClick={command.cancel}>
              요청 대기 중단
            </button>
          )}
          <button
            type="button"
            className="secondary-button"
            disabled={command.busy}
            onClick={close}
          >
            확정 검토 닫기
          </button>
        </div>
      </form>
    </section>
  );
}

export function CarryPreviousMonth({ initial, reload, close }: RecordActionProps) {
  const api = useAssetMonthsApi();
  const command = useMonthCommand();
  const [refresh, setRefresh] = useState(0);
  const prior = usePreviousConfirmation(initial.month, refresh);
  const candidates = useMemo(() => carryCandidates(initial, prior.record), [initial, prior.record]);
  const [blocked, setBlocked] = useState(false);
  const body = { revision_id: initial.revision_id };
  const key = useIdempotencyKey(JSON.stringify(["carry", initial.month, initial.version, body]));
  const priorMonth = previousMonth(initial.month);
  async function carry(event: FormEvent) {
    event.preventDefault();
    if (blocked || candidates.length === 0) return;
    const result = await command.run((signal) =>
      api.carry(initial.month, body, initial.version, key, signal),
    );
    if (!command.mounted.current) return;
    if (result.ok) {
      close();
      await reload().catch(() => undefined);
    } else if (result.error.status === 409 && result.error.code !== "OPERATION_IN_PROGRESS")
      setBlocked(true);
  }
  return (
    <section className="card month-action-panel" aria-labelledby="month-carry-title">
      <h2 id="month-carry-title">전월 확정값 불러오기</h2>
      <p>
        아직 손대지 않은 미입력 항목에만 전월 확정 금액을 넣어요. 직접 입력했거나 사유를 남기고 비운
        항목, 금액 입력 기준이 바뀐 항목은 그대로 둬요. 불러온 금액은 미확인 상태라 이번 달 실제
        값과 기준일을 다시 확인해야 해요.
      </p>
      <form className="finance-form" onSubmit={(event) => void carry(event)}>
        {prior.loading && <p role="status">전월 확정 기록을 확인하고 있어요.</p>}
        {prior.error && (
          <>
            <MonthError error={prior.error} />
            <button type="button" onClick={() => setRefresh((value) => value + 1)}>
              전월 확정 기록 다시 확인
            </button>
          </>
        )}
        {!prior.loading && !prior.error && !prior.record && (
          <p>
            전월 확정 기록이 없어 불러올 금액이 없어요.{" "}
            {priorMonth && <Link to={`/assets/months/${priorMonth}`}>전월 먼저 확정하기</Link>}
          </p>
        )}
        {prior.record && candidates.length === 0 && <p>불러올 수 있는 미입력 항목이 없어요.</p>}
        {candidates.length > 0 && (
          <ul>
            {candidates.map(({ row, source }) => (
              <li key={row.asset_id}>
                {row.name}: {formatKrw(source.input_amount_krw)} · {amountBases[row.amount_basis]}
              </li>
            ))}
          </ul>
        )}
        <MonthError error={command.error} />
        {blocked && (
          <p>현재 월 기록을 다시 확인한 뒤 이 검토를 새로 열어 주세요. 자동 재시도하지 않아요.</p>
        )}
        <div className="form-actions">
          <button
            type="submit"
            disabled={
              command.busy || blocked || prior.loading || !prior.record || candidates.length === 0
            }
          >
            전월 확정값 불러오기
          </button>
          {command.busy && (
            <button type="button" onClick={command.cancel}>
              요청 대기 중단
            </button>
          )}
          <button
            type="button"
            className="secondary-button"
            disabled={command.busy}
            onClick={close}
          >
            불러오기 검토 닫기
          </button>
        </div>
      </form>
    </section>
  );
}

export function ReopenMonth({ initial, reload, close }: RecordActionProps) {
  const api = useAssetMonthsApi();
  const command = useMonthCommand();
  const review = useReview(initial);
  const [reason, setReason] = useState("");
  const [blocked, setBlocked] = useState(false);
  const guard = useUnsavedChangesGuard(reason.trim() !== "");
  const body = { revision_id: review.base.revision_id, reason: reason.trim() };
  const key = useIdempotencyKey(
    JSON.stringify(["reopen", initial.month, review.base.version, body]),
  );
  async function reopen(event: FormEvent) {
    event.preventDefault();
    if (!reason.trim() || blocked || review.base.state !== "confirmed") return;
    const result = await command.run((signal) =>
      api.reopen(initial.month, body, review.base.version, key, signal),
    );
    if (!command.mounted.current) return;
    if (result.ok) {
      guard.release();
      close();
      await reload().catch(() => undefined);
    } else if (result.error.status === 409 && result.error.code !== "OPERATION_IN_PROGRESS")
      setBlocked(true);
  }
  async function compare() {
    const result = await command.run(() => reload());
    if (result.ok && command.mounted.current) review.setLatest(result.value);
  }
  return (
    <section className="card month-action-panel">
      <h2>새 정정본 열기</h2>
      <p>
        {review.base.revision_no}차 확정 기록은 그대로 남겨요. 새 정정본은 당시 이름·소유
        관계·지분·금액 기준·포함 범위를 유지해요.
      </p>
      <form className="finance-form" onSubmit={(event) => void reopen(event)}>
        <div className="form-field">
          <label htmlFor="month-reopen-reason">정정 사유</label>
          <textarea
            id="month-reopen-reason"
            required
            maxLength={1000}
            rows={4}
            disabled={command.busy}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </div>
        <MonthError error={command.error} />
        {command.error && (
          <button type="button" disabled={command.busy} onClick={() => void compare()}>
            정정 전 현재 기록 상태 확인
          </button>
        )}
        {review.latest && (
          <RecordComparison
            before={review.base}
            after={review.latest}
            adopt={() => {
              review.setBase(review.latest!);
              review.setLatest(null);
              setBlocked(false);
              command.setError(null);
            }}
          />
        )}
        {review.base.state !== "confirmed" && (
          <p>현재는 확정 상태가 아니어서 새 정정본을 열 수 없어요. 입력한 사유는 유지했어요.</p>
        )}
        <div className="form-actions">
          <button
            type="submit"
            disabled={
              command.busy || blocked || !reason.trim() || review.base.state !== "confirmed"
            }
          >
            사유를 남기고 정정 시작
          </button>
          {command.busy && (
            <button type="button" onClick={command.cancel}>
              요청 대기 중단
            </button>
          )}
          <button
            type="button"
            className="secondary-button"
            disabled={command.busy}
            onClick={close}
          >
            정정 검토 닫기
          </button>
        </div>
      </form>
    </section>
  );
}

function sameLiveScope(row: MonthValue, asset: Asset): boolean {
  return (
    scopeIdentity(row) ===
    scopeIdentity({
      ...row,
      name: asset.name,
      kind: asset.kind,
      category: asset.category,
      ownership_kind: asset.ownership_kind,
      owner_member_id: asset.owner_member_id ?? null,
      household_share: asset.household_share ?? "1",
      amount_basis: asset.amount_basis,
      inclusion_status: asset.inclusion_status ?? "included",
      started_on: asset.started_on,
      ended_on: asset.ended_on ?? null,
    })
  );
}
export function SynchronizeMonthScope({
  initial,
  reload,
  close,
  members,
}: RecordActionProps & { members: HouseholdMember[] }) {
  const api = useAssetMonthsApi();
  const assetsApi = useAssetsApi();
  const command = useMonthCommand();
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [retry, setRetry] = useState(0);
  const [ack, setAck] = useState(false);
  const [blocked, setBlocked] = useState(false);
  useEffect(() => {
    let active = true;
    setAssets(null);
    setLoadError(null);
    setAck(false);
    void (async () => {
      const items: Asset[] = [];
      let cursor: string | null = null;
      const seen = new Set<string>();
      do {
        const page = await assetsApi.list({
          status: "all",
          limit: 200,
          ...(cursor ? { cursor } : {}),
        });
        items.push(...page.items);
        cursor = page.next_cursor;
        if (cursor) {
          if (seen.has(cursor)) throw new ApiError(0, "REQUEST_FAILED");
          seen.add(cursor);
        }
      } while (cursor && active);
      if (active)
        setAssets(
          items.filter(
            (asset) =>
              asset.started_on <= monthEnd(initial.month) &&
              (!asset.ended_on || asset.ended_on >= `${initial.month}-01`),
          ),
        );
    })().catch((failure) => {
      if (active) setLoadError(toApiError(failure));
    });
    return () => {
      active = false;
    };
  }, [assetsApi, initial.month, retry]);
  const added =
    assets?.filter((asset) => !initial.values.some((row) => row.asset_id === asset.id)) ?? [];
  const removed = assets
    ? initial.values.filter((row) => !assets.some((asset) => asset.id === row.asset_id))
    : [];
  const changed =
    assets?.filter((asset) => {
      const row = initial.values.find((item) => item.asset_id === asset.id);
      return row && !sameLiveScope(row, asset);
    }) ?? [];
  async function synchronize(event: FormEvent) {
    event.preventDefault();
    if (!ack || !assets || blocked) return;
    const result = await command.run((signal) =>
      api.sync(initial.month, { revision_id: initial.revision_id }, initial.version, signal),
    );
    if (!command.mounted.current) return;
    if (result.ok) {
      close();
      await reload().catch(() => undefined);
    } else if (result.error.status === 409) setBlocked(true);
  }
  return (
    <section className="card month-action-panel">
      <h2>현재 자산 범위 반영 전 확인</h2>
      <p>
        아래 현재 기본정보를 이 월 기록에 명시적으로 반영해요. 바뀐 행은 미확인으로 돌아가며
        기준일을 다시 확인해야 해요. 금액 입력 기준이 바뀐 행의 금액은 미입력으로 비워요.
      </p>
      {initial.state === "reopened" && (
        <p className="month-warning">
          정정본은 과거 범위를 유지하는 것이 기본이에요. 이 동작은 과거 범위를 현재 기본정보로
          바꿔요. 필요하지 않으면 반영하지 않고 정정을 계속할 수 있어요.
        </p>
      )}
      <MonthError error={loadError} />
      {loadError && (
        <button type="button" onClick={() => setRetry((value) => value + 1)}>
          현재 기본정보 다시 조회
        </button>
      )}
      {!assets && !loadError && <p role="status">반영할 현재 기본정보를 확인하고 있어요.</p>}
      {assets && (
        <>
          <p>
            추가 {added.length}개 · 제외 {removed.length}개 · 기본정보 변경 {changed.length}개
          </p>
          <ul>
            {added.map((asset) => (
              <li key={asset.id}>
                추가: {asset.name} · 지분 {shareToPercent(asset.household_share ?? "1")}% ·{" "}
                {amountBases[asset.amount_basis]}
              </li>
            ))}
            {removed.map((row) => (
              <li key={row.asset_id}>이 달의 범위에서 제외: {row.name}</li>
            ))}
            {changed.map((asset) => {
              const row = initial.values.find((item) => item.asset_id === asset.id)!;
              return (
                <li key={asset.id}>
                  변경: {row.name} → {asset.name} · 지분 {shareToPercent(row.household_share)}% →{" "}
                  {shareToPercent(asset.household_share ?? "1")}% · {amountBases[row.amount_basis]}{" "}
                  → {amountBases[asset.amount_basis]} ·{" "}
                  {asset.inclusion_status === "excluded" ? "합계 제외" : "합계 포함"}
                  <ScopeChanges before={row} after={assetScope(asset)} members={members} />
                </li>
              );
            })}
          </ul>
        </>
      )}
      <form className="finance-form" onSubmit={(event) => void synchronize(event)}>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={ack}
            disabled={!assets || command.busy || blocked}
            onChange={(event) => setAck(event.target.checked)}
          />
          변경될 범위와 미확인으로 돌아갈 항목을 확인했어요.
        </label>
        <MonthError error={command.error} />
        {command.error && (
          <p>
            작성 중인 월 기록을 다시 확인한 뒤 이 검토를 새로 열어 주세요. 자동 재시도하지 않아요.
          </p>
        )}
        <div className="form-actions">
          <button type="submit" disabled={!assets || !ack || command.busy || blocked}>
            확인한 현재 자산 범위 반영
          </button>
          {command.busy && (
            <button type="button" onClick={command.cancel}>
              요청 대기 중단
            </button>
          )}
          <button
            type="button"
            disabled={command.busy}
            className="secondary-button"
            onClick={close}
          >
            범위 검토 닫기
          </button>
        </div>
      </form>
    </section>
  );
}
