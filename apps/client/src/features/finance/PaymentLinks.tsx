import { useCallback, useEffect, useRef, useState } from "react";
import type { components, operations } from "@sallimbook/api-client";
import { Link } from "react-router";
import { nativeFinance } from "../../platform/nativeFinance";
import { ApiError, toApiError } from "../../platform/api";
import { useAuth } from "../auth/AuthProvider";
import { useAccountsApi } from "../accounts/api";
import type { Asset } from "../assets/model";
import { formatKrw } from "../assets/months/model";
import { CashflowError } from "./FinancialFeedback";
import { isDateOnly, dateLabel } from "./dates";
import { allPages } from "./queries";
type Usage = components["schemas"]["PaymentLinksResponse"];
type Kind = Usage["resource_kind"];
type Query = NonNullable<operations["getCardPaymentLinks"]["parameters"]["query"]>;
export type ClosureProof = Pick<
  components["schemas"]["CardArchive"],
  "closure_ack" | "usage_digest"
>;
export async function completeUsage(
  read: (query: Query) => Promise<Usage>,
  date: string,
): Promise<Usage> {
  const first = await read({ as_of_date: date, limit: 200 });
  if (first.as_of_date !== date) throw new ApiError(409, "PAYMENT_LINKS_CHANGED");
  const result = structuredClone(first);
  const seen = new Set<string>();
  for (let page = 0; page < 100; page++) {
    const cursors = {
      rule_cursor: result.rules.next_cursor,
      obligation_cursor: result.obligations.next_cursor,
      card_cursor: result.cards.next_cursor,
    };
    if (!Object.values(cursors).some(Boolean)) {
      if (
        [result.rules, result.obligations, result.cards].some(
          (group) => group.items.length !== group.total_count,
        )
      )
        throw new ApiError(409, "PAYMENT_LINKS_CHANGED");
      return result;
    }
    const key = JSON.stringify(cursors);
    if (seen.has(key)) throw new ApiError(0, "REQUEST_FAILED");
    seen.add(key);
    const next = await read({
      as_of_date: date,
      limit: 200,
      ...Object.fromEntries(Object.entries(cursors).filter(([, value]) => value !== null)),
    });
    if (
      next.resource_kind !== first.resource_kind ||
      next.resource_id !== first.resource_id ||
      next.usage_digest !== first.usage_digest ||
      next.resource_version !== first.resource_version ||
      next.as_of_date !== first.as_of_date
    )
      throw new ApiError(409, "PAYMENT_LINKS_CHANGED");
    for (const [group, cursor] of [
      ["rules", "rule_cursor"],
      ["obligations", "obligation_cursor"],
      ["cards", "card_cursor"],
    ] as const) {
      if (cursors[cursor] === null) continue;
      const ids = new Set(result[group].items.map((item) => item.id));
      if (
        next[group].items.some((item) => ids.has(item.id)) ||
        next[group].total_count !== first[group].total_count
      )
        throw new ApiError(409, "PAYMENT_LINKS_CHANGED");
      // Each branch retains its generated row type; the cursors advance independently.
      if (group === "rules") result.rules.items.push(...next.rules.items);
      else if (group === "obligations") result.obligations.items.push(...next.obligations.items);
      else result.cards.items.push(...next.cards.items);
      result[group].next_cursor = next[group].next_cursor;
    }
  }
  throw new ApiError(0, "REQUEST_FAILED");
}
export function useClosureReview(kind: Kind | null, id: string, date: string, active: boolean) {
  const { domainApi } = useAuth();
  const [data, setData] = useState<Usage | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [ack, setAck] = useState(false);
  const [retry, setRetry] = useState(0);
  const stamp = `${kind}:${id}:${date}:${active}`;
  const [loadedStamp, setLoadedStamp] = useState("");
  const generation = useRef(0);
  useEffect(() => {
    const current = ++generation.current;
    setData(null);
    setError(null);
    setAck(false);
    setLoadedStamp("");
    if (!active || !kind || !isDateOnly(date)) {
      setLoading(false);
      return;
    }
    setLoading(true);
    const read = (query: Query) =>
      domainApi.read(
        (client) =>
          kind === "card"
            ? client.GET("/api/v1/cards/{resource_id}/payment-links", {
                params: { path: { resource_id: id }, query },
              })
            : client.GET("/api/v1/accounts/{resource_id}/payment-links", {
                params: { path: { resource_id: id }, query },
              }),
        () =>
          kind === "card"
            ? nativeFinance.getCardPaymentLinks({ resourceId: id, query })
            : nativeFinance.getAccountPaymentLinks({ resourceId: id, query }),
      );
    void completeUsage(read, date)
      .then((value) => {
        if (current === generation.current) {
          setData(value);
          setLoadedStamp(stamp);
        }
      })
      .catch((failure) => {
        if (current === generation.current) setError(toApiError(failure));
      })
      .finally(() => {
        if (current === generation.current) setLoading(false);
      });
    return () => {
      generation.current++;
    };
  }, [domainApi, kind, id, date, active, retry, stamp]);
  const required = active && kind !== null;
  const current = loadedStamp === stamp ? data : null;
  const ready =
    !required || (!!current && !loading && !error && (!current.requires_confirmation || ack));
  const proof: ClosureProof =
    current?.requires_confirmation && ack
      ? { closure_ack: true, usage_digest: current.usage_digest }
      : { closure_ack: false };
  const refresh = useCallback(() => {
    setAck(false);
    setData(null);
    setLoadedStamp("");
    setRetry((value) => value + 1);
  }, []);
  return { data: current, error, loading, ready, proof, ack, setAck, refresh };
}
export function useAssetClosure(asset: Asset | undefined | null, date: string, active: boolean) {
  const api = useAccountsApi();
  const required = active && !!asset && asset.category === "financial";
  const [account, setAccount] = useState<string | null>(null);
  const [lookupError, setLookupError] = useState<ApiError | null>(null);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupStamp, setLookupStamp] = useState("");
  const [retry, setRetry] = useState(0);
  const stamp = `${asset?.id}:${required}:${retry}`;
  useEffect(() => {
    let current = true;
    setAccount(null);
    setLookupError(null);
    setLookupStamp("");
    if (!required) {
      setLookupLoading(false);
      return;
    }
    setLookupLoading(true);
    void allPages((cursor) =>
      api.list({ status: "all", limit: 200, ...(cursor ? { cursor } : {}) }),
    )
      .then((rows) => {
        if (current) {
          setAccount(rows.find((row) => row.asset_id === asset!.id)?.id ?? null);
          setLookupStamp(stamp);
        }
      })
      .catch((error) => {
        if (current) setLookupError(toApiError(error));
      })
      .finally(() => {
        if (current) setLookupLoading(false);
      });
    return () => {
      current = false;
    };
  }, [api, asset?.id, required, retry, stamp]);
  const review = useClosureReview(
    account ? "account" : null,
    account ?? "",
    date,
    required && lookupStamp === stamp,
  );
  return {
    ...review,
    error: lookupError ?? review.error,
    loading: lookupLoading || review.loading,
    ready: (!required || (lookupStamp === stamp && !lookupLoading && !lookupError)) && review.ready,
    refresh: () => {
      setRetry((value) => value + 1);
      review.refresh();
    },
  };
}
export function ClosureReview({
  review,
  disabled = false,
}: {
  review: ReturnType<typeof useClosureReview>;
  disabled?: boolean;
}) {
  const data = review.data;
  return (
    <section className="review-panel" aria-label="사용 종료 영향 확인">
      <h3>선택한 종료일 이후의 연결</h3>
      {review.loading && <p role="status">등록된 납부 계획과 연결 카드를 확인하고 있어요.</p>}
      <CashflowError error={review.error} />
      {review.error && (
        <button type="button" disabled={disabled} onClick={review.refresh}>
          종료 영향 다시 확인
        </button>
      )}
      {data && (
        <>
          <p>
            {dateLabel(data.as_of_date)} 기준 · 등록된 정기 결제만 확인해요. 전체 카드 명세나 계좌
            출금 합계는 제공하지 않아요.
          </p>
          <p>
            현재·미래 규칙 {data.rules.total_count}개 · 미납·일부 납부 회차{" "}
            {data.obligations.total_count}개 · 연결 카드 {data.cards.total_count}개
          </p>
          {data.rules.items.length > 0 && (
            <details>
              <summary>연결 규칙 모두 보기</summary>
              <ul>
                {data.rules.items.map((row) => (
                  <li key={row.id}>
                    <Link to={`/fixed-payments/rules/${row.rule_id}`}>{row.title}</Link> ·{" "}
                    {row.payment_basis === "card_approval_plan"
                      ? "카드 승인 계획"
                      : "계좌 직접 납부 계획"}{" "}
                    · {row.period === "future" ? "미래 적용" : "현재 적용"} · 예정{" "}
                    {row.expected_amount_krw === null ? "미정" : formatKrw(row.expected_amount_krw)}{" "}
                    · {dateLabel(row.effective_from)}부터
                  </li>
                ))}
              </ul>
            </details>
          )}
          {data.obligations.items.length > 0 && (
            <details>
              <summary>연결 회차 모두 보기</summary>
              <ul>
                {data.obligations.items.map((row) => (
                  <li key={row.id}>
                    <Link to={`/fixed-payments/${row.id}`}>{row.title}</Link> ·{" "}
                    {dateLabel(row.scheduled_date)} ·{" "}
                    {row.payment_basis === "card_approval_plan"
                      ? "카드 승인 계획"
                      : "계좌 직접 납부 계획"}{" "}
                    · {row.status === "partial" ? "일부 납부" : "미납"} · 실제{" "}
                    {formatKrw(row.actual_paid_krw)}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {data.cards.items.length > 0 && (
            <details>
              <summary>연결 카드 모두 보기</summary>
              <ul>
                {data.cards.items.map((row) => (
                  <li key={row.id}>
                    <Link to={`/cards/${row.id}`}>{row.alias || row.product_name}</Link> ·{" "}
                    {row.issuer_name}
                    {row.last_four ? ` · •••• ${row.last_four}` : ""}
                    {row.active_for_closure ? " · 종료 영향 있음" : ""}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {data.requires_confirmation ? (
            <label className="checkbox-field">
              <input
                type="checkbox"
                checked={review.ack}
                onChange={(event) => review.setAck(event.target.checked)}
                disabled={disabled}
              />
              연결된 규칙·회차·카드를 확인했으며 결제수단을 별도로 정리할 것을 알고 있어요.
            </label>
          ) : (
            <p>현재 확인한 연결 중 종료 확인이 필요한 항목이 없어요.</p>
          )}
          <p className="muted">사용 종료는 기존 연결을 다른 결제수단으로 자동 변경하지 않아요.</p>
        </>
      )}
    </section>
  );
}
