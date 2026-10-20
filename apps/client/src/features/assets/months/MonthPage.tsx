import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import type { components } from "@sallimbook/api-client";
import { ApiError, toApiError } from "../../../platform/api";
import { formatMonth, isValidMonth, useMonth } from "../../../shared/MonthContext";
import { useAuth } from "../../auth/AuthProvider";
import { SessionStatus, useMounted } from "../../auth/AuthFeedback";
import { dateLabel, MemberLoadError, useHouseholdMembers } from "../../finance/FinanceSupport";
import type { HouseholdMember } from "../../finance/FinanceSupport";
import { amountBases, assetKinds, categories, shareToPercent } from "../model";
import { useAssetMonthsApi } from "./api";
import {
  CarryPreviousMonth,
  ConfirmMonth,
  CreateMonthDraft,
  ReopenMonth,
  SynchronizeMonthScope,
} from "./MonthCommands";
import { MonthError, MonthSummary } from "./MonthFeedback";
import { snapshotOwner } from "./ScopeChanges";
import { MonthRowEditor } from "./MonthRowEditor";
import type { EditingValue } from "./MonthRowEditor";
import { carriedNote, formatKrw, monthStates, untouchedMissing, verificationStates } from "./model";
import type { MonthRecord, MonthValue } from "./model";
import { formatSeoulDateTime } from "../../../shared/format";

function SnapshotList({
  record,
  members,
  readOnly,
  locked,
  edit,
}: {
  record: MonthRecord;
  members: HouseholdMember[];
  readOnly: boolean;
  locked: boolean;
  edit: (row: MonthValue) => void;
}) {
  return (
    <section aria-labelledby="month-values-title">
      <h2 id="month-values-title" tabIndex={-1}>
        이 기록에 포함된 자산·부채
      </h2>
      <p className="muted">
        이름·소유 관계·지분·금액 기준은 이 기록에 저장된 내용이에요. 현재 자산 기본정보를 자동으로
        섞지 않아요.
      </p>
      {record.values.length === 0 && (
        <div className="card">
          <p>이 기록의 작성 대상이 없어요. 등록된 자산의 보유 기간과 월을 확인해 주세요.</p>
          <Link to="/assets">자산 기본정보 확인</Link>
        </div>
      )}
      <ul className="finance-list task-records">
        {record.values.map((row) => (
          <li className="card month-value-card" key={row.asset_id}>
            <div className="item-heading">
              <h3>{row.name}</h3>
              <span
                className={`status-chip ${row.verification_state !== "verified" ? "unverified-chip" : ""}`}
              >
                {verificationStates[row.verification_state]}
              </span>
            </div>
            <p className="record-subline">
              {assetKinds[row.kind]} ·{" "}
              {row.inclusion_status === "included" ? "합계 포함" : "합계 제외"} ·{" "}
              {amountBases[row.amount_basis]}
            </p>
            <dl className="metadata-grid compact-metadata">
              <div>
                <dt>입력 금액</dt>
                <dd>{formatKrw(row.input_amount_krw)}</dd>
              </div>
              <div>
                <dt>가계 보유분</dt>
                <dd>{formatKrw(row.owned_amount_krw)}</dd>
              </div>
              <div>
                <dt>실제 기준일</dt>
                <dd>{dateLabel(row.as_of_date)}</dd>
              </div>
            </dl>
            {!readOnly && (
              <div className="primary-action-row">
                <button
                  type="button"
                  className={
                    row.verification_state !== "verified" ? "primary-button" : "secondary-button"
                  }
                  disabled={locked}
                  data-month-row={row.asset_id}
                  onClick={() => edit(row)}
                >
                  {row.name} 금액 확인
                </button>
              </div>
            )}
            {carriedNote(row) && <p className="muted">{carriedNote(row)}</p>}
            {row.change_reason && <p>값 변경 사유: {row.change_reason}</p>}
            <details className="record-details">
              <summary>이 기록의 소유·지분·보유기간</summary>
              <dl className="metadata-grid">
                <div>
                  <dt>분류</dt>
                  <dd>
                    {assetKinds[row.kind]} · {categories[row.category]}
                  </dd>
                </div>
                <div>
                  <dt>소유 관계</dt>
                  <dd>{snapshotOwner(row, members)}</dd>
                </div>
                <div>
                  <dt>가계 지분</dt>
                  <dd>{shareToPercent(row.household_share)}%</dd>
                </div>
                <div>
                  <dt>금액 입력 기준</dt>
                  <dd>{amountBases[row.amount_basis]}</dd>
                </div>
                <div>
                  <dt>합계 반영</dt>
                  <dd>{row.inclusion_status === "included" ? "합계 포함" : "합계 제외"}</dd>
                </div>
                <div>
                  <dt>보유 기간</dt>
                  <dd>
                    {dateLabel(row.started_on)} ~{" "}
                    {row.ended_on ? dateLabel(row.ended_on) : "종료일 없음"}
                  </dd>
                </div>
              </dl>
            </details>
          </li>
        ))}
      </ul>
    </section>
  );
}

