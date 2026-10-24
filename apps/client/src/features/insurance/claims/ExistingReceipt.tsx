import { useCallback, useState } from "react";
import { Link } from "react-router";
import { formatKrw } from "../../assets/months/model";
import { dateLabel } from "../../finance/dates";
import { allPages, useResource } from "../../finance/queries";
import { InsuranceError } from "../InsuranceSupport";
import { AllocationLink } from "../events/AllocationLink";
import { useInsuranceEventsApi } from "../events/api";
import type { Schema } from "../model";

function ReceiptChoices({ claim, saved }: { claim: Schema["ClaimResponse"]; saved: () => void }) {
  const api = useInsuranceEventsApi();
  const [editing, setEditing] = useState<Schema["AllocationResponse"] | null>(null);
  const receipts = useResource(
    useCallback(async () => {
      const rows = await allPages((cursor) =>
        api.listInsurancePayouts({
          query: {
            case_id: claim.case_id,
            state: "active",
            limit: 200,
            ...(cursor ? { cursor } : {}),
          },
        }),
      );
      // Fetch details only for these same-case originals, sequentially to bound load.
      const choices = [];
      for (const row of rows) {
        const original = await api.getInsurancePayout({ resourceId: row.id });
        if (original.cash.state === "active") choices.push(original);
      }
      return choices;
    }, [api, claim.case_id]),
  );
  const choices =
    receipts.data?.flatMap((original) =>
      original.allocations
        .filter((a) => a.case_id === claim.case_id && a.claim_id !== claim.id)
        .map((allocation) => ({ original, allocation })),
    ) ?? [];
  return (
    <>
      <p>
        같은 사건의 활성 입금에서 아직 이 청구에 연결되지 않은 배분을 골라요. 기존 계약·청구 연결도
        함께 확인해 주세요.
      </p>
      <InsuranceError error={receipts.error} />
      {receipts.error && (
        <button onClick={() => void receipts.reload()}>기존 수령 다시 확인</button>
      )}
      {receipts.loading && <p role="status">기존 입금과 사건별 배분을 확인하고 있어요.</p>}
      {!receipts.loading && !receipts.error && !choices.length && (
        <p>연결할 기존 배분이 없어요. 이미 연결된 수령은 아래 원본 목록에서 확인해 주세요.</p>
      )}
      {!receipts.loading && !receipts.error && (
        <ul className="finance-list">
          {choices.map(({ original, allocation }) => (
            <li key={allocation.id}>
              <h3>
                {dateLabel(original.cash.occurred_on)} · 이 사건 배분{" "}
                {formatKrw(allocation.amount_krw)}
              </h3>
              <p>
                <Link to={`/insurance/payouts/${original.id}`}>
                  입금 원본 {formatKrw(original.cash.amount_krw)}
                </Link>{" "}
                · 전체 {original.allocation_count}개 배분
              </p>
              <p>
                {allocation.claim_id ? (
                  <Link to={`/insurance/claims/${allocation.claim_id}`}>
                    현재 다른 청구에 연결됨
                  </Link>
                ) : (
                  "청구 없이 받은 배분"
                )}{" "}
                ·{" "}
                {allocation.policy_id ? (
                  <Link to={`/insurance/policies/${allocation.policy_id}`}>현재 보험계약 확인</Link>
                ) : (
                  "계약 미지정"
                )}
              </p>
              <button type="button" disabled={!!editing} onClick={() => setEditing(allocation)}>
                이 배분을 청구에 연결 검토
              </button>
            </li>
          ))}
        </ul>
      )}
      {editing && (
        <AllocationLink
          key={`${editing.id}:${editing.version}`}
          initial={editing}
          targetClaim={claim}
          saved={() => {
            setEditing(null);
            saved();
          }}
          cancel={() => setEditing(null)}
        />
      )}
    </>
  );
}
export function ExistingReceipt({
  claim,
  saved,
}: {
  claim: Schema["ClaimResponse"];
  saved: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className="card" aria-label="기존 수령 연결">
      <h2>이미 받은 보험금 연결</h2>
      <p>입금 건수와 금액은 유지하고 기존 배분의 청구 연결만 정정해요.</p>
      {!open ? (
        <button onClick={() => setOpen(true)}>같은 사건의 기존 수령 찾기</button>
      ) : (
        <ReceiptChoices claim={claim} saved={saved} />
      )}
    </section>
  );
}
