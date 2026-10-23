import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import { toApiError } from "../../../platform/api";
import { useIdempotencyKey, useMonthCommand } from "../../assets/months/useMonthCommand";
import { SaveControls } from "../../finance/FinancialFeedback";
import { useHouseholdMembers } from "../../finance/FinanceSupport";
import { usePagedList } from "../../finance/queries";
import { InsuranceError } from "../InsuranceSupport";
import { CashSummary } from "./EventSupport";
import { useInsuranceEventsApi } from "./api";
import { eventNames, needsCompare } from "./model";
import type { EventKind, EventRow } from "./model";
import { FormError, useSubmitAttempt } from "../../../shared/formValidation";
import { formatSeoulDateTime } from "../../../shared/format";
import { useUnsavedChangesGuard } from "../../../shared/UnsavedChanges";
export const getters = {
  expense: "getMedicalExpense",
  refund: "getMedicalRefund",
  payout: "getInsurancePayout",
  return: "getInsuranceReturn",
} as const;
const voiders = {
  expense: "voidMedicalExpense",
  refund: "voidMedicalRefund",
  payout: "voidInsurancePayout",
  return: "voidInsuranceReturn",
} as const;
const histories = {
  expense: "medicalExpenseHistory",
  refund: "medicalRefundHistory",
  payout: "insurancePayoutHistory",
  return: "insuranceReturnHistory",
} as const;
const historyKey = (row: { id: string; version: number }) => `${row.id}:${row.version}`;
export function EventCashHistory({ kind, id }: { kind: EventKind; id: string }) {
  const api = useInsuranceEventsApi();
  const members = useHouseholdMembers();
  const history = usePagedList(
    useCallback(
      (cursor?: number) =>
        api[histories[kind]]({
          resourceId: id,
          query: { limit: 50, ...(cursor ? { cursor } : {}) },
        }),
      [api, kind, id],
    ),
    historyKey,
  );
  return (
    <section className="card">
      <h2>{eventNames[kind]} 금전 이력</h2>
      <InsuranceError error={history.error} />
      {history.error && <button onClick={() => void history.reload()}>금전 이력 다시 확인</button>}
      <ol className="month-history">
        {history.items.map((row) => (
          <li key={historyKey(row)}>
            <h3>금전 기록 버전 {row.version}</h3>
            <CashSummary cash={row} />
            <p>
              {formatSeoulDateTime(row.updated_at)} ·{" "}
              {members.members.find((m) => m.member_id === row.updated_by_member_id)
                ?.display_name ?? "가계 구성원"}
            </p>
            {row.reason && <p>사유: {row.reason}</p>}
          </li>
        ))}
      </ol>
      {history.cursor !== null && (
        <button disabled={history.loading} onClick={() => void history.more()}>
          금전 이력 더 보기
        </button>
      )}
    </section>
  );
}
export function VoidEvent({
  kind,
  initial,
  saved,
  cancel,
}: {
  kind: EventKind;
  initial: EventRow;
  saved: () => void;
  cancel: () => void;
}) {
  const api = useInsuranceEventsApi();
  const command = useMonthCommand();
  const [base, setBase] = useState(initial);
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [latest, setLatest] = useState<EventRow | null>(null);
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const attempt = useSubmitAttempt();
  const key = useIdempotencyKey(JSON.stringify([kind, base.id, base.version, reason.trim()]));
  async function submit(event: FormEvent<HTMLFormElement>) {
    const form = event.currentTarget;
    event.preventDefault();
    if (base.cash.state !== "active" || needsCompare(command.error)) return;
    if (!reason.trim() || !ack) {
      setMessage("무효 사유와 확인란을 확인해 주세요.");
      attempt.reject(form);
      return;
    }
    const result = await command.run((signal) =>
      api[voiders[kind]](
        {
          resourceId: base.id,
          input: { reason: reason.trim() },
          ifMatch: `"${base.version}"`,
          idempotencyKey: key,
        },
        signal,
      ),
    );
    if (result.ok && command.mounted.current) {
      guard.release();
      saved();
    }
  }
  async function compare() {
    try {
      const row = await api[getters[kind]]({ resourceId: base.id });
      if (command.mounted.current) setLatest(row);
    } catch (error) {
      command.setError(toApiError(error));
    }
  }
  return (
    <section className="card">
      <h2>{eventNames[kind]} 무효 처리</h2>
      <p>오등록을 무효 이력으로 남겨요. 실제 환불·반환은 별도 금전 기록으로 입력해 주세요.</p>
      <CashSummary cash={base.cash} />
      <form
        onInput={() => {
          setMessage("");
          setDirty(true);
        }}
        onSubmit={(e) => void submit(e)}
      >
        <fieldset disabled={command.busy}>
          <legend>무효 사유와 확인</legend>
          <div className="form-field">
            <label>
              금전 기록 무효 사유
              <textarea
                required
                maxLength={500}
                value={reason}
                onChange={(e) => {
                  setReason(e.target.value);
                  setAck(false);
                }}
              />
            </label>
          </div>
          <label className="checkbox-field">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            실제 환불·반환이 아닌 오등록 무효임을 확인했어요.
          </label>
        </fieldset>
        <FormError message={message} />
        <InsuranceError error={command.error} />
        {needsCompare(command.error) && (
          <button type="button" onClick={() => void compare()}>
            무효 처리 전 원본 다시 비교
          </button>
        )}
        {latest && (
          <section className="review-panel">
            <CashSummary cash={latest.cash} />
            <p>현재 자원 버전 {latest.version}</p>
            <button
              type="button"
              disabled={latest.cash.state !== "active"}
              onClick={() => {
                setBase(latest);
                setLatest(null);
                setAck(false);
                command.setError(null);
              }}
            >
              현재 원본 확인 후 계속
            </button>
          </section>
        )}
        <SaveControls
          busy={command.busy}
          cancel={command.cancel}
          disabled={base.cash.state !== "active" || needsCompare(command.error)}
          label="사유와 함께 금전 기록 무효 처리"
        />
        <button type="button" onClick={cancel} disabled={command.busy}>
          무효 검토 닫기
        </button>
      </form>
    </section>
  );
}
