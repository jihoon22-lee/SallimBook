import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { toApiError } from "../../platform/api";
import { useIdempotencyKey, useMonthCommand } from "../assets/months/useMonthCommand";
import { formatKrw, parseKrw } from "../assets/months/model";
import { CashflowError, SaveControls } from "../finance/FinancialFeedback";
import { isDateOnly, isUuid, todaySeoul, dateLabel } from "../finance/dates";
import { allPages } from "../finance/queries";
import { useFixedApi } from "./api";
import { economicTypes, obligationStates, paymentSplit } from "./model";
import type { Obligation, Settlement } from "./model";
import { PaymentMethod } from "./PaymentMethod";
export type ObligationAction = "reschedule" | "skip" | "unskip" | "complete" | "reopen";
export const actionLabels: Record<ObligationAction, string> = {
  reschedule: "예정일 변경",
  skip: "회차 건너뛰기",
  unskip: "건너뛰기 되돌리기",
  complete: "수동 납부 완료",
  reopen: "수동 완료 재개",
};
export function actionAllowed(row: Obligation, action: ObligationAction): boolean {
  if (row.schedule_state !== "active") return false;
  if (action === "reopen") return row.manually_completed;
  if (action === "unskip") return row.skipped;
  if (action === "complete")
    return !row.skipped && !row.manually_completed && BigInt(row.actual_amount_krw) > 0n;
  return !row.skipped && !row.manually_completed && row.actual_amount_krw === "0";
}
function CurrentObligation({ row }: { row: Obligation }) {
  return (
    <p>
      현재 {obligationStates[row.status]} · 예정 {dateLabel(row.scheduled_date)} · 예정액{" "}
      {row.expected_amount_krw === null ? "미정" : formatKrw(row.expected_amount_krw)} · 실제{" "}
      {formatKrw(row.actual_amount_krw)} · {economicTypes[row.economic_type]} · 버전 {row.version}
    </p>
  );
}
export function ObligationActionForm({
  initial,
  action,
  onSaved,
  onBusyChange,
}: {
  initial: Obligation;
  action: ObligationAction;
  onSaved: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const api = useFixedApi();
  const command = useMonthCommand();
  useEffect(() => {
    onBusyChange?.(command.busy);
  }, [command.busy, onBusyChange]);
  const [row, setRow] = useState(initial);
  const [reason, setReason] = useState("");
  const [date, setDate] = useState(initial.scheduled_date);
  const [latest, setLatest] = useState<Obligation | null>(null);
  const valid =
    !!reason.trim() &&
    reason.length <= 500 &&
    actionAllowed(row, action) &&
    (action !== "reschedule" || (isDateOnly(date) && date !== row.scheduled_date));
  const payload =
    action === "reschedule"
      ? { scheduled_date: date, reason: reason.trim() }
      : { reason: reason.trim() };
  const key = useIdempotencyKey(JSON.stringify([row.id, row.version, action, payload]));
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    const result = await command.run((signal) =>
      action === "reschedule"
        ? api.reschedule(
            row.id,
            { reason: reason.trim(), scheduled_date: date },
            row.version,
            key,
            signal,
          )
        : api[action](row.id, { reason: reason.trim() }, row.version, key, signal),
    );
    if (result.ok && command.mounted.current) onSaved();
  }
  async function compare() {
    try {
      const current = await api.get(row.id);
      if (command.mounted.current) setLatest(current);
    } catch (error) {
      command.setError(toApiError(error));
    }
  }
  return (
    <section className="card">
      <h2>{actionLabels[action]}</h2>
      <CurrentObligation row={row} />
      {action === "complete" && (
        <p>
          기록한 실제 금액을 그대로 두고 이 회차의 납부를 완료 처리해요. 예정액과의 차이는 남아
          있어요.
        </p>
      )}
      <form onSubmit={(event) => void submit(event)}>
        <fieldset disabled={command.busy}>
          <legend>변경 내용</legend>
          {action === "reschedule" && (
            <div className="form-field">
              <label>
                변경할 예정일
                <input
                  type="date"
                  value={date}
                  onChange={(event) => setDate(event.target.value)}
                  required
                />
              </label>
            </div>
          )}
          <div className="form-field">
            <label>
              회차 변경 사유
              <textarea
                maxLength={500}
                required
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
          </div>
        </fieldset>
        <CashflowError error={command.error} />
        {command.error?.status === 409 && (
          <button type="button" onClick={() => void compare()}>
            현재 회차와 비교
          </button>
        )}
        {latest && (
          <section className="review-panel">
            <h3>현재 회차 확인</h3>
            <CurrentObligation row={latest} />
            <button
              type="button"
              disabled={!actionAllowed(latest, action)}
              onClick={() => {
                setRow(latest);
                setLatest(null);
                command.setError(null);
              }}
            >
              현재 회차를 확인하고 계속
            </button>
          </section>
        )}
        <SaveControls
          busy={command.busy}
          cancel={command.cancel}
          disabled={!valid}
          label={`${actionLabels[action]} 저장`}
        />
      </form>
    </section>
  );
}
export function SettlementForm({
  initial,
  onSaved,
  onBusyChange,
}: {
  initial: Obligation;
  onSaved: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const api = useFixedApi();
  const command = useMonthCommand();
  useEffect(() => {
    onBusyChange?.(command.busy);
  }, [command.busy, onBusyChange]);
  const [row, setRow] = useState(initial);
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const [principal, setPrincipal] = useState("");
  const [interest, setInterest] = useState("");
  const [method, setMethod] = useState<"none" | "account" | "card">(
    initial.card_id ? "card" : initial.account_id ? "account" : "none",
  );
  const [methodId, setMethodId] = useState(initial.card_id ?? initial.account_id ?? "");
  const [note, setNote] = useState("");
  const [latest, setLatest] = useState<Obligation | null>(null);
  const [reviewedChangedType, setReviewedChangedType] = useState(false);
  const split = paymentSplit(amount, principal, interest, row.economic_type);
  const parsed = parseKrw(amount);
  const allowed = row.schedule_state === "active" && !row.skipped && !row.manually_completed;
  const valid =
    allowed &&
    !!split &&
    isDateOnly(date) &&
    date <= todaySeoul() &&
    (method === "none" || isUuid(methodId));
  const payload = {
    amount_krw: parsed ?? "",
    occurred_on: date,
    principal_krw: split?.principal ?? "0",
    interest_krw: split?.interest ?? null,
    account_id: method === "account" ? methodId : null,
    card_id: method === "card" ? methodId : null,
    note: note.trim() || null,
  };
  const key = useIdempotencyKey(JSON.stringify([row.id, row.version, payload]));
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    const result = await command.run((signal) =>
      api.settle(row.id, payload, row.version, key, signal),
    );
    if (result.ok && command.mounted.current) onSaved();
  }
  async function compare() {
    try {
      const current = await api.get(row.id);
      if (command.mounted.current) {
        setLatest(current);
        setReviewedChangedType(false);
      }
    } catch (error) {
      command.setError(toApiError(error));
    }
  }
  return (
    <section className="card">
      <h2>실제 납부 기록</h2>
      <CurrentObligation row={row} />
      <p>
        한 회차를 여러 번 나누어 납부할 수 있어요. 예정액보다 적거나 많아도 실제 금액을 기록해요.
      </p>
      <form onSubmit={(event) => void submit(event)}>
        <fieldset disabled={command.busy}>
          <legend>실제로 납부한 내용</legend>
          <div className="form-grid">
            <div className="form-field">
              <label>
                실제 납부금액 (원)
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]+"
                  maxLength={20}
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  required
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                실제 납부일
                <input
                  type="date"
                  max={todaySeoul()}
                  value={date}
                  onChange={(event) => setDate(event.target.value)}
                  required
                />
              </label>
            </div>
            {row.economic_type === "loan" && (
              <>
                <div className="form-field">
                  <label>
                    실제 원금 상환액 (원)
                    <input
                      inputMode="numeric"
                      pattern="[0-9]+"
                      maxLength={20}
                      value={principal}
                      onChange={(event) => setPrincipal(event.target.value)}
                      required
                    />
                  </label>
                </div>
                <div className="form-field">
                  <label>
                    실제 이자 (원)
                    <input
                      inputMode="numeric"
                      pattern="[0-9]+"
                      maxLength={20}
                      value={interest}
                      onChange={(event) => setInterest(event.target.value)}
                      required
                    />
                  </label>
                </div>
                <p className="muted">
                  원금과 이자의 합계가 실제 납부액과 같아야 해요. 이자만 소비성 비용으로 분류하고
                  부채 잔액은 자동 변경하지 않아요.
                </p>
              </>
            )}
            {row.economic_type === "asset_transfer" && (
              <p className="muted">
                연금 납입 등 자산 이동으로 기록하며 소비성 비용은 0원이에요. 자산 평가액은 별도로
                확인해요.
              </p>
            )}
            <PaymentMethod
              method={method}
              id={methodId}
              onChange={(next, id) => {
                setMethod(next);
                setMethodId(id);
              }}
              on={date}
            />
            <div className="form-field">
              <label>
                납부 메모
                <textarea
                  maxLength={2000}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
              </label>
            </div>
          </div>
        </fieldset>
        <CashflowError error={command.error} />
        {command.error?.status === 409 && (
          <button type="button" onClick={() => void compare()}>
            납부 전 현재 회차 비교
          </button>
        )}
        {latest && (
          <section className="review-panel">
            <h3>납부 기준 다시 확인</h3>
            <CurrentObligation row={latest} />
            {latest.economic_type !== row.economic_type && (
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={reviewedChangedType}
                  onChange={(event) => setReviewedChangedType(event.target.checked)}
                />
                현재 납부 성격에 맞게 원금·이자 입력을 다시 확인할게요.
              </label>
            )}
            <button
              type="button"
              disabled={
                latest.schedule_state !== "active" ||
                latest.skipped ||
                latest.manually_completed ||
                (latest.economic_type !== row.economic_type && !reviewedChangedType)
              }
              onClick={() => {
                setRow(latest);
                setLatest(null);
                command.setError(null);
              }}
            >
              현재 납부 기준으로 계속
            </button>
          </section>
        )}
        <SaveControls
          busy={command.busy}
          cancel={command.cancel}
          disabled={!valid}
          label="실제 납부 저장"
        />
      </form>
    </section>
  );
}
export function VoidSettlement({
  initial,
  onSaved,
  onBusyChange,
}: {
  initial: Settlement;
  onSaved: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const api = useFixedApi();
  const command = useMonthCommand();
  useEffect(() => {
    onBusyChange?.(command.busy);
  }, [command.busy, onBusyChange]);
  const [payment, setPayment] = useState(initial);
  const [reason, setReason] = useState("");
  const [latest, setLatest] = useState<Settlement | null>(null);
  const key = useIdempotencyKey(JSON.stringify([payment.id, payment.cash.version, reason.trim()]));
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!reason.trim() || payment.cash.state !== "active") return;
    const result = await command.run((signal) =>
      api.voidPayment(payment.id, { reason: reason.trim() }, payment.cash.version, key, signal),
    );
    if (result.ok && command.mounted.current) onSaved();
  }
  async function compare() {
    try {
      const rows = await allPages((cursor) => api.payments(payment.obligation_id, cursor));
      if (command.mounted.current) setLatest(rows.find((row) => row.id === payment.id) ?? null);
    } catch (error) {
      command.setError(toApiError(error));
    }
  }
  return (
    <section className="card">
      <h2>실제 납부 무효 처리</h2>
      <p>
        {formatKrw(payment.cash.amount_krw)} · {dateLabel(payment.cash.occurred_on)} · 납부 원본
        버전 {payment.cash.version}
      </p>
      <p>잘못 기록한 납부를 무효로 남겨요. 예정 회차와 과거 이력을 삭제하지 않아요.</p>
      <form onSubmit={(event) => void submit(event)}>
        <div className="form-field">
          <label>
            납부 무효 사유
            <textarea
              maxLength={500}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              required
              disabled={command.busy}
            />
          </label>
        </div>
        <CashflowError error={command.error} />
        {command.error?.status === 409 && (
          <button type="button" onClick={() => void compare()}>
            현재 납부 기록과 비교
          </button>
        )}
        {latest && (
          <section className="review-panel">
            <p>
              현재 {latest.cash.state === "active" ? "활성" : "무효"} ·{" "}
              {formatKrw(latest.cash.amount_krw)} · 원본 버전 {latest.cash.version}
            </p>
            <button
              type="button"
              disabled={latest.cash.state !== "active"}
              onClick={() => {
                setPayment(latest);
                setLatest(null);
                command.setError(null);
              }}
            >
              현재 납부를 확인하고 계속
            </button>
          </section>
        )}
        <SaveControls
          busy={command.busy}
          cancel={command.cancel}
          disabled={!reason.trim() || payment.cash.state !== "active"}
          label="사유와 함께 납부 무효 처리"
        />
      </form>
    </section>
  );
}
