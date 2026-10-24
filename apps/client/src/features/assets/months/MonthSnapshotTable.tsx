import type { HouseholdMember } from "../../finance/FinanceSupport";
import { dateLabel } from "../../finance/dates";
import { amountBases, assetKinds, categories, shareToPercent } from "../model";
import { snapshotOwner } from "./ScopeChanges";
import { carriedNote, formatKrw, verificationStates } from "./model";
import type { MonthValue } from "./model";
export function MonthSnapshotTable({
  rows,
  members,
  readOnly,
  locked,
  edit,
}: {
  rows: MonthValue[];
  members: HouseholdMember[];
  readOnly: boolean;
  locked: boolean;
  edit: (row: MonthValue) => void;
}) {
  return (
    <div
      className="table-scroll asset-work-table"
      role="region"
      aria-label="월 기록 금액 표"
      tabIndex={0}
    >
      <table>
        <caption>월 기록 · 가계 보유분은 서버에서 계산한 금액</caption>
        <thead>
          <tr>
            <th scope="col">항목·소유 관계</th>
            <th scope="col" className="money-cell">
              가계 보유분
            </th>
            <th scope="col">확인 상태·기준일</th>
            <th scope="col">기록 확인</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr className="month-value-card" key={row.asset_id}>
              <th scope="row">
                <h3>{row.name}</h3>
                <p className="muted">
                  {assetKinds[row.kind]} · {snapshotOwner(row, members)}
                </p>
                <details className="record-details">
                  <summary>이 기록의 소유·지분·보유기간</summary>
                  <p>
                    {categories[row.category]} · 가계 지분 {shareToPercent(row.household_share)}% ·{" "}
                    {amountBases[row.amount_basis]}
                  </p>
                  <p>
                    입력 금액 {formatKrw(row.input_amount_krw)} ·{" "}
                    {row.inclusion_status === "included" ? "합계 포함" : "합계 제외"}
                  </p>
                  <p>
                    {dateLabel(row.started_on)} ~{" "}
                    {row.ended_on ? dateLabel(row.ended_on) : "종료일 없음"}
                  </p>
                  {row.change_reason && <p>값 변경 사유: {row.change_reason}</p>}
                </details>
              </th>
              <td className="money-cell owned-amount">
                {formatKrw(row.owned_amount_krw)}
                <small>{row.inclusion_status === "excluded" ? "합계 제외" : "합계 포함"}</small>
              </td>
              <td>
                <span
                  className={`status-chip ${row.verification_state !== "verified" ? "unverified-chip" : ""}`}
                >
                  {verificationStates[row.verification_state]}
                </span>
                <p>{dateLabel(row.as_of_date)}</p>
                {carriedNote(row) && <p className="muted">{carriedNote(row)}</p>}
              </td>
              <td>
                {!readOnly ? (
                  <button
                    type="button"
                    className={
                      row.verification_state !== "verified" ? "primary-button" : "secondary-button"
                    }
                    disabled={locked}
                    data-month-row={row.asset_id}
                    onClick={() => edit(row)}
                  >
                    {row.name} 금액 확인
                  </button>
                ) : (
                  "확정 기록"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
