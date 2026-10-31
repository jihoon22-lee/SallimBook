import { useCallback } from "react";
import { Link } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import { useAssetsApi } from "../assets/api";
import { useAccountsApi } from "../accounts/api";
import { useCardsApi } from "../cards/api";
import { useInsuranceApi } from "../insurance/api";
import { useHomecareApi } from "../homecare/api";
import { useResource } from "../finance/queries";
import { FinanceError } from "../finance/FinanceSupport";
import { useAssetComparisonApi } from "../assets/comparison/api";
import { formatKrw } from "../assets/months/model";
import { formatMonth, useMonth } from "../../shared/MonthContext";

type Preview = { items: { id: string; name: string; to: string }[]; next_cursor: string | null };
export function OverviewSection({
  title,
  to,
  read,
}: {
  title: string;
  to: string;
  read: () => Promise<Preview>;
}) {
  const result = useResource(read);
  return (
    <section className="card household-category" aria-label={title}>
      <div className="item-heading">
        <h3>{title}</h3>
        <Link to={to}>{title} 전체 보기</Link>
      </div>
      {result.loading && <p role="status">불러오는 중</p>}
      <FinanceError error={result.error} />
      {result.error && <button onClick={() => void result.reload()}>다시 불러오기</button>}
      {result.data &&
        !result.error &&
        !result.loading &&
        (result.data.items.length ? (
          <>
            <ul className="overview-items">
              {result.data.items.map((item) => (
                <li key={item.id}>
                  <Link to={item.to}>{item.name}</Link>
                </li>
              ))}
            </ul>
            {result.data.next_cursor && (
              <p className="muted">최근 등록한 항목이에요. 전체 목록에서 더 볼 수 있어요.</p>
            )}
          </>
        ) : (
          <p className="muted">아직 등록한 항목이 없어요.</p>
        ))}
    </section>
  );
}

export function InsuranceOverview() {
  const api = useInsuranceApi();
  const read = useCallback(async () => {
    const page = await api.policies({ limit: 4, status: "active" });
    return {
      ...page,
      items: page.items.map((row) => ({
        id: row.id,
        name: `${row.insurer} · ${row.product_name}`,
        to: `/insurance/policies/${row.id}`,
      })),
    };
  }, [api]);
  return <OverviewSection title="보험" to="/insurance/policies" read={read} />;
}
function PortfolioBalance() {
  const api = useAssetComparisonApi();
  const { month } = useMonth();
  const result = useResource(
    useCallback(() => api.comparison({ to: month, limit: 1 }), [api, month]),
  );
  const totals = result.data?.current.totals;
  return (
    <section className="card portfolio-balance" aria-label="저장된 자산 금액">
      <div className="item-heading">
        <h3>{formatMonth(month)} 자산·부채</h3>
        <Link to="/assets">자산 전체 보기</Link>
      </div>
      <FinanceError error={result.error} />
      {result.loading ? (
        <p role="status">금액 불러오는 중</p>
      ) : result.error ? (
        <button onClick={() => void result.reload()}>금액 다시 불러오기</button>
      ) : totals ? (
        <>
          <dl className="metric-strip">
            <div className="metric-primary">
              <dt>저장된 순자산</dt>
              <dd>{formatKrw(totals.net_assets_krw)}</dd>
            </div>
            <div>
              <dt>자산</dt>
              <dd>{formatKrw(totals.assets_krw)}</dd>
            </div>
            <div>
              <dt>부채</dt>
              <dd>{formatKrw(totals.liabilities_krw)}</dd>
            </div>
          </dl>
          <p className="muted">
            {totals.missing_count > 0 ? `금액 미입력 ${totals.missing_count}개 · ` : ""}
            {totals.carried_count > 0 ? `전월에서 가져온 금액 ${totals.carried_count}개 · ` : ""}
            저장한 금액 기준
          </p>
        </>
      ) : (
        <p>이 달에 저장한 금액은 아직 없어요. 등록한 자산과 계좌는 아래에서 볼 수 있어요.</p>
      )}
      <Link to={`/assets/months/${month}`}>금액 입력·수정</Link>
    </section>
  );
}
function RegisteredHousehold() {
  const assets = useAssetsApi(),
    accounts = useAccountsApi(),
    cards = useCardsApi(),
    homecare = useHomecareApi();
  const accountRead = useCallback(async () => {
    const page = await accounts.list({ limit: 4 });
    return {
      ...page,
      items: page.items.map((row) => ({
        id: row.id,
        name: row.asset.name,
        to: `/accounts/${row.id}`,
      })),
    };
  }, [accounts]);
  const cardRead = useCallback(async () => {
    const page = await cards.list({ limit: 4 });
    return {
      ...page,
      items: page.items.map((row) => ({
        id: row.id,
        name: row.alias || row.product_name,
        to: `/cards/${row.id}`,
      })),
    };
  }, [cards]);
  const propertyRead = useCallback(async () => {
    const page = await assets.list({ limit: 4, category: "real_estate" });
    return {
      ...page,
      items: page.items.map((row) => ({ id: row.id, name: row.name, to: `/assets/${row.id}` })),
    };
  }, [assets]);
  const financialRead = useCallback(async () => {
    const page = await assets.list({ limit: 4, category: "financial" });
    return {
      ...page,
      items: page.items.map((row) => ({ id: row.id, name: row.name, to: `/assets/${row.id}` })),
    };
  }, [assets]);
  const otherRead = useCallback(async () => {
    const pages = await Promise.all(
      (["deposit", "loan", "other"] as const).map((category) =>
        assets.list({ limit: 3, category }),
      ),
    );
    return {
      items: pages.flatMap((page) =>
        page.items.map((row) => ({ id: row.id, name: row.name, to: `/assets/${row.id}` })),
      ),
      next_cursor: pages.find((page) => page.next_cursor)?.next_cursor ?? null,
    };
  }, [assets]);
  const deviceRead = useCallback(async () => {
    const page = await homecare.listAppliances({ query: { limit: 4, status: "active" } });
    return {
      ...page,
      items: page.items.map((row) => ({ id: row.id, name: row.name, to: `/appliances/${row.id}` })),
    };
  }, [homecare]);
  return (
    <>
      <PortfolioBalance />
      <div className="household-overview-grid">
        <OverviewSection title="계좌·연금" to="/accounts" read={accountRead} />
        <OverviewSection
          title="투자·금융 자산"
          to="/assets?category=financial"
          read={financialRead}
        />
        <OverviewSection title="부동산" to="/assets?category=real_estate" read={propertyRead} />
        <OverviewSection title="보증금·기타 자산·부채" to="/assets" read={otherRead} />
        <InsuranceOverview />
        <OverviewSection title="카드" to="/cards" read={cardRead} />
        <OverviewSection title="가전·전자제품" to="/appliances" read={deviceRead} />
      </div>
    </>
  );
}
export function HouseholdOverview() {
  const { state } = useAuth();
  return (
    <section aria-label="우리 집 보유 현황">
      <h2>우리 집 보유 현황</h2>
      {state.status === "authenticated" ? (
        <RegisteredHousehold />
      ) : (
        <p>로그인하면 등록한 자산·계좌·보험·가전을 한눈에 볼 수 있어요.</p>
      )}
    </section>
  );
}
