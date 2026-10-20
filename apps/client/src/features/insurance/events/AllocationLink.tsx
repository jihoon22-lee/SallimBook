import { useCallback, useState } from "react";
import { needsCompare } from "./model";
import type { FormEvent } from "react";
import { toApiError } from "../../../platform/api";
import { useIdempotencyKey, useMonthCommand } from "../../assets/months/useMonthCommand";
import { SaveControls } from "../../finance/FinancialFeedback";
import { useHouseholdMembers } from "../../finance/FinanceSupport";
import { usePagedList } from "../../finance/queries";
import { changedFields, optional, preserveDraft } from "../model";
import type { Schema } from "../model";
import { InsuranceError } from "../InsuranceSupport";
import { AllocationFields, AllocationSummary, allocationDraft } from "./PayoutEditor";
import { useInsuranceEventsApi } from "./api";
import { FormError, useSubmitAttempt } from "../../../shared/formValidation";
import { formatSeoulDateTime } from "../../../shared/format";
const keyOf = (row: { id: string; version: number }) => `${row.id}:${row.version}`;
export function AllocationHistory({ id }: { id: string }) {
  const members = useHouseholdMembers();
  const api = useInsuranceEventsApi();
  const history = usePagedList(
    useCallback(
      async (cursor?: number) => {
        const result = await api.payoutAllocationHistory({
          allocationId: id,
          query: { limit: 50, ...(cursor ? { cursor } : {}) },
        });
        return { ...result, items: result.items.map((row) => ({ ...row, id: row.allocation_id })) };
      },
      [api, id],
    ),
    keyOf,
  );
  return (
    <section>
      <h3>배분 연결 이력</h3>
      <InsuranceError error={history.error} />
      {history.error && <button onClick={() => void history.reload()}>배분 이력 다시 확인</button>}
      <ol className="month-history">
        {history.items.map((row) => (
          <li key={keyOf(row)}>
            <h4>배분 버전 {row.version}</h4>
            <AllocationSummary row={row} />
            <p>
              {formatSeoulDateTime(row.changed_at)} ·{" "}
              {members.members.find((m) => m.member_id === row.changed_by_member_id)
                ?.display_name ?? "가계 구성원"}
            </p>
            {row.reason && <p>연결 사유: {row.reason}</p>}
          </li>
        ))}
      </ol>
      {history.cursor !== null && (
        <button disabled={history.loading} onClick={() => void history.more()}>
          배분 이력 더 보기
        </button>
      )}
    </section>
  );
}
export function AllocationLink({
  initial,
  saved,
  cancel,
}: {
  initial: Schema["AllocationResponse"];
  saved: () => void;
  cancel: () => void;
}) {
  const api = useInsuranceEventsApi();
  const command = useMonthCommand();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => allocationDraft(initial));
  const [reason, setReason] = useState("");
  const [latest, setLatest] = useState<Schema["AllocationResponse"] | null>(null);
  const [message, setMessage] = useState("");
  const attempt = useSubmitAttempt();
  const changes = changedFields(
    { policy_id: base.policy_id ?? null, claim_id: base.claim_id ?? null },
    { policy_id: optional(draft.policyId), claim_id: optional(draft.claimId) },
  );
  const input = { ...changes, reason: reason.trim() };
  const key = useIdempotencyKey(JSON.stringify([base.id, base.version, input]));
  const ready =
    !!reason.trim() && Object.keys(changes).length > 0 && (!draft.claimId || !!draft.policyId);
  async function submit(event: FormEvent<HTMLFormElement>) {
    const form = event.currentTarget;
    event.preventDefault();
    if (needsCompare(command.error)) return;
    if (!ready) {
      setMessage(
        "바꿀 계약·청구 연결과 정정 사유를 확인해 주세요. 청구를 고르면 계약도 골라야 해요.",
      );
      attempt.reject(form);
      return;
    }
    const result = await command.run((signal) =>
      api.linkPayoutAllocation(
        { allocationId: base.id, input, ifMatch: `"${base.version}"`, idempotencyKey: key },
        signal,
      ),
    );
    if (result.ok && command.mounted.current) saved();
  }
  async function compare() {
    try {
      const row = await api.getPayoutAllocation({ allocationId: base.id });
      if (command.mounted.current) setLatest(row);
    } catch (error) {
      command.setError(toApiError(error));
    }
  }
  return (
    <section className="review-panel">
      <h3>같은 입금의 청구 연결 정정</h3>
      <p>사건·금액·급부유형은 유지하며 계약·청구 연결만 바꿔요. 새 보험금 입금을 만들지 않아요.</p>
      <form onInput={() => setMessage("")} onSubmit={(e) => void submit(e)}>
        <AllocationFields
          value={draft}
          onChange={setDraft}
          fixedCase
          showMoney={false}
          disabled={command.busy}
        />
        <div className="form-field">
          <label>
            배분 연결 정정 사유
            <textarea
              required
              maxLength={500}
              value={reason}
              disabled={command.busy}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
        </div>
        <FormError message={message} />
        <InsuranceError error={command.error} />
        {needsCompare(command.error) && (
          <button type="button" onClick={() => void compare()}>
            현재 배분 연결 비교
          </button>
        )}
        {latest && (
          <section className="review-panel">
            <AllocationSummary row={latest} />
            <button
              type="button"
              onClick={() => {
                setDraft(preserveDraft(allocationDraft(base), draft, allocationDraft(latest)));
                setBase(latest);
                setLatest(null);
                command.setError(null);
              }}
            >
              비교한 배분 연결 유지
            </button>
          </section>
        )}
        <SaveControls
          busy={command.busy}
          cancel={command.cancel}
          disabled={needsCompare(command.error)}
          label="같은 입금의 청구 연결 저장"
        />
        <button type="button" onClick={cancel} disabled={command.busy}>
          배분 연결 취소
        </button>
      </form>
    </section>
  );
}
