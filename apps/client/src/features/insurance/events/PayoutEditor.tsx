import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { toApiError } from "../../../platform/api";
import { formatKrw, parseKrw } from "../../assets/months/model";
import { useIdempotencyKey, useMonthCommand } from "../../assets/months/useMonthCommand";
import { RecordedMoneyNotice, SaveControls } from "../../finance/FinancialFeedback";
import { isUuid } from "../../finance/dates";
import { allPages, useResource } from "../../finance/queries";
import { InsuranceError } from "../InsuranceSupport";
import { benefits, optional, preserveDraft } from "../model";
import type { Schema } from "../model";
import { ActualFields, CashSummary, CaseSelect, PolicySelect } from "./EventSupport";
import { actualDraft, actualInput, claimStates, exactSum } from "./model";
import type { ActualDraft } from "./model";
import { useInsuranceEventsApi } from "./api";
export type AllocationDraft = {
  caseId: string;
  policyId: string;
  claimId: string;
  benefit: Schema["BenefitType"];
  amount: string;
};
export const allocationDraft = (row?: Schema["AllocationResponse"]): AllocationDraft => ({
  caseId: row?.case_id ?? "",
  policyId: row?.policy_id ?? "",
  claimId: row?.claim_id ?? "",
  benefit: row?.benefit_type ?? "reimbursement",
  amount: row?.amount_krw ?? "",
});
export function AllocationFields({
  value,
  onChange,
  fixedCase = false,
  showMoney = true,
  disabled = false,
}: {
  value: AllocationDraft;
  onChange: (next: AllocationDraft) => void;
  fixedCase?: boolean;
  showMoney?: boolean;
  disabled?: boolean;
}) {
  const api = useInsuranceEventsApi();
  const claims = useResource(
    useCallback(
      () =>
        isUuid(value.caseId)
          ? allPages((cursor) =>
              api.listInsuranceClaims({
                query: {
                  case_id: value.caseId,
                  ...(value.policyId ? { policy_id: value.policyId } : {}),
                  limit: 200,
                  ...(cursor ? { cursor } : {}),
                },
              }),
            )
          : Promise.resolve([]),
      [api, value.caseId, value.policyId],
    ),
  );
  return (
    <fieldset className="form-grid" disabled={disabled}>
      <legend>사건·계약·청구 배분</legend>
      {fixedCase ? (
        <Link to={`/insurance/cases/${value.caseId}`}>배분 사건 확인</Link>
      ) : (
        <CaseSelect
          label="배분 사건"
          value={value.caseId}
          onChange={(id) => onChange({ ...value, caseId: id, claimId: "" })}
        />
      )}
      <PolicySelect
        label="배분 보험계약"
        value={value.policyId}
        onChange={(id) => onChange({ ...value, policyId: id, claimId: "" })}
      />
      <div className="form-field">
        <label>
          배분 청구 (선택)
          <select
            value={value.claimId}
            disabled={claims.loading}
            onChange={(e) => {
              const selected = claims.data?.find((row) => row.id === e.target.value);
              onChange({
                ...value,
                claimId: e.target.value,
                policyId: selected?.policy_id ?? value.policyId,
              });
            }}
          >
            <option value="">청구 없이 직접 수령</option>
            {claims.data?.map((row) => (
              <option key={row.id} value={row.id}>
                {row.claim_reference || "접수번호 미입력"} ·{" "}
                {claimStates[row.claim_state ?? "draft"]}
              </option>
            ))}
          </select>
        </label>
        <InsuranceError error={claims.error} />
        {claims.error && (
          <button type="button" onClick={() => void claims.reload()}>
            배분 청구 다시 확인
          </button>
        )}
      </div>
      {showMoney && (
        <>
          <div className="form-field">
            <label>
              배분 급부유형
              <select
                value={value.benefit}
                onChange={(e) =>
                  onChange({ ...value, benefit: e.target.value as AllocationDraft["benefit"] })
                }
              >
                {Object.entries(benefits).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="form-field">
            <label>
              사건 배분금액 (원)
              <input
                required
                inputMode="numeric"
                value={value.amount}
                onChange={(e) => onChange({ ...value, amount: e.target.value })}
              />
            </label>
          </div>
        </>
      )}
    </fieldset>
  );
}
export function AllocationSummary({ row }: { row: Schema["AllocationInput"] }) {
  return (
    <>
      <p>
        {benefits[row.benefit_type]} · 배분 {formatKrw(row.amount_krw)}
      </p>
      <div className="form-actions">
        <Link to={`/insurance/cases/${row.case_id}`}>배분 사건</Link>
        {row.policy_id ? (
          <Link to={`/insurance/policies/${row.policy_id}`}>배분 보험계약</Link>
        ) : (
          <span>보험계약 미지정</span>
        )}
        {row.claim_id ? (
          <Link to={`/insurance/claims/${row.claim_id}`}>연결 청구</Link>
        ) : (
          <span>청구 없는 직접 수령</span>
        )}
      </div>
    </>
  );
}
type Draft = { actual: ActualDraft; insurer: string; allocations: AllocationDraft[] };
function draftOf(row?: Schema["PayoutResponse"], caseId = "", policyId = "", claimId = ""): Draft {
  return {
    actual: actualDraft(row?.cash),
    insurer: row?.insurer_note ?? "",
    allocations: row?.allocations.map(allocationDraft) ?? [
      { ...allocationDraft(), caseId, policyId, claimId },
    ],
  };
}
export function payoutInput(d: Draft): Omit<Schema["PayoutCreate"], "card_id"> | null {
  const actual = actualInput(d.actual);
  const sum = exactSum(d.allocations.map((r) => r.amount));
  if (
    !actual ||
    d.actual.method === "card" ||
    d.insurer.length > 1000 ||
    !d.allocations.length ||
    d.allocations.length > 200 ||
    sum !== actual.amount_krw ||
    d.allocations.some(
      (a) =>
        !isUuid(a.caseId) ||
        (a.policyId && !isUuid(a.policyId)) ||
        (a.claimId && (!isUuid(a.claimId) || !isUuid(a.policyId))) ||
        parseKrw(a.amount) === null ||
        parseKrw(a.amount) === "0",
    )
  )
    return null;
  const { card_id: _card, ...cash } = actual;
  return {
    ...cash,
    insurer_note: optional(d.insurer),
    allocations: d.allocations.map((a) => ({
      case_id: a.caseId,
      policy_id: optional(a.policyId),
      claim_id: optional(a.claimId),
      benefit_type: a.benefit,
      amount_krw: parseKrw(a.amount)!,
    })),
  };
}
export function PayoutEditor({
  initial,
  caseId = "",
  policyId = "",
  claimId = "",
}: {
  initial?: Schema["PayoutResponse"];
  caseId?: string;
  policyId?: string;
  claimId?: string;
}) {
  const api = useInsuranceEventsApi();
  const command = useMonthCommand();
  const navigate = useNavigate();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => draftOf(initial, caseId, policyId, claimId));
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [latest, setLatest] = useState<Schema["PayoutResponse"] | null>(null);
  const input = payoutInput(draft);
  const sum = exactSum(draft.allocations.map((a) => a.amount));
  const key = useIdempotencyKey(JSON.stringify([base?.id, base?.version, input, reason.trim()]));
  const ready = !!input && ack && (!base || (base.cash.state === "active" && !!reason.trim()));
  const change = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft((d) => ({ ...d, [key]: value }));
    setAck(false);
  };
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!input || !ready || command.error?.status === 409) return;
    const result = await command.run((signal) =>
      base
        ? api.correctInsurancePayout(
            {
              resourceId: base.id,
              input: { ...input, reason: reason.trim() },
              ifMatch: `"${base.version}"`,
              idempotencyKey: key,
            },
            signal,
          )
        : api.createInsurancePayout({ input, idempotencyKey: key }, signal),
    );
    if (result.ok && command.mounted.current) navigate(`/insurance/payouts/${result.value.id}`);
  }
  async function compare() {
    if (!base) return;
    try {
      const row = await api.getInsurancePayout({ resourceId: base.id });
      if (command.mounted.current) setLatest(row);
    } catch (error) {
      command.setError(toApiError(error));
    }
  }
  return (
    <section className="card">
      <h2>{base ? "보험금 수령 원본 정정" : "실제 보험금 수령"}</h2>
      <RecordedMoneyNotice />
      <p>
        입금 한 번을 원본 한 건으로 기록하고 사건별로 배분해요. 청구가 없어도 저장하고 나중에 같은
        배분을 청구에 연결할 수 있어요.
      </p>
      <form onSubmit={(e) => void submit(e)}>
        <ActualFields
          title="보험금 수령"
          draft={draft.actual}
          onChange={(value) => change("actual", value)}
          disabled={command.busy}
          accountOnly
        />
        <fieldset disabled={command.busy}>
          <legend>입금 출처와 배분</legend>
          <div className="form-field">
            <label>
              보험사·입금 참고 메모
              <textarea
                maxLength={1000}
                value={draft.insurer}
                onChange={(e) => change("insurer", e.target.value)}
              />
            </label>
          </div>
          {draft.allocations.map((a, index) => (
            <section className="conversion-row" key={index} aria-label={`보험금 배분 ${index + 1}`}>
              <h3>배분 {index + 1}</h3>
              <AllocationFields
                value={a}
                onChange={(next) =>
                  change(
                    "allocations",
                    draft.allocations.map((row, i) => (i === index ? next : row)),
                  )
                }
              />
              {draft.allocations.length > 1 && (
                <button
                  type="button"
                  onClick={() =>
                    change(
                      "allocations",
                      draft.allocations.filter((_, i) => i !== index),
                    )
                  }
                >
                  배분 {index + 1} 제거
                </button>
              )}
            </section>
          ))}
          <button
            type="button"
            disabled={draft.allocations.length >= 200}
            onClick={() => change("allocations", [...draft.allocations, allocationDraft()])}
          >
            사건 배분 추가
          </button>
          <p>
            실제 입금 {formatKrw(parseKrw(draft.actual.amount))} · 배분 합계 {formatKrw(sum)}
          </p>
          {sum !== parseKrw(draft.actual.amount) && (
            <p role="alert">배분 합계가 실제 입금액과 같아야 해요.</p>
          )}
          {base && (
            <div className="form-field">
              <label>
                보험금 수령 정정 사유
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
          )}
          <label className="checkbox-field">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            실제 입금 한 건과 같은 합계의 사건별 배분을 확인했어요.
          </label>
          {base && (
            <p>
              기존 수령은 무효로 보존하고 새 원본으로 정정해요. 활성 반환이 있으면 먼저 반환 기록을
              확인해야 해요.
            </p>
          )}
        </fieldset>
        <InsuranceError error={command.error} />
        {base && command.error?.status === 409 && (
          <button type="button" onClick={() => void compare()}>
            보험금 수령 현재 원본 비교
          </button>
        )}
        {latest && (
          <section className="review-panel">
            <CashSummary cash={latest.cash} />
            <p>현재 출처 메모: {latest.insurer_note || "미입력"}</p>
            {latest.allocations.map((a) => (
              <AllocationSummary key={a.id} row={a} />
            ))}
            <button
              type="button"
              disabled={latest.cash.state !== "active"}
              onClick={() => {
                const current = draftOf(latest);
                setDraft({
                  ...preserveDraft(draftOf(base), draft, current),
                  actual: preserveDraft(draftOf(base).actual, draft.actual, current.actual),
                });
                setBase(latest);
                setLatest(null);
                setAck(false);
                command.setError(null);
              }}
            >
              비교한 수령 정정 유지
            </button>
          </section>
        )}
        <SaveControls
          backTo={
            base
              ? `/insurance/payouts/${base.id}`
              : isUuid(caseId)
                ? `/insurance/cases/${caseId}`
                : "/insurance/payouts"
          }
          busy={command.busy}
          cancel={command.cancel}
          disabled={!ready || command.error?.status === 409}
          label={base ? "보험금 수령 정정 저장" : "실제 보험금 수령 저장"}
        />
      </form>
    </section>
  );
}