function MonthHistory({ month, refresh }: { month: string; refresh: string }) {
  const api = useAssetMonthsApi();
  const mounted = useMounted();
  const [items, setItems] = useState<components["schemas"]["MonthHistoryItem"][]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const generation = useRef(0);
  const load = useCallback(
    async (after?: number) => {
      const current = ++generation.current;
      setLoading(true);
      setError(null);
      if (after === undefined) {
        setItems([]);
        setCursor(null);
      }
      try {
        const response = await api.history(month, {
          limit: 50,
          ...(after === undefined ? {} : { cursor: after }),
        });
        if (!mounted.current || current !== generation.current) return;
        setItems((old) =>
          after === undefined
            ? response.items
            : [
                ...old,
                ...response.items.filter(
                  (item) => !old.some((entry) => entry.revision_id === item.revision_id),
                ),
              ],
        );
        setCursor(response.next_cursor);
      } catch (failure) {
        if (mounted.current && current === generation.current) setError(toApiError(failure));
      } finally {
        if (mounted.current && current === generation.current) setLoading(false);
      }
    },
    [api, month, mounted],
  );
  useEffect(() => {
    // The ref is a request counter, so bumping its latest value on cleanup is intended.
    const counter = generation;
    void load();
    return () => {
      counter.current++;
    };
  }, [load, refresh]);
  return (
    <section className="card" aria-labelledby="month-history-title">
      <h2 id="month-history-title">확정·정정 이력</h2>
      <p>각 기록의 당시 범위와 금액을 별도로 확인할 수 있어요.</p>
      <MonthError error={error} />
      {loading && (
        <p className="loading-state" role="status">
          기록 이력을 불러오고 있어요.
        </p>
      )}
      <ol className="month-history">
        {items.map((item) => (
          <li key={item.revision_id}>
            <Link to={`/assets/months/${month}?revision=${item.revision_no}`}>
              {item.revision_no}차 기록 · {monthStates[item.state]}
            </Link>
            {item.reopened_reason && <p>정정 사유: {item.reopened_reason}</p>}
            {item.confirmed_at && (
              <p className="muted">확정 {formatSeoulDateTime(item.confirmed_at)}</p>
            )}
          </li>
        ))}
      </ol>
      <div className="form-actions">
        <button type="button" disabled={loading} onClick={() => void load()}>
          기록 이력 다시 불러오기
        </button>
        {cursor !== null && (
          <button type="button" disabled={loading} onClick={() => void load(cursor)}>
            기록 이력 더 보기
          </button>
        )}
      </div>
    </section>
  );
}

