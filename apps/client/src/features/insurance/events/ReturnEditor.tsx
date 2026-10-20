import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router";
import { toApiError } from "../../../platform/api";
import { formatKrw } from "../../assets/months/model";
import { useIdempotencyKey, useMonthCommand } from "../../assets/months/useMonthCommand";
import { RecordedMoneyNotice, SaveControls } from "../../finance/FinancialFeedback";
import { allPages, useResource } from "../../finance/queries";
import { InsuranceError } from "../InsuranceSupport";
import { benefits, preserveDraft } from "../model";
import type { Schema } from "../model";
import { ActualFields, CashSummary } from "./EventSupport";
import { actualDraft, actualInput, eventNames, eventPaths, needsCompare } from "./model";
import { useInsuranceEventsApi } from "./api";
import { useUnsavedChangesGuard } from "../../../shared/UnsavedChanges";
type Parent = Schema["ExpenseResponse"] | Schema["PayoutResponse"];
type ReturnRow = Schema["RefundResponse"] | Schema["ReturnResponse"];
export function ReturnEditor({
  kind,
  initialParent,
  initial,
}: {
  kind: "refund" | "return";
  initialParent: Parent;
  initial?: ReturnRow;
}) {
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const api = useInsuranceEventsApi();
  const command = useMonthCommand();
  const navigate = useNavigate();
  const [parent, setParent] = useState(initialParent);
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => actualDraft(initial?.cash));
  const [allocation, setAllocation] = useState(
    initial && "original_allocation_id" in initial ? initial.original_allocation_id : "",
  );
  const [reason, setReason] = useState("");
  const [latest, setLatest] = useState<{ parent: Parent; base?: ReturnRow } | null>(null);
  const returns = useResource(
    useCallback(
      async (): Promise<ReturnRow[]> =>
        kind === "refund"
          ? allPages((cursor) =>
              api.listMedicalRefunds({
                resourceId: parent.id,
                query: { limit: 200, ...(cursor ? { cursor } : {}) },
              }),
            )
          : allPages((cursor) =>
              api.listInsuranceReturns({
                resourceId: parent.id,
                query: { limit: 200, ...(cursor ? { cursor } : {}) },
              }),
            ),
      [api, kind, parent.id],
    ),
  );
  const allocations = "allocations" in parent ? parent.allocations : [];
  const selected = allocations.find((row) => row.id === allocation);
  const ceiling = kind === "refund" ? parent.cash.amount_krw : selected?.amount_krw;
  const used =
    returns.data
      ?.filter(
        (row) =>
          row.cash.state === "active" &&
          row.id !== base?.id &&
          (kind === "refund" ||
            ("original_allocation_id" in row && row.original_allocation_id === allocation)),
      )
      .reduce((sum, row) => sum + BigInt(row.cash.amount_krw), 0n) ?? 0n;
  const remaining = ceiling === undefined ? null : (BigInt(ceiling) - used).toString();
  const actual = actualInput(draft);
  const ready =
    !!actual &&
    !!reason.trim() &&
    remaining !== null &&
    BigInt(actual.amount_krw) <= BigInt(remaining) &&
    !returns.loading &&
    !returns.error &&
    parent.cash.state === "active" &&
    (!base || base.cash.state === "active");
  const key = useIdempotencyKey(
    JSON.stringify([
      kind,
      base?.id ?? parent.id,
      base?.version ?? parent.version,
      actual,
      allocation,
      reason.trim(),
    ]),
  );
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!actual || !ready || needsCompare(command.error)) return;
    const result = await command.run((signal) => {
      const common = {
        resourceId: base?.id ?? parent.id,
        ifMatch: `"${base?.version ?? parent.version}"`,
        idempotencyKey: key,
      };
      if (kind === "refund") {
        const options = { ...common, input: { ...actual, reason: reason.trim() } };
        return base
          ? api.correctMedicalRefund(options, signal)
          : api.createMedicalRefund(options, signal);
      }
      const { card_id: _card, ...cash } = actual;
      const options = {
        ...common,
        input: { ...cash, original_allocation_id: allocation, reason: reason.trim() },
      };
      return base
        ? api.correctInsuranceReturn(options, signal)
        : api.createInsuranceReturn(options, signal);
    });
    if (result.ok && command.mounted.current) {
      guard.release();
      navigate(`/insurance/${eventPaths[kind]}/${result.value.id}`, { replace: true });
    }
  }
  async function compare() {
    try {
      const currentParent =
        kind === "refund"
          ? await api.getMedicalExpense({ resourceId: parent.id })
          : await api.getInsurancePayout({ resourceId: parent.id });
      const current = !base
        ? undefined
        : kind === "refund"
          ? await api.getMedicalRefund({ resourceId: base.id })
          : await api.getInsuranceReturn({ resourceId: base.id });
      if (command.mounted.current) setLatest({ parent: currentParent, base: current });
    } catch (error) {
      command.setError(toApiError(error));
    }
  }
  return (
    <section className="card">
      <h2>
        {eventNames[kind]} {base ? "원본 정정" : "기록"}
      </h2>
      <RecordedMoneyNotice />
      <p>
        {kind === "refund"
          ? "병원·약국이 실제 돌려준 금액을 의료비 원본에 연결해요."
          : "보험사에 실제 돌려준 금액을 원래 입금의 사건별 배분에 연결해요."}
      </p>
      <CashSummary cash={parent.cash} />
      <form onInput={() => setDirty(true)} onSubmit={(e) => void submit(e)}>
        {kind === "return" && (
          <div className="form-field">
            <label>
              반환할 원래 배분
              <select
                required
                value={allocation}
                disabled={command.busy}
                onChange={(e) => setAllocation(e.target.value)}
              >
                <option value="">원래 배분 선택</option>
                {allocations.map((row, index) => (
                  <option key={row.id} value={row.id}>
                    배분 {index + 1} · {benefits[row.benefit_type]} · {formatKrw(row.amount_krw)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        <p>
          현재 기록 기준 남은 {kind === "refund" ? "환불" : "반환"} 가능액:{" "}
          {remaining === null ? "원래 배분을 선택해 주세요" : formatKrw(remaining)}
        </p>
        <InsuranceError error={returns.error} />
        {returns.error && (
          <button type="button" onClick={() => void returns.reload()}>
            누적 {eventNames[kind]} 다시 확인
          </button>
        )}
        <ActualFields
          title={eventNames[kind]}
          draft={draft}
          onChange={setDraft}
          disabled={command.busy}
          accountOnly={kind === "return"}
        />
        {base && (
          <p className="muted">
            원래 {eventNames[kind]} 사유 “{base.reason}”은 그대로 남아요. 정정 사유는 금전 이력에
            기록돼요. 사유 자체가 틀렸다면 무효 처리 후 새로 기록해 주세요.
          </p>
        )}
        <div className="form-field">
          <label>
            {eventNames[kind]} {base ? "정정 사유" : "사유"}
            <textarea
              required
              maxLength={500}
              disabled={command.busy}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
        </div>
        {base && (
          <p>기존 {eventNames[kind]}은 무효로 보존하고 같은 부모 원본의 새 기록으로 정정해요.</p>
        )}
        <InsuranceError error={command.error} />
        {needsCompare(command.error) && (
          <button type="button" onClick={() => void compare()}>
            현재 원본과 누적액 비교
          </button>
        )}
        {latest && (
          <section className="review-panel">
            <CashSummary cash={latest.parent.cash} />
            {latest.base && <CashSummary cash={latest.base.cash} />}
            <button
              type="button"
              disabled={latest.parent.cash.state !== "active" || latest.base?.cash.state === "void"}
              onClick={() => {
                if (base && latest.base) {
                  setDraft(
                    preserveDraft(actualDraft(base.cash), draft, actualDraft(latest.base.cash)),
                  );
                  if (
                    "original_allocation_id" in base &&
                    "original_allocation_id" in latest.base &&
                    allocation === base.original_allocation_id
                  )
                    setAllocation(latest.base.original_allocation_id);
                  setBase(latest.base);
                }
                setParent(latest.parent);
                setLatest(null);
                command.setError(null);
                void returns.reload();
              }}
            >
              현재 원본 확인하고 입력 유지
            </button>
          </section>
        )}
        <SaveControls
          backTo={
            base
              ? `/insurance/${kind === "refund" ? "refunds" : "returns"}/${base.id}`
              : `/insurance/${kind === "refund" ? "expenses" : "payouts"}/${initialParent.id}`
          }
          busy={command.busy}
          cancel={command.cancel}
          disabled={!ready || needsCompare(command.error)}
          label={`${eventNames[kind]}${base ? " 정정" : ""} 저장`}
        />
      </form>
    </section>
  );
}
