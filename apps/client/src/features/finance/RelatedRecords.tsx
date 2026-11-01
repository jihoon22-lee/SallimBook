import { ExpensePlans } from "../fixed/ExpensePlans";
import { useCallback } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import { nativeFinance } from "../../platform/nativeFinance";
import { useAccountsApi } from "../accounts/api";
import { useAssetsApi } from "../assets/api";
import { useCardsApi } from "../cards/api";
import { useIncomeApi } from "../income/api";
import { incomeKinds } from "../income/model";
import { useAccountChoices, endedSuffix } from "./AccountChoices";
import { allPages, useResource } from "./queries";
import { completeUsage } from "./PaymentLinks";
import { CashflowError } from "./FinancialFeedback";
import { dateLabel, todaySeoul } from "./dates";
import { formatKrw } from "../assets/months/model";
import { MonthPicker, useMonth, formatMonth } from "../../shared/MonthContext";
import { formatSeoulDateTime } from "../../shared/format";

function ReadState({
  state,
}: {
  state: {
    loading: boolean;
    error: Parameters<typeof CashflowError>[0]["error"];
    reload: () => Promise<unknown>;
  };
}) {
  return (
    <>
      {state.loading && <p role="status">연결 기록을 확인하고 있어요.</p>}
      <CashflowError error={state.error} />
      {state.error && (
        <button type="button" onClick={() => void state.reload()}>
          연결 기록 다시 확인
        </button>
      )}
    </>
  );
}

/** Names are fetched from ordinary metadata only, never number or vault endpoints. */
export function NamedReference({
  kind,
  id,
  suffix,
}: {
  kind: "accounts" | "cards" | "assets";
  id: string;
  suffix?: ReactNode;
}) {
  const accounts = useAccountsApi();
  const cards = useCardsApi();
  const assets = useAssetsApi();
  const resource = useResource(
    useCallback(async () => {
      if (kind === "accounts") {
        const row = await accounts.get(id);
        return row.asset.name + endedSuffix(row.status, row.closed_on);
      }
      if (kind === "cards") {
        const row = await cards.get(id);
        return (row.alias || row.product_name) + endedSuffix(row.status, row.ended_on);
      }
      const row = await assets.get(id);
      return row.name + endedSuffix(row.status, row.ended_on);
    }, [accounts, cards, assets, kind, id]),
  );
  return (
    <>
      <Link to={`/${kind}/${id}`}>
        {resource.error ? "연결 정보 확인 필요" : (resource.data ?? "연결 정보 확인 중")}
        {suffix}
      </Link>
      {resource.error && (
        <button type="button" onClick={() => void resource.reload()}>
          연결 이름 다시 확인
        </button>
      )}
    </>
  );
}