type Panel = { type: "confirm" | "reopen" | "sync" | "carry"; initial: MonthRecord };
function MonthWorkspace({
  month,
  revisionNo,
  setEditing,
}: {
  month: string;
  revisionNo?: number;
  setEditing: (editing: boolean) => void;
}) {
  const api = useAssetMonthsApi();
  const mounted = useMounted();
  const members = useHouseholdMembers();
  const [record, setRecord] = useState<MonthRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [editor, setEditor] = useState<EditingValue | null>(null);
  const [panel, setPanel] = useState<Panel | null>(null);
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  // After the editor closes (cancel or save), focus returns to the row that opened it.
  const returnFocusTo = useRef<string | null>(null);
  function closeEditor() {
    returnFocusTo.current = editor?.row.asset_id ?? null;
    setEditor(null);
  }
  useEffect(() => {
    const id = returnFocusTo.current;
    if (editor || id === null) return;
    const row = document.querySelector<HTMLButtonElement>(`[data-month-row="${CSS.escape(id)}"]`);
    // A save reloads the month and briefly disables the rows; wait for that to settle.
    if (row?.disabled && loading) return;
    returnFocusTo.current = null;
    (row && !row.disabled ? row : document.getElementById("month-values-title"))?.focus();
  }, [editor, loading]);
  const reload = useCallback(async (): Promise<MonthRecord> => {
    const current = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const result = await api.all(month, undefined, revisionNo);
      if (mounted.current && current === generation.current) setRecord(result);
      return result;
    } catch (failure) {
      if (mounted.current && current === generation.current) {
        const value = toApiError(failure);
        setError(value);
        if (value.status === 404) setRecord(null);
      }
      throw failure;
    } finally {
      if (mounted.current && current === generation.current) setLoading(false);
    }
  }, [api, month, revisionNo, mounted]);
  useEffect(() => {
    // The ref is a request counter, so bumping its latest value on cleanup is intended.
    const counter = generation;
    void reload().catch(() => undefined);
    return () => {
      counter.current++;
    };
  }, [reload]);
  useEffect(() => {
    setEditing(Boolean(editor || panel));
    return () => setEditing(false);
  }, [editor, panel, setEditing]);
  function saved(result: components["schemas"]["MonthValueResult"], revisionId: string) {
    setRecord((current) =>
      current?.revision_id === revisionId
        ? {
            ...current,
            version: result.revision_version,
            totals: result.totals,
            values: current.values.map((row) =>
              row.asset_id === result.value.asset_id ? result.value : row,
            ),
          }
        : current,
    );
    closeEditor();
    setNotice("확인한 금액과 기준일을 저장했어요.");
    void reload().catch(() => undefined);
  }
  if (loading && !record) return <p role="status">월 기록을 불러오고 있어요.</p>;
  if (!record)
    return (
      <>
        {error?.code === "MONTH_NOT_FOUND" && revisionNo === undefined ? (
          <CreateMonthDraft month={month} reload={reload} />
        ) : (
          <>
            <MonthError error={error} />
            <button type="button" onClick={() => void reload().catch(() => undefined)}>
              월 기록 다시 확인
            </button>
          </>
        )}
      </>
    );
  const readOnly = revisionNo !== undefined || record.state === "confirmed";
  const locked = Boolean(editor || panel || loading || error);
  const nextUnverified = record.values.find(
    (row) => row.inclusion_status === "included" && row.verification_state !== "verified",
  );
  return (
    <>
      {notice && <p role="status">{notice}</p>}
      <MonthError error={error} />
      {revisionNo !== undefined && (
        <section className="card">
          <h2>{record.revision_no}차 기록 조회</h2>
          <p>이 화면에서는 선택한 기록을 읽기만 해요. 이전 확정값과 당시 지분·범위는 보존돼요.</p>
          <Link className="button-link" to={`/assets/months/${month}`}>
            현재 월 기록으로 돌아가기
          </Link>
        </section>
      )}
      {!readOnly && nextUnverified && (
        <div className="primary-action-row">
          <button
            type="button"
            className="primary-button"
            disabled={locked}
            onClick={() => {
              setNotice("");
              setEditor({ revisionId: record.revision_id, row: nextUnverified });
            }}
          >
            미확인 항목 확인하기
          </button>
          <span className="muted">
            {record.totals.verified_count} / {record.totals.item_count}개 확인
          </span>
        </div>
      )}
      <MonthSummary record={record} />
      {record.state === "reopened" && (
        <section className="card">
          <h2>과거 범위를 유지하는 정정본</h2>
          <p>
            이전 확정 당시의 이름·소유 관계·지분·금액 기준·포함 여부를 유지해요. 현재 자산
            기본정보를 반영하려면 별도 범위 검토를 선택해 주세요.
          </p>
        </section>
      )}
      {record.scope_stale && (
        <p className="month-warning">
          현재 자산 기본정보와 이 기록의 범위가 달라요.
          {record.state === "draft"
            ? " 확정 전에 자산 범위 반영을 검토해야 해요."
            : " 정정본은 과거 범위를 유지한 채 확정할 수 있어요."}
        </p>
      )}
      <MemberLoadError error={members.error} retry={members.retry} />
      <div className="form-actions">
        <button
          type="button"
          disabled={loading || Boolean(panel)}
          onClick={() => void reload().catch(() => undefined)}
        >
          현재 월 기록 다시 불러오기
        </button>
        {revisionNo === undefined &&
          (record.state === "confirmed" ? (
            <button
              type="button"
              disabled={locked}
              onClick={() => setPanel({ type: "reopen", initial: record })}
            >
              정정 사유 남기고 다시 열기
            </button>
          ) : (
            <>
              {record.values.some(untouchedMissing) && (
                <button
                  type="button"
                  disabled={locked}
                  onClick={() => setPanel({ type: "carry", initial: record })}
                >
                  전월 확정값 불러오기 검토
                </button>
              )}
              <button
                type="button"
                disabled={locked}
                onClick={() => setPanel({ type: "sync", initial: record })}
              >
                현재 자산 범위 반영 검토
              </button>
              <button
                type="button"
                disabled={
                  locked ||
                  record.totals.provisional ||
                  (record.state === "draft" && record.scope_stale)
                }
                onClick={() => setPanel({ type: "confirm", initial: record })}
              >
                월 확정 검토
              </button>
            </>
          ))}
      </div>
      {editor && (
        <MonthRowEditor
          key={editor.row.asset_id}
          month={month}
          initial={editor}
          members={members.members}
          reload={reload}
          saved={saved}
          close={closeEditor}
        />
      )}
      {panel?.type === "confirm" && (
        <ConfirmMonth initial={panel.initial} reload={reload} close={() => setPanel(null)} />
      )}
      {panel?.type === "reopen" && (
        <ReopenMonth initial={panel.initial} reload={reload} close={() => setPanel(null)} />
      )}
      {panel?.type === "carry" && (
        <CarryPreviousMonth initial={panel.initial} reload={reload} close={() => setPanel(null)} />
      )}
      {panel?.type === "sync" && (
        <SynchronizeMonthScope
          members={members.members}
          initial={panel.initial}
          reload={reload}
          close={() => setPanel(null)}
        />
      )}
      <SnapshotList
        record={record}
        members={members.members}
        readOnly={readOnly}
        locked={locked}
        edit={(row) => {
          setNotice("");
          setEditor({ revisionId: record.revision_id, row });
        }}
      />
      <MonthHistory month={month} refresh={`${record.revision_id}:${record.state}`} />
    </>
  );
}

