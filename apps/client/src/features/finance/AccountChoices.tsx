import { useCallback } from "react";
import { useAccountsApi } from "../accounts/api";
import { allPages, useResource } from "./queries";
import { FinanceError } from "./FinanceSupport";
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
}: {
  value: string;
  onChange: (value: string) => void;
  label?: string;
  includeClosed?: boolean;
  disabled?: boolean;
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
            ?.filter((row) => includeClosed || row.status === "active" || row.id === value)
            .map((row) => (
              <option key={row.id} value={row.id} disabled={row.status !== "active"}>
                {row.asset.name} · {row.institution_name}
                {row.masked_number ? ` · ${row.masked_number}` : ""}
                {row.status === "active" ? "" : " · 사용 종료"}
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