export function AssetAccountLink({ assetId }: { assetId: string }) {
  const accounts = useAccountChoices();
  const rows = accounts.data?.filter((row) => row.asset_id === assetId) ?? [];
  return (
    <section className="card" aria-label="자산의 연결 계좌">
      <h2>연결 계좌</h2>
      <ReadState state={accounts} />
      {!accounts.loading && !accounts.error && (
        <>
          {rows.length ? (
            <ul>
              {rows.map((row) => (
                <li key={row.id}>
                  <Link to={`/accounts/${row.id}`}>
                    {row.asset.name} · {row.institution_name}
                    {endedSuffix(row.status, row.closed_on)}
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p>연결된 계좌가 없어요.</p>
          )}
          <p className="muted">계좌와 금융 자산은 같은 평가액을 공유하며 한 번만 합산해요.</p>
        </>
      )}
    </section>
  );
}

export function PaymentConnections({ kind, id }: { kind: "account" | "card"; id: string }) {
  const { domainApi } = useAuth();
  const date = todaySeoul();
  const resource = useResource(
    useCallback(
      () =>
        completeUsage(
          (query) =>
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
            ),
          date,
        ),
      [domainApi, kind, id, date],
    ),
  );
  const data = resource.data;
  return (
    <section className="card" aria-label="정기 결제 연결">
      <h2>정기 결제 연결</h2>
      <ExpensePlans method={{ kind, id }} />
      <p>
        {dateLabel(date)} 기준 현재·미래 납부 규칙과 미납·일부 납부 회차예요. 전체 카드 명세나 계좌
        출금 합계는 아니에요.
      </p>
      <ReadState state={resource} />
      {data && !resource.error && !resource.loading && (
        <>
          <p>
            연결 규칙 {new Set(data.rules.items.map((row) => row.rule_id)).size}개 · 적용기간{" "}
            {data.rules.total_count}개 · 미납·일부 납부 {data.obligations.total_count}회
          </p>
          {data.rules.items.length ? (
            <ul>
              {data.rules.items.map((row) => (
                <li key={row.id}>
                  <Link to={`/fixed-payments/rules/${row.rule_id}`}>{row.title}</Link> ·{" "}
                  {row.period === "future" ? "미래 적용" : "현재 적용"} ·{" "}
                  {row.payment_basis === "card_approval_plan"
                    ? "카드 승인 계획"
                    : "계좌 직접 납부 계획"}{" "}
                  · 예정{" "}
                  {row.expected_amount_krw === null ? "미정" : formatKrw(row.expected_amount_krw)} ·{" "}
                  {dateLabel(row.effective_from)}부터
                  {row.effective_until ? ` ${dateLabel(row.effective_until)} 전까지` : ""}
                </li>
              ))}
            </ul>
          ) : (
            <p>현재·미래 연결 규칙이 없어요.</p>
          )}
          {data.obligations.items.length > 0 && (
            <details>
              <summary>미납·일부 납부 회차 {data.obligations.total_count}회</summary>
              <ul>
                {data.obligations.items.map((row) => (
                  <li key={row.id}>
                    <Link to={`/fixed-payments/${row.id}`}>{row.title}</Link> ·{" "}
                    {dateLabel(row.scheduled_date)} ·{" "}
                    {row.status === "partial" ? "일부 납부" : "미납"} · 실제{" "}
                    {formatKrw(row.actual_paid_krw)}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {kind === "account" && (
            <>
              <h3>결제계좌로 연결된 카드 {data.cards.total_count}개</h3>
              {data.cards.items.length ? (
                <ul>
                  {data.cards.items.map((row) => (
                    <li key={row.id}>
                      <Link to={`/cards/${row.id}`}>{row.alias || row.product_name}</Link> ·{" "}
                      {row.issuer_name}
                      {row.ended_on ? ` · ${dateLabel(row.ended_on)} 사용 종료` : " · 사용 중"}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>연결된 카드가 없어요.</p>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}

export function AccountIncomeLinks({ accountId }: { accountId: string }) {
  const api = useIncomeApi();
  const { month } = useMonth();
  const resource = useResource(
    useCallback(
      async () =>
        (
          await allPages((cursor) =>
            api.list({ month, state: "all", limit: 200, ...(cursor ? { cursor } : {}) }),
          )
        ).filter((row) => row.account_id === accountId),
      [api, month, accountId],
    ),
  );
  return (
    <section className="card" aria-label="계좌에 연결된 수입">
      <h2>연결된 수입·반환</h2>
      <MonthPicker />
      <p>
        {formatMonth(month)}에 이 계좌로 기록한 수입과 보험금 유입·반환이에요. 무효 기록도 함께
        표시하며 계좌 잔액은 자동 변경하지 않아요.
      </p>
      <ReadState state={resource} />
      {!resource.error &&
        !resource.loading &&
        (resource.data?.length ? (
          <ul>
            {resource.data.map((row) => (
              <li key={row.id}>
                <Link to={`/income/${row.id}`}>
                  {incomeKinds[row.kind as keyof typeof incomeKinds]} ·{" "}
                  {row.occurred_on
                    ? dateLabel(row.occurred_on)
                    : `${formatMonth(row.period_month)} 월합계`}{" "}
                  · {formatKrw(row.amount_krw)}
                </Link>
                {row.state === "void" ? " · 무효 기록" : ""}
              </li>
            ))}
          </ul>
        ) : (
          <p>선택한 월에 연결된 수입·반환이 없어요.</p>
        ))}
    </section>
  );
}

export function RuleInsuranceLink({ ruleId }: { ruleId: string }) {
  const { domainApi } = useAuth();
  const resource = useResource(
    useCallback(
      () =>
        domainApi.read(
          (client) =>
            client.GET("/api/v1/recurring-rules/{rule_id}/insurance-link", {
              params: { path: { rule_id: ruleId } },
            }),
          () => nativeFinance.getRecurringRuleInsuranceLink({ ruleId }),
        ),
      [domainApi, ruleId],
    ),
  );
  const row = resource.data?.link;
  return (
    <section className="card" aria-label="납부 규칙의 보험 계약">
      <h2>연결 보험 계약</h2>
      <ReadState state={resource} />
      {!resource.error &&
        !resource.loading &&
        (row ? (
          <p>
            <Link to={`/insurance/policies/${row.policy_id}`}>
              {row.product_name} · {row.insurer}
            </Link>{" "}
            ·{" "}
            {row.policy_status === "active"
              ? "유지 중"
              : row.policy_status === "ended"
                ? "계약 종료"
                : "실효"}{" "}
            ·{" "}
            {row.active
              ? "보험료 연결 중"
              : `보험료 연결 종료${row.ended_at ? ` (${formatSeoulDateTime(row.ended_at)})` : ""}`}
          </p>
        ) : (
          <p>연결된 보험 계약이 없어요.</p>
        ))}
    </section>
  );
}

export function IncomeInsuranceLinks({ recordId }: { recordId: string }) {
  const { domainApi } = useAuth();
  const resource = useResource(
    useCallback(
      () =>
        domainApi.read(
          (client) =>
            client.GET("/api/v1/income/{record_id}/insurance-source", {
              params: { path: { record_id: recordId } },
            }),
          () => nativeFinance.getIncomeInsuranceSource({ recordId }),
        ),
      [domainApi, recordId],
    ),
  );
  const row = resource.data;
  return (
    <section aria-label="보험금 원본과 배분 사건">
      <h3>보험금 원본과 배분 사건</h3>
      <ReadState state={resource} />
      {row && !resource.error && !resource.loading && (
        <>
          {row.payout_id ? (
            <>
              <p>보험 영역의 실제 수령·반환 기록이에요. 수입으로 다시 등록하지 않아요.</p>
              <div className="form-actions">
                <Link to={`/insurance/payouts/${row.payout_id}`}>실제 입금 원본과 전체 배분</Link>
                {row.return_id && (
                  <Link to={`/insurance/returns/${row.return_id}`}>실제 반환 원본</Link>
                )}
              </div>
              <p>원래 입금의 사건별 배분이에요. 반환 금액은 실제 반환 원본에서 확인해 주세요.</p>
              <ul>
                {row.allocations.map((allocation) => (
                  <li key={allocation.id}>
                    <Link to={`/insurance/cases/${allocation.case_id}`}>
                      {allocation.case_title}
                    </Link>{" "}
                    · 입금 배분 {formatKrw(allocation.amount_krw)}
                    {allocation.id === row.original_allocation_id ? " · 이 반환의 대상 배분" : ""}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p>보험금 원본 연결이 없어요.</p>
          )}
        </>
      )}
    </section>
  );
}
