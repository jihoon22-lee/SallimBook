import type { ReactNode } from "react";
import { Link } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import { FinanceError } from "../finance/FinanceSupport";
import { formatKrw } from "../assets/months/model";
import { formatMonth, useMonth } from "../../shared/MonthContext";
import { StaleNotice } from "../../shared/StaleNotice";
import {
  holdingGroups,
  type HouseholdOverview as Overview,
  type OverviewResource,
} from "./overviewApi";

type Holding = Overview["holdings"]["items"][number];
type GroupTotal = Overview["holdings"]["groups"][number];
const TILE_ITEMS = 3;

/** Asset and liability totals are shown as the server sent them, never netted in the browser. */
function groupAmount(group: GroupTotal) {
  if (group.known_count === 0) return "금액 미입력";
  if (group.liabilities_krw === "0") return formatKrw(group.assets_krw);
  if (group.assets_krw === "0") return `부채 ${formatKrw(group.liabilities_krw)}`;
  return `자산 ${formatKrw(group.assets_krw)} · 부채 ${formatKrw(group.liabilities_krw)}`;
}

function itemLink(item: Holding) {
  return item.account_id ? `/accounts/${item.account_id}` : `/assets/${item.asset_id}`;
}

function ItemAmount({ item, month }: { item: Holding; month: string }) {
  if (item.owned_amount_krw === null) return <small> · 금액 미입력</small>;
  return (
    <small>
      {" · "}
      {item.kind === "liability" ? "부채 " : ""}
      {formatKrw(item.owned_amount_krw)}
      {item.basis_month && item.basis_month !== month && ` (${formatMonth(item.basis_month)} 기준)`}
      {item.stale && " · 오래된 금액"}
      {!item.included && " · 합계 제외"}
    </small>
  );
}

function Balance({ data, month }: { data: Overview; month: string }) {
  const holdings = data.holdings;
  const notes = [
    holdings.missing_count > 0 && `금액 미입력 ${holdings.missing_count}개`,
    holdings.stale_count > 0 && `오래된 금액 ${holdings.stale_count}개`,
    holdings.oldest_basis_month &&
      holdings.oldest_basis_month !== month &&
      `가장 오래된 기준 ${formatMonth(holdings.oldest_basis_month)}`,
  ].filter(Boolean);
  return (
    <section className="card portfolio-balance" aria-label="저장된 자산 금액">
      <div className="item-heading">
        <h3>자산·부채</h3>
        <Link to="/assets">자산 전체 보기</Link>
      </div>
      {holdings.item_count === 0 ? (
        <p>
          아직 합계에 넣을 자산·계좌가 없어요. <Link to="/assets/new">자산 등록</Link> ·{" "}
          <Link to="/accounts/new">계좌 등록</Link>
        </p>
      ) : holdings.known_count === 0 ? (
        <p>등록한 {holdings.item_count}개 항목의 금액을 아직 입력하지 않았어요.</p>
      ) : (
        <>
          <dl className="metric-strip">
            <div className="metric-primary">
              <dt>등록 기준 순자산</dt>
              <dd>{formatKrw(holdings.net_assets_krw)}</dd>
            </div>
            <div>
              <dt>자산</dt>
              <dd>{formatKrw(holdings.assets_krw)}</dd>
            </div>
            <div>
              <dt>부채</dt>
              <dd>{formatKrw(holdings.liabilities_krw)}</dd>
            </div>
          </dl>
          <p className="muted">
            항목마다 마지막으로 입력하거나 확인한 금액이에요.
            {notes.length > 0 && ` ${notes.join(" · ")}`}
          </p>
        </>
      )}
      <Link to={`/assets/months/${month}`}>금액 입력·수정</Link>
    </section>
  );
}

