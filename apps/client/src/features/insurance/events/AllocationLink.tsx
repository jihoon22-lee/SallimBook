import { useCallback, useEffect, useRef, useState } from "react";
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
import { useUnsavedChangesGuard } from "../../../shared/UnsavedChanges";
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
  targetClaim,
  saved,
  cancel,
}: {
  initial: Schema["AllocationResponse"];
  targetClaim?: Schema["ClaimResponse"];
  saved: () => void;
  cancel: () => void;
}) {
  const api = useInsuranceEventsApi();
  const command = useMonthCommand();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => ({
    ...allocationDraft(initial),
    ...(targetClaim ? { policyId: targetClaim.policy_id, claimId: targetClaim.id } : {}),
  }));
  const [ack, setAck] = useState(false);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    const opener = document.activeElement;
    panel.current?.focus({ preventScroll: true });
    panel.current?.scrollIntoView({ block: "start" });
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected)
        opener.focus({ preventScroll: true });
    };
  }, []);
  const [reason, setReason] = useState("");
  const [latest, setLatest] = useState<Schema["AllocationResponse"] | null>(null);
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const attempt = useSubmitAttempt();
  const changes = changedFields(
    { policy_id: base.policy_id ?? null, claim_id: base.claim_id ?? null },
    { policy_id: optional(draft.policyId), claim_id: optional(draft.claimId) },
  );
  const input = { ...changes, reason: reason.trim() };
  const key = useIdempotencyKey(JSON.stringify([base.id, base.version, input]));
  const ready =
    !!reason.trim() &&
    Object.keys(changes).length > 0 &&
    (!draft.claimId || !!draft.policyId) &&
    (!targetClaim || ack);
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
    if (result.ok && command.mounted.current) {
      guard.release();
      saved();
    }
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
    <section ref={panel} tabIndex={-1} className="review-panel" aria-label="기존 배분 연결 검토">
      <h3>같은 입금의 청구 연결 정정</h3>
      <p>사건·금액·급부유형은 유지하며 계약·청구 연결만 바꿔요. 새 보험금 입금을 만들지 않아요.</p>
      <form
        onInput={() => {
          setMessage("");
          setDirty(true);
        }}
        onSubmit={(e) => void submit(e)}
      >
        {targetClaim ? (
          <>
            <h4>현재 배분 연결</h4>
            <AllocationSummary row={base} />
            <h4>변경할 청구</h4>
            <p>{targetClaim.claim_reference || "접수번호 미입력"}</p>
            <p>현재 계약이나 다른 청구에 연결되어 있다면 이 청구의 계약·청구로 바뀌어요.</p>
            <label className="checkbox-field">
              <input
                type="checkbox"
                required
                checked={ack}
                disabled={command.busy}
                onChange={(e) => setAck(e.target.checked)}
              />
              기존 연결과 변경할 청구를 확인했어요.
            </label>
          </>
        ) : (
          <AllocationFields
            value={draft}
            onChange={setDraft}
            fixedCase
            showMoney={false}
            disabled={command.busy}
          />
        )}
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
                setDraft(
                  targetClaim
                    ? {
                        ...allocationDraft(latest),
                        policyId: targetClaim.policy_id,
                        claimId: targetClaim.id,
                      }
                    : preserveDraft(allocationDraft(base), draft, allocationDraft(latest)),
                );
                setBase(latest);
                setAck(false);
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
