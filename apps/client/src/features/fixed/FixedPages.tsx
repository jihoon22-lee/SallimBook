import { ExpensePlans } from "./ExpensePlans";
import { LastAuditActor } from "../audit/LastAuditActor";
import { NameSearch } from "../../shared/NameSearch";
import { RuleInsuranceLink, NamedReference } from "../finance/RelatedRecords";
import { TaskNotice, TaskPanel, useTaskPanelRelease } from "../../shared/TaskLayout";
import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { components } from "@sallimbook/api-client";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { stateFlag, useRouteNotice } from "../../shared/routeNotice";
import { MisregistrationDelete } from "../assets/MisregistrationDelete";
import { ApiError, toApiError } from "../../platform/api";
import { MonthPicker, useMonth, formatMonth } from "../../shared/MonthContext";
import { formatKrw, monthEnd } from "../assets/months/model";
import { signedKrw } from "../assets/comparison/model";
import { useIdempotencyKey, useMonthCommand } from "../assets/months/useMonthCommand";
import {
  AuthenticatedFinance,
  CashflowError,
  RecordedMoneyNotice,
  SaveControls,
} from "../finance/FinancialFeedback";
import { dateLabel, isDateOnly, isUuid, todaySeoul } from "../finance/dates";
import { allPages, usePagedList, useResource } from "../finance/queries";
import { useRefreshOnChange } from "./useRefreshOnChange";
import { useFixedApi } from "./api";
import {
  displayedTerms,
  economicTypes,
  generationValid,
  historyLabel,
  obligationStatusLabel,
  settlementEntry,
  withdrawalPlan,
} from "./model";
import type { Obligation, Rule, Settlement } from "./model";
import { RuleCommandError, RuleEditor, WithdrawalNotice } from "./RuleEditor";
import { RuleSummary } from "./RuleSummary";
import { BatchSettlement } from "./BatchSettlement";
import { ObligationCalendar } from "./ObligationCalendar";
import {
  actionAllowed,
  actionLabels,
  AdditionalPaymentCheck,
  ObligationActionForm,
  SettlementForm,
  VoidSettlement,
} from "./ObligationCommands";
import type { ObligationAction } from "./ObligationCommands";
import { FormError, useSubmitAttempt } from "../../shared/formValidation";
import { useUnsavedChangesGuard } from "../../shared/UnsavedChanges";
export function FixedSummaryPanel({ refresh = 0 }: { refresh?: number }) {
  const { month } = useMonth();
  return <FixedSummaryContent key={month} month={month} refresh={refresh} />;
}
function FixedSummaryContent({ month, refresh }: { month: string; refresh: number }) {
  const api = useFixedApi();
  const summary = useResource(useCallback(() => api.summary(month), [api, month]));
  useRefreshOnChange(summary.reload, refresh);
  return (
    <section
      className="card task-summary"
      aria-label="고정 납부 월 요약"
      aria-busy={summary.loading && Boolean(summary.data)}
    >
      <h2>{formatMonth(month)} 고정 납부</h2>
      <CashflowError error={summary.error} />
      {summary.error && (
        <button onClick={() => void summary.reload()}>고정 납부 요약 다시 확인</button>
      )}
      {summary.loading && (
        <p role="status">
          {summary.data
            ? "고정 납부 합계를 다시 확인하고 있어요."
            : "예정과 실제 납부를 확인하고 있어요."}
        </p>
      )}
      {summary.error && summary.data && (
        <p>아래는 마지막으로 확인한 합계예요. 다시 확인해 주세요.</p>
      )}
      {summary.data && (
        <>
          <dl className="metadata-grid compact-metadata">
            <div>
              <dt>금액이 정해진 예정</dt>
              <dd>{formatKrw(summary.data.expected_known_krw)}</dd>
            </div>
            <div>
              <dt>예정액 미정</dt>
              <dd>{summary.data.unknown_expected_count}개</dd>
            </div>
            <div>
              <dt>실제 납부액</dt>
              <dd>{formatKrw(summary.data.actual_amount_krw)}</dd>
            </div>
            <div>
              <dt>소비성 비용</dt>
              <dd>{formatKrw(summary.data.consumption_krw)}</dd>
            </div>
            <div>
              <dt>원금 상환</dt>
              <dd>{formatKrw(summary.data.principal_krw)}</dd>
            </div>
            <div>
              <dt>연금 등 자산 이동</dt>
              <dd>{formatKrw(summary.data.asset_transfer_krw)}</dd>
            </div>
          </dl>
          <p className="muted">
            예정은 선택 월의 예정일 기준 {summary.data.obligation_count}회차, 실제는 선택 월의
            납부일 기준이에요. 두 금액을 더하지 않아요.
          </p>
        </>
      )}
      <p className="muted">
        등록된 정기 결제 기준이에요. 카드 승인 계획을 카드 대금의 전체 출금액으로 표시하지 않아요.
      </p>
    </section>
  );
}
function GenerateForm({ month, onSaved }: { month: string; onSaved: () => void }) {
  const api = useFixedApi();
  const command = useMonthCommand();
  const release = useTaskPanelRelease();
  const [start, setStart] = useState(`${month}-01`);
  const [end, setEnd] = useState(monthEnd(month));
  const [rule, setRule] = useState("");
  const rules = useResource(
    useCallback(
      () => allPages((cursor) => api.rules({ limit: 200, ...(cursor ? { cursor } : {}) })),
      [api],
    ),
  );
  const payload = { start_date: start, end_date: end, rule_id: rule || null };
  const [sequence, setSequence] = useState(0);
  const key = useIdempotencyKey(JSON.stringify([payload, sequence]));
  const [done, setDone] = useState(false);
  const [message, setMessage] = useState("");
  const attempt = useSubmitAttempt();
  async function submit(event: FormEvent<HTMLFormElement>) {
    const form = event.currentTarget;
    event.preventDefault();
    if (!generationValid(start, end)) {
      setMessage("회차 생성 기간은 시작일부터 1년 이내로 정해 주세요.");
      attempt.reject(form);
      return;
    }
    const result = await command.run((signal) => api.generate(payload, key, signal));
    if (result.ok && command.mounted.current) {
      release();
      setDone(true);
      setSequence((value) => value + 1);
      onSaved();
    }
  }
  return (
    <section className="card">
      <h2>예정 회차 만들기</h2>
      <p>
        명시한 기간만 만들어요. 같은 규칙의 같은 회차는 다시 요청해도 중복 생성하지 않아요. 한 번에
        최대 366일이에요.
      </p>
      <form onInput={() => setMessage("")} onSubmit={(event) => void submit(event)}>
        <fieldset disabled={command.busy}>
          <legend>생성할 기간</legend>
          <div className="form-grid">
            <div className="form-field">
              <label>
                회차 생성 시작일
                <input
                  type="date"
                  value={start}
                  onChange={(event) => {
                    setStart(event.target.value);
                    setDone(false);
                  }}
                  required
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                회차 생성 종료일
                <input
                  type="date"
                  value={end}
                  onChange={(event) => {
                    setEnd(event.target.value);
                    setDone(false);
                  }}
                  required
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                생성할 규칙
                <select
                  value={rule}
                  disabled={rules.loading}
                  onChange={(event) => {
                    setRule(event.target.value);
                    setDone(false);
                  }}
                >
                  <option value="">모든 등록 규칙</option>
                  {rules.data?.map((row) => (
                    <option key={row.id} value={row.id}>
                      {displayedTerms(row).title}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
        </fieldset>
        <CashflowError error={rules.error} />
        {rules.error && (
          <button type="button" onClick={() => void rules.reload()}>
            규칙 목록 다시 확인
          </button>
        )}
        <FormError message={message} />
        <CashflowError error={command.error} />
        {done && (
          <p role="status">요청한 기간의 회차 생성을 확인했어요. 예정 월 목록에서 확인해 주세요.</p>
        )}
        <SaveControls
          busy={command.busy}
          cancel={command.cancel}
          disabled={rules.loading || !!rules.error}
          label="선택 기간 회차 생성"
        />
      </form>
    </section>
  );
}
export function ObligationSummary({
  row,
  showActor = false,
}: {
  row: Obligation;
  showActor?: boolean;
}) {
  return (
    <>
      <dl className="metadata-grid">
        <div>
          <dt>예정일</dt>
          <dd>
            {dateLabel(row.scheduled_date)}
            {row.manual_override ? " · 수동 예외" : ""}
          </dd>
        </div>
        <div>
          <dt>원래 규칙일</dt>
          <dd>{dateLabel(row.nominal_date)}</dd>
        </div>
        <div>
          <dt>예정액</dt>
          <dd>{row.expected_amount_krw === null ? "미정" : formatKrw(row.expected_amount_krw)}</dd>
        </div>
        <div>
          <dt>실제 납부 합계</dt>
          <dd>{formatKrw(row.actual_amount_krw)}</dd>
        </div>
        <div>
          <dt>실제 − 예정</dt>
          <dd>
            {row.difference_krw === null
              ? "예정액 미정으로 계산하지 않음"
              : signedKrw(row.difference_krw)}
          </dd>
        </div>
        <div>
          <dt>처리 상태</dt>
          <dd>
            {obligationStatusLabel(row)}
            {row.manually_completed ? " · 수동 완료" : ""}
          </dd>
        </div>
        <div>
          <dt>납부 성격</dt>
          <dd>{economicTypes[row.economic_type]}</dd>
        </div>
        <div>
          <dt>소비 / 원금 / 자산 이동</dt>
          <dd>
            {formatKrw(row.consumption_krw)} / {formatKrw(row.principal_krw)} /{" "}
            {formatKrw(row.asset_transfer_krw)}
          </dd>
        </div>
        <div>
          <dt>예정 수단</dt>
          <dd>
            {row.card_id ? (
              <NamedReference kind="cards" id={row.card_id} suffix=" · 카드 승인 계획" />
            ) : row.account_id ? (
              <NamedReference kind="accounts" id={row.account_id} suffix=" · 계좌 직접 납부 계획" />
            ) : (
              "수단 미지정"
            )}
          </dd>
        </div>
        {row.currency_reference && (
          <div>
            <dt>외화 참고</dt>
            <dd>
              {row.foreign_amount_reference} {row.currency_reference} · 자동 환산 없음
            </dd>
          </div>
        )}
      </dl>
      {showActor && <LastAuditActor kind="obligation" id={row.id} version={row.version} />}
      {row.note && <p>메모: {row.note}</p>}
    </>
  );
}
function PrepareMonth({ month, onSaved }: { month: string; onSaved: () => void }) {
  const api = useFixedApi();
  const command = useMonthCommand();
  const [sequence, setSequence] = useState(0);
  const [notice, setNotice] = useState("");
  const key = useIdempotencyKey(JSON.stringify([month, sequence]));
  useUnsavedChangesGuard(command.busy);
  async function prepare() {
    const result = await command.run((signal) =>
      api.generate(
        { start_date: `${month}-01`, end_date: monthEnd(month), rule_id: null },
        key,
        signal,
      ),
    );
    if (result.ok && command.mounted.current) {
      setNotice(
        `이달 예정 회차 ${result.value.items.length}건을 확인했어요. 실제 납부는 별도로 기록해 주세요.`,
      );
      setSequence((value) => value + 1);
      onSaved();
    }
  }
  return (
    <div>
      <button className="secondary-button" disabled={command.busy} onClick={() => void prepare()}>
        이달 예정 준비
      </button>
      <CashflowError error={command.error} />
      {notice && <p role="status">{notice}</p>}
    </div>
  );
}
function FixedList() {
  const { month } = useMonth();
  return <FixedMonthList key={month} month={month} />;
}
function FixedMonthList({ month }: { month: string }) {
  const api = useFixedApi();
  const [showBatch, setShowBatch] = useState(false);
  const [showGenerate, setShowGenerate] = useState(false);
  const [view, setView] = useState<"list" | "calendar">("list");
  const [refresh, setRefresh] = useState(0);
  const list = usePagedList(
    useCallback(
      (cursor?: string) => api.obligations({ month, limit: 50, ...(cursor ? { cursor } : {}) }),
      [api, month],
    ),
    undefined,
    "fixed-obligations",
  );
  function reload() {
    void list.reload();
    setRefresh((value) => value + 1);
  }
  return (
    <>
      <MonthPicker />
      <CashflowError error={list.error} />
      <div className="task-toolbar">
        <h2>{formatMonth(month)} 납부 목록</h2>
        <div className="segmented-control" role="group" aria-label="납부 보기 방식">
          <button aria-pressed={view === "list"} onClick={() => setView("list")}>
            목록 보기
          </button>
          <button aria-pressed={view === "calendar"} onClick={() => setView("calendar")}>
            달력 보기
          </button>
        </div>
        <button className="secondary-button" disabled={list.loading} onClick={reload}>
          월 납부 목록 다시 확인
        </button>
      </div>
      <div className="form-actions">
        <button
          className="secondary-button"
          disabled={showBatch || list.loading || Boolean(list.error)}
          onClick={() => setShowBatch(true)}
        >
          여러 회차 납부 입력 열기
        </button>
        <PrepareMonth key={month} month={month} onSaved={reload} />
      </div>
      {showBatch && (
        <TaskPanel label="선택 납부 입력">
          <BatchSettlement month={month} onSaved={reload} onClose={() => setShowBatch(false)} />
        </TaskPanel>
      )}
      {list.loading && (
        <p className="loading-state" role="status">
          납부 회차를 불러오고 있어요.
        </p>
      )}
      {!list.loading && !list.error && !list.items.length && (
        <section className="card empty-state">
          <h2>이 달의 회차가 없어요</h2>
          <p>
            규칙을 새로 저장하면 12개월의 예정을 준비해요. 이미 등록한 규칙은 ‘이달 예정 준비’를
            선택해 주세요. 실제 납부는 직접 기록해요.
          </p>
        </section>
      )}
      {view === "calendar" ? (
        <ObligationCalendar month={month} refresh={refresh} />
      ) : (
        <>
          <ul className="finance-list task-records">
            {list.items.map((row) => (
              <li key={row.id} className="card">
                <div className="record-main">
                  <div>
                    <span className="status-chip">{obligationStatusLabel(row)}</span>
                    <h2>
                      <Link to={`/fixed-payments/${row.id}`}>{row.title}</Link>
                    </h2>
                    <p className="record-subline">
                      {dateLabel(row.scheduled_date)} 예정
                      {row.manual_override ? " · 수동 예외" : ""}
                    </p>
                  </div>
                  {settlementEntry(row) === "settle" && (
                    <Link
                      className="button-link secondary-button"
                      to={`/fixed-payments/${row.id}?task=settle`}
                    >
                      납부 기록
                    </Link>
                  )}
                </div>
                <p className="record-facts">
                  <span>
                    예정{" "}
                    <strong>
                      {row.expected_amount_krw === null
                        ? "미정"
                        : formatKrw(row.expected_amount_krw)}
                    </strong>
                  </span>
                  <span>
                    실제 <strong>{formatKrw(row.actual_amount_krw)}</strong>
                  </span>
                </p>
                <details className="record-details">
                  <summary>납부 성격·수단·차액 상세</summary>
                  <ObligationSummary row={row} />
                </details>
              </li>
            ))}
          </ul>
          {list.cursor && (
            <button disabled={list.loading} onClick={() => void list.more()}>
              납부 회차 더 보기
            </button>
          )}
        </>
      )}
      <div className="form-actions">
        <Link className="button-link" to="/fixed-payments/rules/new">
          납부 규칙 등록
        </Link>
        <Link className="button-link secondary-button" to="/fixed-payments/rules">
          규칙과 적용기간 관리
        </Link>
        <button aria-expanded={showGenerate} onClick={() => setShowGenerate((value) => !value)}>
          예정 회차 생성 {showGenerate ? "닫기" : "열기"}
        </button>
      </div>
      {showGenerate && (
        <TaskPanel key={month} label="예정 회차 생성 입력">
          <GenerateForm month={month} onSaved={reload} />
        </TaskPanel>
      )}
      <FixedSummaryPanel refresh={refresh} />
      <RecordedMoneyNotice />
    </>
  );
}
function RuleList() {
  const api = useFixedApi();
  const [params] = useSearchParams();
  const q = params.get("q") ?? "";
  const list = usePagedList(
    useCallback(
      (cursor?: string) =>
        api.rules({ limit: 50, ...(q ? { q } : {}), ...(cursor ? { cursor } : {}) }),
      [api, q],
    ),
    undefined,
    "fixed-rules",
  );
  return (
    <>
      <NameSearch
        label="납부 규칙 이름·변경 이력 검색"
        hint="과거·예정 적용기간의 이름도 함께 찾아요."
      />
      <div className="form-actions">
        <Link className="button-link" to="/fixed-payments/rules/new">
          납부 규칙 등록
        </Link>
        <Link to="/fixed-payments">월별 납부 회차</Link>
      </div>
      <CashflowError error={list.error} />
      {list.error && <button onClick={() => void list.reload()}>규칙 목록 다시 확인</button>}
      {list.loading && (
        <p className="loading-state" role="status">
          규칙을 불러오고 있어요.
        </p>
      )}
      {!list.loading && !list.error && !list.items.length && <p>등록된 납부 규칙이 없어요.</p>}
      <ul className="finance-list">
        {list.items.map((row) => {
          const terms = displayedTerms(row);
          return (
            <li className="card" key={row.id}>
              <h2>
                <Link to={`/fixed-payments/rules/${row.id}`}>{terms.title}</Link>
              </h2>
              <p>
                {row.ended_on ? `종료 적용일 ${dateLabel(row.ended_on)}` : "계속 적용"} · 규칙 버전{" "}
                {row.version}
              </p>
              <RuleSummary terms={terms} />
            </li>
          );
        })}
      </ul>
      {list.cursor && (
        <button disabled={list.loading} onClick={() => void list.more()}>
          규칙 더 보기
        </button>
      )}
    </>
  );
}
function EndRule({ initial, onSaved }: { initial: Rule; onSaved: () => void }) {
  const api = useFixedApi();
  const command = useMonthCommand();
  const [row, setRow] = useState(initial);
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const [latest, setLatest] = useState<Rule | null>(null);
  const [ack, setAck] = useState(false);
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const attempt = useSubmitAttempt();
  const key = useIdempotencyKey(JSON.stringify([row.id, row.version, date, reason.trim()]));
  const plan = withdrawalPlan(row, date);
  const valid =
    (!row.ended_on || (row.ended_on > todaySeoul() && date < row.ended_on)) &&
    isDateOnly(date) &&
    date >= todaySeoul() &&
    date > plan.floor &&
    !!reason.trim() &&
    ack;
  async function submit(event: FormEvent<HTMLFormElement>) {
    const form = event.currentTarget;
    event.preventDefault();
    if (!valid) {
      setMessage(
        "종료 적용일·종료 사유·확인란을 확인해 주세요. 종료 적용일은 오늘 이후, 마지막 적용 시작일 뒤, 기존 종료일 전이어야 해요.",
      );
      attempt.reject(form);
      return;
    }
    const result = await command.run((signal) =>
      api.endRule(row.id, { effective_on: date, reason: reason.trim() }, row.version, key, signal),
    );
    if (result.ok && command.mounted.current) {
      guard.release();
      onSaved();
    }
  }
  async function compare() {
    try {
      const current = await api.rule(row.id);
      if (command.mounted.current) setLatest(current);
    } catch (error) {
      command.setError(toApiError(error));
    }
  }
  return (
    <section className="card">
      <h2>납부 규칙 종료</h2>
      <p>
        현재 적용 중인 시작일 {dateLabel(plan.floor)}보다 뒤의 종료 적용일을 선택해요. 과거 납부와
        수동 예외는 남겨요.
        {row.ended_on
          ? ` 현재 종료 적용일 ${dateLabel(row.ended_on)}보다 앞당기는 것만 가능해요.`
          : ""}
      </p>
      <form
        onInput={() => {
          setMessage("");
          setDirty(true);
        }}
        onSubmit={(event) => void submit(event)}
      >
        <fieldset disabled={command.busy}>
          <legend>종료 내용</legend>
          <div className="form-field">
            <label>
              규칙 종료 적용일
              <input
                type="date"
                value={date}
                min={todaySeoul()}
                onChange={(event) => {
                  setDate(event.target.value);
                  setAck(false);
                }}
                required
              />
            </label>
          </div>
          <div className="form-field">
            <label>
              규칙 종료 사유
              <textarea
                maxLength={500}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                required
              />
            </label>
          </div>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={ack}
              onChange={(event) => setAck(event.target.checked)}
            />
            종료 적용일 이후의 미래 미납 회차가 바뀌는 것을 확인했어요.
          </label>
        </fieldset>
        <WithdrawalNotice withdrawn={plan.withdrawn} />
        <RuleCommandError error={command.error} />
        {command.error?.status === 409 && (
          <button type="button" onClick={() => void compare()}>
            종료 전 현재 규칙 비교
          </button>
        )}
        {latest && (
          <section className="review-panel">
            <p>
              현재 규칙 버전 {latest.version} ·{" "}
              {latest.ended_on ? `종료 ${dateLabel(latest.ended_on)}` : "계속 적용"}
            </p>
            <RuleSummary terms={displayedTerms(latest)} />
            <LastAuditActor kind="recurring_rule" id={latest.id} version={latest.version} />
            <button
              type="button"
              disabled={!!latest.ended_on && latest.ended_on <= todaySeoul()}
              onClick={() => {
                setRow(latest);
                setLatest(null);
                setAck(false);
                command.setError(null);
              }}
            >
              현재 규칙 확인 후 계속
            </button>
          </section>
        )}
        <FormError message={message} />
        <SaveControls busy={command.busy} cancel={command.cancel} label="납부 규칙 종료 저장" />
      </form>
    </section>
  );
}
function RuleDetail({ id, edit }: { id: string; edit: boolean }) {
  const prepared = useRouteNotice((state) => {
    const value = (state as { prepared?: unknown } | null)?.prepared;
    return typeof value === "string" ? value : null;
  });
  const api = useFixedApi();
  const resource = useResource(
    useCallback(
      () => (isUuid(id) ? api.rule(id) : Promise.reject(new ApiError(404, "NOT_FOUND"))),
      [api, id],
    ),
  );
  const [ending, setEnding] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const navigate = useNavigate();
  const row = resource.data;
  const deleteKey = useIdempotencyKey(JSON.stringify(["rule-delete", row?.id, row?.version]));
  return (
    <>
      <TaskNotice message={prepared ?? ""} />
      <CashflowError error={resource.error} />
      {resource.error && <button onClick={() => void resource.reload()}>규칙 다시 확인</button>}
      {resource.loading && (
        <p className="loading-state" role="status">
          규칙과 적용기간을 불러오고 있어요.
        </p>
      )}
      {row && !resource.loading && !resource.error && (
        <>
          {edit ? (
            <RuleEditor initial={row} />
          ) : (
            <section className="card">
              <h2>{displayedTerms(row).title}</h2>
              <RuleSummary terms={displayedTerms(row)} />
              <LastAuditActor kind="recurring_rule" id={row.id} version={row.version} />
              <p>
                규칙 버전 {row.version}
                {row.ended_on ? ` · 종료 적용일 ${dateLabel(row.ended_on)}` : ""}
              </p>
              {row.end_reason && <p>종료 사유: {row.end_reason}</p>}
              <div className="form-actions">
                {(!row.ended_on || row.ended_on > todaySeoul()) && (
                  <Link className="button-link" to={`/fixed-payments/rules/${id}/edit`}>
                    규칙 적용기간 변경
                  </Link>
                )}
                {(!row.ended_on || row.ended_on > todaySeoul()) && (
                  <button
                    className="secondary-button"
                    onClick={() => {
                      setDeleting(false);
                      setEnding(true);
                    }}
                  >
                    {row.ended_on ? "규칙 종료일 앞당기기 검토" : "납부 규칙 종료 검토"}
                  </button>
                )}
                <Link to="/fixed-payments">월별 회차 확인</Link>
              </div>
              <details className="secondary-actions">
                <summary>규칙 삭제</summary>
                <div className="form-actions">
                  <button
                    type="button"
                    className="danger-button"
                    onClick={() => {
                      setEnding(false);
                      setDeleting(true);
                    }}
                  >
                    오등록 규칙 삭제 검토
                  </button>
                </div>
              </details>
            </section>
          )}
          {!edit && <RuleInsuranceLink ruleId={id} />}
          {deleting && (
            <MisregistrationDelete
              id="rule-delete"
              title="오등록 규칙 삭제 확인"
              ackLabel="잘못 등록한 규칙이며 회차와 함께 삭제할 것을 확인했어요."
              actionLabel="오등록 규칙 삭제"
              inUseCode="RULE_IN_USE"
              remove={() =>
                api.deleteRule(row.id, row.version, deleteKey, new AbortController().signal)
              }
              done={() =>
                navigate("/fixed-payments/rules", { replace: true, state: { deleted: "rule" } })
              }
              cancel={() => setDeleting(false)}
              reload={() => void resource.reload()}
            >
              <p>
                납부 기록이나 건너뛰기·예정일 변경 같은 처리 이력이 없고 확정한 월에 걸리지 않은
                오등록 규칙만 삭제할 수 있어요. 규칙의 적용기간과 예정 회차가 함께 지워져요. 납부한
                적이 있으면 규칙 종료를 이용해 주세요.
              </p>
            </MisregistrationDelete>
          )}
          {ending && (
            <>
              <EndRule
                initial={row}
                onSaved={() => {
                  setEnding(false);
                  void resource.reload();
                }}
              />
              <button className="secondary-button" onClick={() => setEnding(false)}>
                규칙 종료 취소
              </button>
            </>
          )}
          <section className="card">
            <h2>적용기간 이력</h2>
            <ol className="month-history">
              {row.versions.map((terms) => (
                <li key={terms.id}>
                  <h3>
                    {terms.title} · {dateLabel(terms.effective_from)} 적용
                  </h3>
                  <RuleSummary terms={terms} />
                  {terms.reason && <p>변경 사유: {terms.reason}</p>}
                </li>
              ))}
            </ol>
          </section>
        </>
      )}
    </>
  );
}
type History = components["schemas"]["ObligationHistoryItem"];
const historyKey = (row: History) => `${row.id}:${row.version}`;
function ObligationHistory({ id }: { id: string }) {
  const api = useFixedApi();
  const history = usePagedList(
    useCallback((cursor?: number) => api.history(id, cursor), [api, id]),
    historyKey,
  );
  return (
    <section className="card">
      <h2>회차 변경 이력</h2>
      <CashflowError error={history.error} />
      {history.error && <button onClick={() => void history.reload()}>회차 이력 다시 확인</button>}
      <ol className="month-history">
        {history.items.map((row) => (
          <li key={historyKey(row)}>
            <h3>
              버전 {row.version} · {historyLabel(row)}
            </h3>
            <p>
              예정일 {dateLabel(row.scheduled_date)} · 예정액{" "}
              {row.expected_amount_krw === null ? "미정" : formatKrw(row.expected_amount_krw)}
              {row.manual_override ? " · 수동 예외" : ""}
            </p>
            {row.reason && <p>사유: {row.reason}</p>}
          </li>
        ))}
      </ol>
      {history.cursor !== null && (
        <button disabled={history.loading} onClick={() => void history.more()}>
          회차 이력 더 보기
        </button>
      )}
    </section>
  );
}
function SettlementList({
  id,
  onSelect,
  refresh,
  locked = false,
}: {
  id: string;
  onSelect: (row: Settlement, trigger: HTMLButtonElement) => void;
  refresh: number;
  locked?: boolean;
}) {
  const api = useFixedApi();
  const list = usePagedList(
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `refresh` is a reload trigger; a new value must re-run the read.
    useCallback((cursor?: string) => api.payments(id, cursor), [api, id, refresh]),
  );
  return (
    <section className="card">
      <h2>실제 납부 내역</h2>
      <CashflowError error={list.error} />
      {list.error && <button onClick={() => void list.reload()}>실제 납부 다시 확인</button>}
      {!list.loading && !list.error && !list.items.length && (
        <p>아직 실제 납부를 기록하지 않았어요.</p>
      )}
      <ul className="finance-list">
        {list.items.map((payment) => (
          <li key={payment.id}>
            <h3>
              {formatKrw(payment.cash.amount_krw)} · {dateLabel(payment.cash.occurred_on)}
            </h3>
            <p>
              {payment.cash.state === "active" ? "활성 납부" : "무효 납부"} · 소비{" "}
              {formatKrw(payment.consumption_krw)} · 원금 {formatKrw(payment.principal_krw)} · 자산
              이동 {formatKrw(payment.asset_transfer_krw)}
            </p>
            <p>
              {payment.cash.card_id ? (
                <NamedReference kind="cards" id={payment.cash.card_id} suffix=" · 실제 납부 카드" />
              ) : payment.cash.account_id ? (
                <NamedReference
                  kind="accounts"
                  id={payment.cash.account_id}
                  suffix=" · 실제 납부 계좌"
                />
              ) : (
                "납부수단 연결 안 함"
              )}
            </p>
            {payment.cash.note && <p>메모: {payment.cash.note}</p>}
            {payment.cash.reason && <p>사유: {payment.cash.reason}</p>}
            {payment.cash.state === "active" && (
              <button
                className="secondary-button"
                disabled={locked}
                onClick={(event) => onSelect(payment, event.currentTarget)}
              >
                이 납부 무효 검토
              </button>
            )}
          </li>
        ))}
      </ul>
      {list.cursor && (
        <button disabled={list.loading} onClick={() => void list.more()}>
          실제 납부 더 보기
        </button>
      )}
    </section>
  );
}
function ObligationDetail({ id }: { id: string }) {
  const api = useFixedApi();
  const navigate = useNavigate();
  const previousSaved = useRouteNotice(stateFlag("previousPaymentSaved"));
  const nextCommand = useMonthCommand();
  const [nextMonth, setNextMonth] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();
  const actionTrigger = useRef<HTMLButtonElement>(null);
  const resource = useResource(
    useCallback(
      () => (isUuid(id) ? api.get(id) : Promise.reject(new ApiError(404, "NOT_FOUND"))),
      [api, id],
    ),
  );
  const [action, setAction] = useState<ObligationAction | "settle" | "">(() =>
    params.get("task") === "settle" ? "settle" : "",
  );
  const [commandBusy, setCommandBusy] = useState(false);
  const [voiding, setVoiding] = useState<Settlement | null>(null);
  const [notice, setNotice] = useState("");
  const row = resource.data;
  const entry = row ? settlementEntry(row) : null;
  const canSettle = entry !== null;
  // A paid occurrence shows the double-count check before the payment form.
  const [extraConfirmed, setExtraConfirmed] = useState(false);
  const currentAction = action === "settle" && !canSettle ? "" : action;
  function close(restoreFocus = true) {
    const target = actionTrigger.current;
    if (restoreFocus)
      requestAnimationFrame(() => {
        if (target?.isConnected) target.focus();
      });
    setAction("");
    setVoiding(null);
    setExtraConfirmed(false);
  }
  // Drop ?task= only after the closed panel unmounts, so its unsaved guard is gone first.
  useEffect(() => {
    if (action || nextMonth || !params.has("task")) return;
    const next = new URLSearchParams(params);
    next.delete("task");
    setParams(next, { replace: true });
  }, [action, nextMonth, params, setParams]);
  async function continueToNext(month: string) {
    const result = await nextCommand.run(() =>
      allPages((cursor) => api.obligations({ month, limit: 200, ...(cursor ? { cursor } : {}) })),
    );
    if (!result.ok || !nextCommand.mounted.current) return;
    const next = result.value.find(
      (item) =>
        item.id !== id &&
        item.status === "unpaid" &&
        item.actual_amount_krw === "0" &&
        item.schedule_state === "active" &&
        !item.skipped &&
        !item.manually_completed,
    );
    // Keep the old task URL intact until navigation unmounts this occurrence. Clearing
    // it in an effect while a fast native read navigates can otherwise win that race.
    if (next)
      navigate(`/fixed-payments/${next.id}?task=settle`, { state: { previousPaymentSaved: true } });
    else {
      setNextMonth(null);
      setNotice("실제 납부를 저장했어요. 이달에 이어서 입력할 미기록 회차가 없어요.");
    }
  }
  function saved(continueNext = false) {
    const message = voiding
      ? "납부 무효 처리를 저장했어요."
      : action === "settle"
        ? "실제 납부를 저장했어요. 아래 납부 내역에서 확인할 수 있어요."
        : "납부 회차 변경을 저장했어요.";
    setCommandBusy(false);
    close(false);
    setNotice(message);
    void resource.reload();
    if (continueNext && row) {
      const month = row.scheduled_date.slice(0, 7);
      setNextMonth(month);
      void continueToNext(month);
    }
  }
  return (
    <>
      <CashflowError error={resource.error} />
      <TaskNotice
        message={
          notice ||
          (previousSaved ? "이전 회차의 실제 납부를 저장했어요. 다음 회차를 확인해 주세요." : "")
        }
      />
      {nextMonth && (
        <section className="card" aria-label="다음 회차 확인">
          <p>납부는 저장됐어요. 다음 미기록 회차를 확인하고 있어요.</p>
          <CashflowError error={nextCommand.error} />
          {nextCommand.error && (
            <button disabled={nextCommand.busy} onClick={() => void continueToNext(nextMonth)}>
              다음 회차만 다시 확인
            </button>
          )}
        </section>
      )}
      {resource.error && <button onClick={() => void resource.reload()}>회차 다시 확인</button>}
      {resource.loading && (
        <p className="loading-state" role="status">
          {row ? "납부 회차를 다시 확인하고 있어요." : "현재 납부 회차를 불러오고 있어요."}
        </p>
      )}
      {resource.error && row && (
        <p>아래는 마지막으로 확인한 회차예요. 다시 확인한 뒤 작업해 주세요.</p>
      )}
      {row && (
        <>
          <section className="card" aria-busy={resource.loading}>
            <div className="item-heading">
              <h2>{row.title}</h2>
              <span className="status-chip">{obligationStatusLabel(row)}</span>
            </div>
            <p className="record-amount">
              {row.expected_amount_krw === null
                ? "예정액 미정"
                : formatKrw(row.expected_amount_krw)}
            </p>
            <p className="record-subline">
              {dateLabel(row.scheduled_date)} 예정 · 실제 납부 합계{" "}
              {formatKrw(row.actual_amount_krw)}
            </p>
            <div className="primary-action-row">
              {entry && (
                <button
                  ref={actionTrigger}
                  className={entry === "settle" ? "primary-button" : "secondary-button"}
                  disabled={
                    resource.loading ||
                    Boolean(resource.error || currentAction || voiding || nextMonth)
                  }
                  onClick={(event) => {
                    actionTrigger.current = event.currentTarget;
                    setAction("settle");
                    setVoiding(null);
                    setNotice("");
                  }}
                >
                  {entry === "settle" ? "실제 납부 기록" : "추가 납부 기록"}
                </button>
              )}
              <Link to={`/fixed-payments/rules/${row.rule_id}`}>납부 규칙과 적용기간</Link>
            </div>
            <details className="secondary-actions">
              <summary>예정일 변경·회차 관리</summary>
              <div className="form-actions">
                {(Object.keys(actionLabels) as ObligationAction[])
                  .filter((name) => actionAllowed(row, name))
                  .map((name) => (
                    <button
                      className="secondary-button"
                      key={name}
                      disabled={
                        resource.loading ||
                        Boolean(resource.error || currentAction || voiding || nextMonth)
                      }
                      onClick={(event) => {
                        actionTrigger.current = event.currentTarget;
                        setAction(name);
                        setVoiding(null);
                        setNotice("");
                      }}
                    >
                      {actionLabels[name]}
                    </button>
                  ))}
              </div>
            </details>
            <ObligationSummary row={row} showActor />
            <RecordedMoneyNotice />
          </section>
          {currentAction && (
            <TaskPanel
              key={`${id}:${row.version}:${currentAction}`}
              label={currentAction === "settle" ? "실제 납부 입력" : "납부 회차 변경 입력"}
            >
              {currentAction === "settle" ? (
                entry === "additional" && !extraConfirmed ? (
                  <AdditionalPaymentCheck row={row} onConfirm={() => setExtraConfirmed(true)} />
                ) : (
                  <SettlementForm initial={row} onSaved={saved} onBusyChange={setCommandBusy} />
                )
              ) : (
                <ObligationActionForm
                  initial={row}
                  action={currentAction}
                  onSaved={saved}
                  onBusyChange={setCommandBusy}
                />
              )}
              <div className="form-actions">
                <button className="secondary-button" disabled={commandBusy} onClick={() => close()}>
                  납부 작업 닫기
                </button>
              </div>
            </TaskPanel>
          )}
          {voiding && (
            <TaskPanel key={`${voiding.id}:${voiding.cash.version}`} label="납부 무효 입력">
              <VoidSettlement initial={voiding} onSaved={saved} onBusyChange={setCommandBusy} />
              <div className="form-actions">
                <button className="secondary-button" disabled={commandBusy} onClick={() => close()}>
                  납부 작업 닫기
                </button>
              </div>
            </TaskPanel>
          )}
          <SettlementList
            id={id}
            refresh={row.version}
            locked={
              resource.loading || Boolean(resource.error || currentAction || voiding || nextMonth)
            }
            onSelect={(payment, trigger) => {
              actionTrigger.current = trigger;
              setVoiding(payment);
              setAction("");
              setNotice("");
            }}
          />
          <ObligationHistory key={`${id}:${row.version}`} id={id} />
        </>
      )}
    </>
  );
}
export function FixedListPage() {
  const [params, setParams] = useSearchParams();
  const actual = params.get("view") === "payments";
  return (
    <AuthenticatedFinance title="고정 지출" description="월 계획을 한눈에 보고 필요할 때 수정해요.">
      <nav className="form-actions" aria-label="고정 지출 보기">
        <button
          aria-pressed={!actual}
          onClick={() =>
            setParams((old) => {
              old.delete("view");
              return old;
            })
          }
        >
          월 계획
        </button>
        <button
          aria-pressed={actual}
          onClick={() =>
            setParams((old) => {
              old.set("view", "payments");
              return old;
            })
          }
        >
          예정·실제 납부
        </button>
      </nav>
      {actual ? <FixedList /> : <ExpensePlans />}
    </AuthenticatedFinance>
  );
}
export function RuleListPage() {
  const deleted = useRouteNotice(stateFlag("deleted", "rule"));
  return (
    <AuthenticatedFinance
      title="납부 규칙 관리"
      description="주기와 적용기간을 관리하고 과거 규칙을 보존해요."
    >
      {deleted && <p role="status">납부 규칙을 삭제했어요.</p>}
      <RuleList />
    </AuthenticatedFinance>
  );
}
export function RuleNewPage() {
  return (
    <AuthenticatedFinance
      title="납부 규칙 등록"
      description="보험료·구독·통신비·원리금·연금 납입을 직접 설정해요."
    >
      <RuleEditor />
    </AuthenticatedFinance>
  );
}
export function RuleDetailPage({ edit = false }: { edit?: boolean }) {
  const { id = "" } = useParams();
  return (
    <AuthenticatedFinance
      title={edit ? "납부 규칙 변경" : "납부 규칙 상세"}
      description="적용기간과 변경 사유를 확인해요."
    >
      <RuleDetail key={`${id}:${edit}`} id={id} edit={edit} />
    </AuthenticatedFinance>
  );
}
export function FixedDetailPage() {
  const { id = "" } = useParams();
  return (
    <AuthenticatedFinance
      title="고정 납부 상세"
      description="한 회차의 예정과 실제 납부, 처리 이력을 확인해요."
    >
      <ObligationDetail key={id} id={id} />
    </AuthenticatedFinance>
  );
}
