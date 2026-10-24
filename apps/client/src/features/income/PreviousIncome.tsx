import { useCallback, useState } from "react";
import { previousMonth, formatKrw } from "../assets/months/model";
import { allPages, useResource } from "../finance/queries";
import { CashflowError } from "../finance/FinancialFeedback";
import { useHouseholdMembers } from "../finance/FinanceSupport";
import { useIncomeApi } from "./api";
import { incomeKinds, manualIncome } from "./model";
import type { Income } from "./model";

export function PreviousIncome({
  month,
  choose,
  close,
}: {
  month: string;
  choose: (row: Income) => void;
  close: () => void;
}) {
  const api = useIncomeApi();
  const members = useHouseholdMembers();
  const prior = previousMonth(month);
  const records = useResource(
    useCallback(
      () =>
        prior
          ? allPages((cursor) =>
              api.list({
                month: prior,
                state: "active",
                limit: 200,
                ...(cursor ? { cursor } : {}),
              }),
            )
          : Promise.resolve([]),
      [api, prior],
    ),
  );
  const [selected, setSelected] = useState("");
  const candidates =
    records.data?.filter(manualIncome).filter((row) => row.state === "active") ?? [];
  const chosen = candidates.find((row) => row.id === selected);
  return (
    <section className="review-panel" aria-label="지난달 수입 선택">
      <h3>{prior ?? "이전 월 없음"} 수입에서 새 초안 만들기</h3>
      <p>
        이번 달 입력 중인 내용은 선택한 기록의 금액·구성원·종류·계좌·메모로 바뀌어요. 실제 입금일은
        비워 두며, 금액과 계좌를 이번 달에 맞게 확인한 뒤 저장해 주세요. 보험금·반환·무효 기록은
        가져오지 않아요.
      </p>
      <CashflowError error={records.error} />
      {records.loading && <p role="status">지난달 수입을 확인하고 있어요.</p>}
      {!records.loading && !records.error && candidates.length === 0 && (
        <p>불러올 지난달 수동 수입이 없어요.</p>
      )}
      <div className="form-field">
        <label htmlFor="previous-income">지난달 수입 기록</label>
        <select
          id="previous-income"
          value={selected}
          disabled={records.loading || Boolean(records.error)}
          onChange={(event) => setSelected(event.target.value)}
        >
          <option value="">기록 선택</option>
          {candidates.map((row) => (
            <option key={row.id} value={row.id}>
              {members.members.find((member) => member.member_id === row.member_id)?.display_name ??
                "구성원 확인 필요"}{" "}
              · {incomeKinds[row.kind]} · {formatKrw(row.amount_krw)} ·{" "}
              {row.occurred_on ?? "월합계"}
              {row.note ? ` · ${row.note}` : ""}
            </option>
          ))}
        </select>
      </div>
      <div className="form-actions">
        <button
          type="button"
          disabled={!chosen || records.loading || Boolean(records.error)}
          onClick={() => {
            if (chosen) choose(chosen);
          }}
        >
          선택한 기록으로 새 초안 만들기
        </button>
        {records.error && (
          <button type="button" onClick={() => void records.reload()}>
            지난달 수입 다시 확인
          </button>
        )}
        <button type="button" className="secondary-button" onClick={close}>
          불러오기 닫기
        </button>
      </div>
    </section>
  );
}
