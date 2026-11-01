import { useAuth } from "../auth/AuthProvider";
import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import type { components } from "@sallimbook/api-client";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import type { ApiError } from "../../platform/api";
import { AmountField } from "../../shared/AmountField";
import { parseKrwInput } from "../../shared/krw";
import { formatKrw } from "../assets/months/model";
import { useIdempotencyKey, useMonthCommand } from "../assets/months/useMonthCommand";
import { AuthenticatedFinance, CashflowError, SaveControls } from "../finance/FinancialFeedback";
import { useHouseholdMembers } from "../finance/FinanceSupport";
import type { HouseholdMember } from "../finance/FinanceSupport";
import { todaySeoul } from "../finance/dates";
import { allPages, useResource } from "../finance/queries";
import { useUnsavedChangesGuard } from "../../shared/UnsavedChanges";
import { useIncomeApi } from "./api";
import { usePlanningApi } from "./planningApi";

type S = components["schemas"];
type Expected = S["ExpectedResponse"];
type Bonus = S["BonusResponse"];
const kinds = { tai_h1: "TAI 상반기", tai_h2: "TAI 하반기", opi: "OPI" };
const money = (value: string | null | undefined) => (value == null ? "미확인" : formatKrw(value));
function parse(value: string) {
  if (!value.trim()) return null;
  const parsed = parseKrwInput(value);
  return parsed.ok ? parsed.krw : undefined;
}
type EditTarget = { kind: "expected" | "bonus"; id: string | null };
/** `?edit=expected`, `?edit=bonus:<id>`: the editor is a history step, so Back closes it. */
function parseTarget(value: string | null): EditTarget | null {
  const [kind, id] = (value ?? "").split(":");
  return kind === "expected" || kind === "bonus" ? { kind, id: id || null } : null;
}
function IncomePlanning() {
  const api = usePlanningApi();
  const incomeApi = useIncomeApi();
  const members = useHouseholdMembers();
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const data = useResource(
    useCallback(async () => {
      const [expected, bonuses] = await Promise.all([
        allPages(api.expected),
        allPages(api.bonuses),
      ]);
      return { expected, bonuses };
    }, [api]),
  );
  // The household totals come from the server, the same figures the home summary shows.
  const baseline = useResource(
    useCallback(() => incomeApi.summary(todaySeoul().slice(0, 7)), [incomeApi]),
  );
  const name = (id: string) =>
    members.members.find((m) => m.member_id === id)?.display_name ?? "구성원";
  const expected = data.data?.expected ?? [];
  const bonuses = data.data?.bonuses ?? [];
  const active = expected.filter((r) => r.active);
  const ended = expected.filter((r) => !r.active);
  const years = [...new Set(bonuses.map((r) => r.performance_year))].sort((a, b) => b - a);
  const target = parseTarget(params.get("edit"));
  const source =
    target?.kind === "expected"
      ? expected.find((r) => r.id === target.id)
      : bonuses.find((r) => r.id === target?.id);
  const editing = !!target && (target.id === null || !!source);
  function openEditor(kind: EditTarget["kind"], id?: string) {
    setParams(
      (old) => {
        old.set("edit", id ? `${kind}:${id}` : kind);
        return old;
      },
      { state: { planningEditor: true }, preventScrollReset: true },
    );
  }
  function closeEditor() {
    if ((location.state as { planningEditor?: boolean } | null)?.planningEditor) navigate(-1);
    else
      setParams(
        (old) => {
          old.delete("edit");
          return old;
        },
        { replace: true, preventScrollReset: true },
      );
  }
  async function refresh() {
    await Promise.all([data.reload(), baseline.reload()]);
  }
  async function saved() {
    closeEditor();
    await refresh();
  }
  return (
    <>
      <div className="form-actions plan-toolbar">
        <Link to="/income">월별 실제 수입 보기</Link>
        <button
          type="button"
          className="secondary-button quiet-button"
          disabled={data.loading}
          onClick={() => void refresh()}
        >
          최신 수입 기준 다시 확인
        </button>
      </div>
      <CashflowError error={data.error ?? members.error} />
      {data.loading && <p role="status">수입 기준을 확인하고 있어요.</p>}
      {/* A refresh keeps an open editor and its draft; the editor keeps its own source version. */}
      {editing ? (
        <PlanningEditor
          key={source?.id ?? target.kind}
          kind={target.kind}
          source={source}
          members={members.members}
          onSaved={() => void saved()}
          onCancel={closeEditor}
        />
      ) : (
        <>
          <section className="card planning-section">
            <div className="item-heading">
              <h2>현재 예상 월 수입</h2>
              <button
                type="button"
                className="primary-button"
                disabled={!!data.error || data.loading}
                onClick={() => openEditor("expected")}
              >
                예상 수입 추가
              </button>
            </div>
            <p className="muted">
              실제 입금 기록과 별도로 관리해요. 이 금액으로 과거 월 수입이나 자산 잔액을 자동
              변경하지 않아요.
            </p>
            {!data.error && (
              <BaselineTotals
                summary={baseline.data?.expected}
                error={baseline.error}
                retry={() => void baseline.reload()}
                members={members.members}
              />
            )}
            <ul className="record-list">
              {active.map((r) => (
                <ExpectedRow
                  key={r.id}
                  row={r}
                  name={name(r.member_id)}
                  onEdit={() => openEditor("expected", r.id)}
                />
              ))}
            </ul>
            {data.data && !active.length && (
              <p className="muted">매달 예상하는 월급과 부수입을 추가해 보세요.</p>
            )}
            {ended.length > 0 && (
              <details className="history-disclosure">
                <summary>종료된 예상 수입 {ended.length}개</summary>
                <ul className="record-list">
                  {ended.map((r) => (
                    <ExpectedRow
                      key={r.id}
                      row={r}
                      name={name(r.member_id)}
                      onEdit={() => openEditor("expected", r.id)}
                    />
                  ))}
                </ul>
              </details>
            )}
          </section>
          <section className="card planning-section">
            <div className="item-heading">
              <h2>성과연도별 상여</h2>
              <button
                type="button"
                className="primary-button"
                disabled={!!data.error || data.loading}
                onClick={() => openEditor("bonus")}
              >
                상여 상세 추가
              </button>
            </div>
            <p className="muted">
              세전 금액, 세후 현금과 수령 당시 주식 평가액을 나누어 보존해요. 주식 금액은 현재
              평가액이 아니에요.
            </p>
            {years.map((year) => {
              const rows = bonuses
                .filter((r) => r.performance_year === year)
                .sort((a, b) => a.award_kind.localeCompare(b.award_kind));
              const current = rows.filter((r) => r.active);
              const voided = rows.filter((r) => !r.active);
              const sum = (field: "net_cash_krw" | "stock_grant_value_krw") =>
                current.reduce((n, r) => n + BigInt(r[field] ?? "0"), 0n);
              return (
                <section key={year} aria-label={`${year}년 성과 상여`}>
                  <h3>{year}년 성과</h3>
                  <p>
                    확인된 세후 현금 {money(sum("net_cash_krw").toString())} · 주식 수령가액{" "}
                    {money(sum("stock_grant_value_krw").toString())} · 합계{" "}
                    {money((sum("net_cash_krw") + sum("stock_grant_value_krw")).toString())}
                  </p>
                  <p className="muted">
                    현금 미확인 {current.filter((r) => r.net_cash_krw == null).length}건 · 주식
                    미확인 {current.filter((r) => r.stock_grant_value_krw == null).length}건
                  </p>
                  <ul className="record-list">
                    {current.map((r) => (
                      <BonusRow
                        key={r.id}
                        row={r}
                        name={name(r.member_id)}
                        onEdit={() => openEditor("bonus", r.id)}
                      />
                    ))}
                  </ul>
                  {voided.length > 0 && (
                    <details className="history-disclosure">
                      <summary>무효 처리한 상여 {voided.length}개</summary>
                      <ul className="record-list">
                        {voided.map((r) => (
                          <BonusRow
                            key={r.id}
                            row={r}
                            name={name(r.member_id)}
                            onEdit={() => openEditor("bonus", r.id)}
                          />
                        ))}
                      </ul>
                    </details>
                  )}
                </section>
              );
            })}
          </section>
        </>
      )}
    </>
  );
}
function BaselineTotals({
  summary,
  error,
  retry,
  members,
}: {
  summary: S["ExpectedIncomeSummary"] | undefined;
  error: ApiError | null;
  retry: () => void;
  members: HouseholdMember[];
}) {
  if (error)
    return (
      <>
        <CashflowError error={error} />
        <button type="button" className="secondary-button" onClick={retry}>
          예상 합계 다시 확인
        </button>
      </>
    );
  if (!summary) return null;
  return (
    <>
      <p className="planning-total">
        확인된 예상 합계 <strong>{formatKrw(summary.known_amount_krw)}</strong> · 미확인{" "}
        {summary.unknown_count}건
      </p>
      {summary.members.length > 1 && (
        <dl className="metric-strip planning-members">
          {summary.members.map((row) => (
            <div key={row.member_id}>
              <dt>
                {members.find((m) => m.member_id === row.member_id)?.display_name ?? "구성원"}
              </dt>
              <dd>
                {formatKrw(row.known_amount_krw)}
                {row.unknown_count > 0 && <small> · 미확인 {row.unknown_count}건</small>}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </>
  );
}
function ExpectedRow({ row, name, onEdit }: { row: Expected; name: string; onEdit: () => void }) {
  return (
    <li>
      <div className="item-heading">
        <h3>
          {name} · {row.label}
        </h3>
        <button type="button" className="secondary-button" onClick={onEdit}>
          예상 수입 수정
        </button>
      </div>
      <p className="record-facts">
        <span>
          <strong>{money(row.amount_krw)}</strong> / 월
        </span>
        {!row.active && <span>종료</span>}
      </p>
      {row.note && <p className="muted">{row.note}</p>}
    </li>
  );
}
function BonusRow({ row, name, onEdit }: { row: Bonus; name: string; onEdit: () => void }) {
  return (
    <li>
      <div className="item-heading">
        <h4>
          {name} · {kinds[row.award_kind]}
        </h4>
        <button type="button" className="secondary-button" onClick={onEdit}>
          상여 상세 수정
        </button>
      </div>
      <dl className="metadata-grid compact-metadata">
        <div>
          <dt>지급월</dt>
          <dd>
            {row.payment_month ?? "미확인"} · {row.received ? "수령 확인" : "수령 미확인"}
          </dd>
        </div>
        <div>
          <dt>세전</dt>
          <dd>{money(row.gross_krw)}</dd>
        </div>
        <div>
          <dt>세후 현금</dt>
          <dd>{money(row.net_cash_krw)}</dd>
        </div>
        <div>
          <dt>수령 당시 주식 평가액</dt>
          <dd>{money(row.stock_grant_value_krw)}</dd>
        </div>
        <div>
          <dt>지급률</dt>
          <dd>{row.payout_rate_percent == null ? "미확인" : `${row.payout_rate_percent}%`}</dd>
        </div>
      </dl>
      {!row.active && <p>무효 처리됨</p>}
      {row.note && <p className="muted">{row.note}</p>}
      {row.cash_record_id && (
        <p>
          <Link to={`/income/${row.cash_record_id}`}>지급월에 연결된 실제 현금 수입</Link>
        </p>
      )}
    </li>
  );
}
function PlanningEditor({
  kind,
  source: serverSource,
  members,
  onSaved,
  onCancel,
}: {
  kind: "expected" | "bonus";
  source?: Expected | Bonus;
  members: ReturnType<typeof useHouseholdMembers>["members"];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const api = usePlanningApi(),
    command = useMonthCommand();
  // Keep the source revision with the draft; a background refresh must not rebase unsaved input.
  const [source] = useState(serverSource);
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const expected = source && "label" in source ? source : undefined,
    bonus = source && "award_kind" in source ? source : undefined;
  const { state: auth } = useAuth();
  const [member, setMember] = useState(
    source?.member_id ?? (auth.status === "authenticated" ? auth.member.member_id : ""),
  );
  const [label, setLabel] = useState(expected?.label ?? "");
  const [amount, setAmount] = useState(expected?.amount_krw ?? "");
  const [year, setYear] = useState(bonus?.performance_year.toString() ?? "");
  const [award, setAward] = useState<S["BonusInput"]["award_kind"]>(bonus?.award_kind ?? "tai_h1");
  const [month, setMonth] = useState(bonus?.payment_month ?? "");
  const [gross, setGross] = useState(bonus?.gross_krw ?? ""),
    [cash, setCash] = useState(bonus?.net_cash_krw ?? ""),
    [stock, setStock] = useState(bonus?.stock_grant_value_krw ?? "");
  const [rate, setRate] = useState(bonus?.payout_rate_percent ?? "");
  const [received, setReceived] = useState(bonus?.received ?? false),
    [active, setActive] = useState(source?.active ?? true);
  const [note, setNote] = useState(source?.note ?? ""),
    [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const fingerprint = JSON.stringify([
    source?.id,
    source?.version,
    member,
    label,
    amount,
    year,
    award,
    month,
    gross,
    cash,
    stock,
    rate,
    received,
    active,
    note,
    reason,
  ]);
  const key = useIdempotencyKey(fingerprint);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const common = { member_id: member, active, note: note.trim() || null };
    if (
      !member ||
      (source && (kind === "bonus" || !active) && !reason.trim()) ||
      (kind === "expected"
        ? !label.trim() || parse(amount) === undefined
        : !/^[0-9]{4}$/.test(year) ||
          Number(year) < 1900 ||
          Number(year) > 9998 ||
          [gross, cash, stock].some((v) => parse(v) === undefined) ||
          (rate && !/^(0|[1-9][0-9]{0,4})(\.[0-9]{1,2})?$/.test(rate)) ||
          (received && (!month || !cash.trim())))
    ) {
      setError("구성원·금액·연도와 정정 사유를 확인해 주세요. 미입력과 0원은 달라요.");
      return;
    }
    setError("");
    const result = await command.run<Expected | Bonus>((signal) =>
      kind === "expected"
        ? api.saveExpected(
            { ...common, label: label.trim(), amount_krw: parse(amount) ?? null },
            expected,
            reason.trim() || "예상 월 수입 수정",
            key,
            signal,
          )
        : api.saveBonus(
            {
              ...common,
              performance_year: Number(year),
              award_kind: award,
              payment_month: month || null,
              gross_krw: parse(gross) ?? null,
              net_cash_krw: parse(cash) ?? null,
              stock_grant_value_krw: parse(stock) ?? null,
              payout_rate_percent: rate || null,
              received,
            },
            bonus,
            reason.trim(),
            key,
            signal,
          ),
    );
    if (result.ok && command.mounted.current) {
      guard.release();
      onSaved();
    }
  }
  return (
    <section className="card">
      <h2>{kind === "expected" ? "예상 월 수입 입력" : "성과연도 상여 입력"}</h2>
      <form onInput={() => setDirty(true)} onSubmit={(e) => void submit(e)}>
        <fieldset disabled={command.busy}>
          <legend>입력 내용</legend>
          <label>
            구성원
            <select
              aria-label="구성원"
              value={member}
              onChange={(e) => setMember(e.target.value)}
              required
            >
              <option value="">선택해 주세요</option>
              {members.map((m) => (
                <option key={m.member_id} value={m.member_id}>
                  {m.display_name}
                </option>
              ))}
            </select>
          </label>
          {kind === "expected" ? (
            <>
              <label>
                수입 항목
                <input
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  maxLength={120}
                  required
                />
              </label>
              <AmountField
                label="예상 월 금액"
                value={amount}
                onChange={setAmount}
                hint="비워두면 미확인, 0은 0원이에요."
              />
            </>
          ) : (
            <>
              <label>
                성과연도
                <input
                  inputMode="numeric"
                  value={year}
                  onChange={(e) => setYear(e.target.value)}
                  maxLength={4}
                  required
                />
              </label>
              <label>
                상여 구분
                <select
                  aria-label="상여 구분"
                  value={award}
                  onChange={(e) => setAward(e.target.value as typeof award)}
                >
                  {Object.entries(kinds).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                실제 지급월
                <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
              </label>
              <p>
                TAI 상반기는 성과연도 7월, 하반기는 12월, OPI는 다음 해 1월을 기준으로 원본의
                지급월을 확인해 입력해 주세요.
              </p>
              <AmountField label="세전 금액" value={gross} onChange={setGross} />
              <AmountField label="세후 현금" value={cash} onChange={setCash} />
              <AmountField
                label="수령 당시 주식 평가액"
                value={stock}
                onChange={setStock}
                hint="현재 주가 평가액을 넣지 않아요. 비워두면 미확인, 0은 주식 수령액 0원이에요."
              />
              <label>
                지급률 (%)
                <input
                  inputMode="decimal"
                  value={rate}
                  onChange={(e) => setRate(e.target.value)}
                  maxLength={8}
                />
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={received}
                  onChange={(e) => setReceived(e.target.checked)}
                />
                실제 수령을 확인했으며, 양수 세후 현금을 지급월 수입에 연결할게요
              </label>
            </>
          )}
          <label className="checkbox-field">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            현재 유효한 기록
          </label>
          <p>
            해제하면 예상 합계에서 제외하고, 상여에 연결된 현금 수입은 사유를 남겨 무효 처리해요.
          </p>
          <label>
            메모
            <textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
          </label>
          {source && (
            <label>
              {kind === "expected" && active ? "변경 메모 (선택)" : "정정 사유"}
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                required={kind !== "expected" || !active}
                maxLength={500}
              />
            </label>
          )}
          {error && <p role="alert">{error}</p>}
          <CashflowError error={command.error} />
          {command.error?.status === 409 && (
            <p>
              내용이 변경되었거나 연결된 기록을 확인해야 해요. 입력을 취소한 뒤 최신 수입 기준을
              다시 확인해 주세요.
            </p>
          )}
        </fieldset>
        <SaveControls
          busy={command.busy}
          cancel={command.cancel}
          disabled={command.error?.status === 409}
          label="저장"
          onDismiss={onCancel}
        />
      </form>
    </section>
  );
}
export function IncomePlanningPage() {
  return (
    <AuthenticatedFinance
      title="예상 수입·성과연도 상여"
      description="예상 기준과 실제 지급 내역을 구분해 관리해요."
    >
      <IncomePlanning />
    </AuthenticatedFinance>
  );
}
