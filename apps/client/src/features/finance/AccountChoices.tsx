import { useCallback } from "react";
import { useAccountsApi } from "../accounts/api";
import { allPages, useResource } from "./queries";
import { FinanceError } from "./FinanceSupport";
import { dateLabel, isDateOnly } from "./dates";
/** Same day as the server's _link_date: the actual date, or the first day of a month total. */
export function linkDate(precision: "day" | "month", date: string, month: string): string {
  return precision === "day" ? date : `${month}-01`;
}
/** A closed account or card can be chosen only for a record dated on or before its end. */
export function usableOn(endedOn: string | null | undefined, on: string | undefined): boolean {
  return !endedOn || (!!on && isDateOnly(on) && endedOn >= on);
}
/** Selectable for a record dated on (plans pass no date and need a method still in use). */
export function methodUsable(
  status: string,
  endedOn: string | null | undefined,
  on: string | undefined,
): boolean {
  return endedOn ? usableOn(endedOn, on) : status === "active";
}
export function endedSuffix(status: string, endedOn: string | null | undefined): string {
  if (endedOn) return ` · ${dateLabel(endedOn)} 사용 종료`;
  return status === "active" ? "" : " · 사용 종료";
}
export function useAccountChoices() {
  const api = useAccountsApi();
  return useResource(
    useCallback(
      () =>
        allPages((cursor) =>
          api.list({ status: "all", limit: 200, ...(cursor ? { cursor } : {}) }),
        ),
      [api],
    ),
  );
}
export function AccountSelect({
  value,
  onChange,
  label = "입금계좌",
  includeClosed = false,
  disabled = false,
  on,
}: {
  value: string;
  onChange: (value: string) => void;
  label?: string;
  includeClosed?: boolean;
  disabled?: boolean;
  /** The record date; a closed account is selectable through its end date. */
  on?: string;
}) {
  const accounts = useAccountChoices();
  return (
    <div className="form-field">
      <label>
        {label}
        <select
          value={value}
          disabled={disabled || accounts.loading}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">계좌 연결 안 함</option>
          {accounts.data
            ?.filter(
              (row) =>
                includeClosed || row.id === value || methodUsable(row.status, row.closed_on, on),
            )
            .map((row) => (
              <option
                key={row.id}
                value={row.id}
                disabled={!methodUsable(row.status, row.closed_on, on)}
              >
                {row.asset.name} · {row.institution_name}
                {row.masked_number ? ` · ${row.masked_number}` : ""}
                {endedSuffix(row.status, row.closed_on)}
              </option>
            ))}
          {value && !accounts.data?.some((row) => row.id === value) && (
            <option value={value}>현재 연결 계좌 · 다시 확인 필요</option>
          )}
        </select>
      </label>
      <FinanceError error={accounts.error} />
      {accounts.error && (
        <button type="button" onClick={() => void accounts.reload()}>
          계좌 목록 다시 확인
        </button>
      )}
    </div>
  );
}