function GroupTile({
  group,
  items,
  month,
}: {
  group: GroupTotal;
  items: Holding[];
  month: string;
}) {
  const { label, to } = holdingGroups[group.group];
  const missing = group.count - group.known_count;
  return (
    <section className="card household-category" aria-label={label}>
      <h3>
        <Link to={to}>{label}</Link>
      </h3>
      <p className="household-amount">{groupAmount(group)}</p>
      <p className="muted">
        {group.count}개{missing > 0 && ` · 금액 미입력 ${missing}개`}
      </p>
      <ul className="overview-items">
        {items.slice(0, TILE_ITEMS).map((item) => (
          <li key={item.asset_id}>
            <Link to={itemLink(item)}>{item.name}</Link>
            <ItemAmount item={item} month={month} />
          </li>
        ))}
      </ul>
      {items.length > TILE_ITEMS && <p className="muted">외 {items.length - TILE_ITEMS}개</p>}
    </section>
  );
}

function RegisteredTile({
  title,
  to,
  count,
  items,
  path,
  children,
}: {
  title: string;
  to: string;
  count: number;
  items: { id: string; name: string }[];
  path: string;
  children?: ReactNode;
}) {
  return (
    <section className="card household-category" aria-label={title}>
      <h3>
        <Link to={to}>{title}</Link>
      </h3>
      {count === 0 ? (
        <p className="muted">아직 등록한 항목이 없어요.</p>
      ) : (
        <>
          <p className="muted">{count}개</p>
          {children}
          <ul className="overview-items">
            {items.map((item) => (
              <li key={item.id}>
                <Link to={`${path}/${item.id}`}>{item.name}</Link>
              </li>
            ))}
          </ul>
          {count > items.length && <p className="muted">외 {count - items.length}개</p>}
        </>
      )}
    </section>
  );
}

/** Insurance counts from the household status; the claim list is where the work happens. */
export function InsuranceCounts({ insurance }: { insurance: Overview["insurance"] }) {
  return (
    <>
      <p>
        진행 중인 사건 {insurance.open_case_count}건 · 청구 진행{" "}
        {insurance.claims_in_progress_count}건
      </p>
      {insurance.documents_required_count > 0 && (
        <p>
          <Link to="/insurance/claims?state=documents_required">
            서류 보완이 필요한 청구 {insurance.documents_required_count}건
          </Link>
        </p>
      )}
    </>
  );
}

function Holdings({ overview, quiet }: { overview: OverviewResource; quiet: boolean }) {
  const { month } = useMonth();
  // A failed refresh keeps the status already on screen; only a first load has nothing to show.
  const data = overview.data;
  if (overview.error && !data)
    return quiet ? null : (
      <>
        <FinanceError error={overview.error} />
        <button type="button" onClick={() => void overview.reload()}>
          보유 현황 다시 불러오기
        </button>
      </>
    );
  if (!data) return <p role="status">보유 현황 불러오는 중</p>;
  const { holdings, insurance } = data;
  return (
    <div aria-busy={overview.loading}>
      {overview.error && !quiet && <StaleNotice retry={() => void overview.reload()} />}
      <Balance data={data} month={month} />
      <div className="household-overview-grid">
        {holdings.groups.map((group) => (
          <GroupTile
            key={group.group}
            group={group}
            month={month}
            items={holdings.items.filter((item) => item.group === group.group)}
          />
        ))}
        <RegisteredTile
          title="보험"
          to="/insurance/policies"
          path="/insurance/policies"
          count={insurance.active_policy_count}
          items={insurance.policies}
        >
          <InsuranceCounts insurance={insurance} />
        </RegisteredTile>
        <RegisteredTile
          title="카드"
          to="/cards"
          path="/cards"
          count={data.cards.count}
          items={data.cards.items}
        />
        <RegisteredTile
          title="가전·전자제품"
          to="/appliances"
          path="/appliances"
          count={data.appliances.count}
          items={data.appliances.items}
        />
      </div>
    </div>
  );
}

export function HouseholdOverview({
  overview,
  quiet = false,
}: {
  overview?: OverviewResource;
  quiet?: boolean;
}) {
  const { state } = useAuth();
  return (
    <section aria-label="우리 집 보유 현황">
      <h2>우리 집 보유 현황</h2>
      {state.status === "authenticated" && overview ? (
        <Holdings overview={overview} quiet={quiet} />
      ) : (
        <p>로그인하면 등록한 자산·계좌·보험·가전을 한눈에 볼 수 있어요.</p>
      )}
    </section>
  );
}
