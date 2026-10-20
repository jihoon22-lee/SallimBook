import { useCallback } from "react";
import { useCardsApi } from "../cards/api";
import { useAssetsApi } from "../assets/api";
import { AccountSelect, endedSuffix, methodUsable } from "../finance/AccountChoices";
import { CashflowError } from "../finance/FinancialFeedback";
import { allPages, useResource } from "../finance/queries";
function CardSelect({
  value,
  onChange,
  on,
}: {
  value: string;
  onChange: (id: string) => void;
  on?: string;
}) {
  const api = useCardsApi();
  const resource = useResource(
    useCallback(
      () =>
        allPages((cursor) =>
          api.list({ status: "all", limit: 200, ...(cursor ? { cursor } : {}) }),
        ),
      [api],
    ),
  );
  return (
    <div className="form-field">
      <label>
        납부 카드
        <select
          value={value}
          disabled={resource.loading}
          onChange={(event) => onChange(event.target.value)}
          required
        >
          <option value="">카드 선택</option>
          {resource.data
            ?.filter((row) => row.id === value || methodUsable(row.status, row.ended_on, on))
            .map((row) => (
              <option
                value={row.id}
                key={row.id}
                disabled={!methodUsable(row.status, row.ended_on, on)}
              >
                {row.alias || row.product_name} · {row.masked_number || "네 자리 미입력"}
                {endedSuffix(row.status, row.ended_on)}
              </option>
            ))}
          {value && !resource.data?.some((row) => row.id === value) && (
            <option value={value}>현재 연결 카드 · 다시 확인 필요</option>
          )}
        </select>
      </label>
      <CashflowError error={resource.error} />
      {resource.error && (
        <button type="button" onClick={() => void resource.reload()}>
          납부 카드 다시 확인
        </button>
      )}
    </div>
  );
}
export function PaymentMethod({
  method,
  id,
  onChange,
  on,
}: {
  method: "none" | "account" | "card";
  id: string;
  onChange: (method: "none" | "account" | "card", id: string) => void;
  /** The actual payment date; plans leave it out and only see methods still in use. */
  on?: string;
}) {
  return (
    <>
      <div className="form-field">
        <label>
          납부수단 구분
          <select
            value={method}
            onChange={(event) => onChange(event.target.value as typeof method, "")}
          >
            <option value="none">수단 연결 안 함</option>
            <option value="account">계좌 직접 납부</option>
            <option value="card">카드 승인</option>
          </select>
        </label>
      </div>
      {method === "account" && (
        <AccountSelect
          label="납부 계좌"
          value={id}
          onChange={(value) => onChange("account", value)}
          on={on}
        />
      )}
      {method === "card" && (
        <CardSelect value={id} onChange={(value) => onChange("card", value)} on={on} />
      )}
      {method === "card" && (
        <p className="muted">카드 승인 기록이에요. 카드 대금의 실제 계좌 출금과는 달라요.</p>
      )}
    </>
  );
}
export function LiabilitySelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (id: string) => void;
}) {
  const api = useAssetsApi();
  const resource = useResource(
    useCallback(
      () =>
        allPages((cursor) =>
          api.list({ kind: "liability", status: "all", limit: 200, ...(cursor ? { cursor } : {}) }),
        ),
      [api],
    ),
  );
  return (
    <div className="form-field">
      <label>
        연결 부채 (선택)
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={resource.loading}
        >
          <option value="">연결 안 함</option>
          {resource.data
            ?.filter((row) => row.status === "active" || row.id === value)
            .map((row) => (
              <option key={row.id} value={row.id} disabled={row.status !== "active"}>
                {row.name}
                {row.status === "archived" ? " · 사용 종료" : ""}
              </option>
            ))}
        </select>
      </label>
      <CashflowError error={resource.error} />
      {resource.error && (
        <button type="button" onClick={() => void resource.reload()}>
          부채 목록 다시 확인
        </button>
      )}
    </div>
  );
}