export function AssetMonthPage() {
  const { month = "" } = useParams();
  const [params] = useSearchParams();
  const { setMonth } = useMonth();
  const { state } = useAuth();
  const navigate = useNavigate();
  const id = useId();
  const [editing, setEditing] = useState(false);
  const revision = params.get("revision");
  const validRevision =
    revision === null ||
    (/^[1-9][0-9]{0,8}$/.test(revision) && Number.isSafeInteger(Number(revision)));
  useEffect(() => {
    if (isValidMonth(month)) setMonth(month);
  }, [month, setMonth]);
  if (!isValidMonth(month) || !validRevision)
    return (
      <>
        <div className="intro">
          <h1>월을 확인해 주세요</h1>
          <p>올바른 연도·월과 기록 번호로 이동해 주세요.</p>
        </div>
        <Link to="/assets">자산 목록으로</Link>
      </>
    );
  return (
    <>
      <div className="intro">
        <p className="eyebrow">우리 집의 월말 확인</p>
        <h1>월별 자산 확인</h1>
        <p>
          금액을 실제로 확인한 날짜와 함께 기록해요. 수입·납부·보험금 입력으로 잔액을 자동 가감하지
          않아요.
        </p>
      </div>
      <div className="month-picker">
        <div className="month-control">
          <label htmlFor={id}>확인할 월</label>
          <input
            id={id}
            type="month"
            min="0001-01"
            max="9999-12"
            value={month}
            disabled={editing}
            onChange={(event) => {
              if (isValidMonth(event.target.value))
                navigate(`/assets/months/${event.target.value}`);
            }}
          />
        </div>
        <span className="muted">서울 기준 · {formatMonth(month)}</span>
      </div>
      {editing && (
        <p className="muted">입력이나 검토를 마치고 닫으면 다른 월로 이동할 수 있어요.</p>
      )}
      {state.status !== "authenticated" ? (
        <SessionStatus />
      ) : (
        <MonthWorkspace
          key={`${month}:${revision ?? "current"}`}
          month={month}
          revisionNo={revision === null ? undefined : Number(revision)}
          setEditing={setEditing}
        />
      )}
    </>
  );
}
