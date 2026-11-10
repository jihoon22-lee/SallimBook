import type { ReactNode } from "react";
import { Link } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import { formatKrw } from "../assets/months/model";
import { formatMonth, useMonth } from "../../shared/MonthContext";
import { formatKrwChange, formatKrwShort, sharePercent } from "../../shared/krwShort";
import {
  holdingGroups,
  type HouseholdOverview as Overview,
  type InsuranceSummary,
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

/** The larger side of a group as a share of the largest group, for the bar's length only. */
function groupSize(group: GroupTotal) {
  return BigInt(group.assets_krw) > BigInt(group.liabilities_krw)
    ? group.assets_krw
    : group.liabilities_krw;
}

function GroupRow({
  group,
  items,
  month,
  largest,
}: {
  group: GroupTotal;
  items: Holding[];
  month: string;
  largest: string;
}) {
  const { label, to } = holdingGroups[group.group];
  const missing = group.count - group.known_count;
  const debt = group.assets_krw === "0" && group.liabilities_krw !== "0";
  return (
    <section className="holding-row" aria-label={label}>
      <h3>
        <Link to={to}>{label}</Link>
      </h3>
      <p className="household-amount">{groupAmount(group)}</p>
      <div className={debt ? "holding-bar holding-bar-debt" : "holding-bar"} aria-hidden="true">
        <span style={{ width: `${sharePercent(groupSize(group), largest)}%` }} />
      </div>
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
    <section className="card home-panel household-category" aria-label={title}>
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

function Investments({ data }: { data: Overview["investments"] }) {
  if (data.count === 0 && data.missing_contribution_count === 0) return null;
  return (
    <section className="card home-panel" aria-label="투자·연금">
      <div className="item-heading">
        <h3>투자·연금</h3>
        <Link to="/accounts">계좌별 보기</Link>
      </div>
      {data.count > 0 ? (
        <>
          <p className="panel-figure">
            <strong title={formatKrw(data.value_krw)}>{formatKrwShort(data.value_krw)}</strong>
            <span className={BigInt(data.gain_krw) < 0n ? "gain gain-down" : "gain"}>
              {formatKrwChange(data.gain_krw)}
              {data.return_percent !== null && ` (${data.return_percent}%)`}
            </span>
          </p>
          <p className="muted">넣은 돈 {formatKrw(data.contributed_krw)} 대비 최근 입력 평가액</p>
          <ul className="panel-rows">
            {data.items.map((item) => (
              <li key={item.account_id}>
                <Link to={`/accounts/${item.account_id}`}>{item.name}</Link>
                <strong title={formatKrw(item.value_krw)}>{formatKrwShort(item.value_krw)}</strong>
                <small>
                  넣은 돈 {formatKrwShort(item.contributed_krw)} ·{" "}
                  <span className={BigInt(item.gain_krw) < 0n ? "gain gain-down" : "gain"}>
                    {formatKrwChange(item.gain_krw)}
                  </span>{" "}
                  · {formatMonth(item.basis_month)} 기준
                </small>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="muted">계좌에 넣은 돈을 적어 두면 평가액과의 차이를 볼 수 있어요.</p>
      )}
      {data.missing_contribution_count > 0 && (
        <p className="muted">
          넣은 돈을 적지 않은 투자·연금 계좌 {data.missing_contribution_count}개
        </p>
      )}
    </section>
  );
}

/** Premiums paid against benefits received; counts come from the status read. */
function Insurance({
  insurance,
  summary,
}: {
  insurance: Overview["insurance"];
  summary: InsuranceSummary | null;
}) {
  const paid = summary && summary.paid_unknown_count < summary.policy_count;
  return (
    <section className="card home-panel" aria-label="보험">
      <div className="item-heading">
        <h3>
          <Link to="/insurance/policies">보험</Link>
        </h3>
        <Link to="/insurance">계약별 보기</Link>
      </div>
      {insurance.active_policy_count === 0 ? (
        <p className="muted">아직 등록한 항목이 없어요.</p>
      ) : (
        <>
          {summary && paid && (
            <>
              <p className="panel-figure">
                <strong>
                  {summary.recovery_percent === null ? "—" : `${summary.recovery_percent}%`}
                </strong>
                <span className="muted">낸 보험료 대비 받은 보험금</span>
              </p>
              <dl className="ratio-rows">
                <div>
                  <dt>낸 보험료</dt>
                  <dd>
                    <span className="ratio-track">
                      <span className="ratio-paid" style={{ width: "100%" }} />
                    </span>
                    <b title={formatKrw(summary.paid_total_krw)}>
                      {formatKrwShort(summary.paid_total_krw)}
                    </b>
                  </dd>
                </div>
                <div>
                  <dt>받은 보험금</dt>
                  <dd>
                    <span className="ratio-track">
                      <span
                        className="ratio-received"
                        style={{
                          width: `${sharePercent(summary.matched_received_krw, summary.paid_total_krw)}%`,
                        }}
                      />
                    </span>
                    <b title={formatKrw(summary.matched_received_krw)}>
                      {formatKrwShort(summary.matched_received_krw)}
                    </b>
                  </dd>
                </div>
              </dl>
              {summary.paid_unknown_count > 0 && (
                <p className="muted">
                  낸 보험료를 모르는 계약 {summary.paid_unknown_count}개는 비율에서 뺐어요.
                </p>
              )}
            </>
          )}
          <p className="muted">
            가입 중인 계약 {insurance.active_policy_count}개
            {summary &&
              summary.monthly_premium_krw !== "0" &&
              ` · 매달 ${formatKrw(summary.monthly_premium_krw)}`}
          </p>
          <InsuranceCounts insurance={insurance} />
          <ul className="overview-items">
            {insurance.policies.map((item) => (
              <li key={item.id}>
                <Link to={`/insurance/policies/${item.id}`}>{item.name}</Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function Holdings({
  overview,
  insurance: insuranceSummary,
}: {
  overview: OverviewResource;
  insurance: InsuranceSummary | null;
}) {
  const { month } = useMonth();
  // A failed refresh keeps the status already on screen; only a first load has nothing to show.
  const data = overview.data;
  if (!data) return overview.error ? null : <p role="status">보유 현황 불러오는 중</p>;
  const { holdings, insurance } = data;
  const largest = holdings.groups.reduce(
    (most, group) => (BigInt(groupSize(group)) > BigInt(most) ? groupSize(group) : most),
    "0",
  );
  return (
    <div className="home-panels" aria-busy={overview.loading}>
      {holdings.groups.length > 0 && (
        <section className="card home-panel" aria-label="자산 구성">
          <div className="item-heading">
            <h3>자산 구성</h3>
            <Link to="/assets">전체 보기</Link>
          </div>
          {holdings.groups.map((group) => (
            <GroupRow
              key={group.group}
              group={group}
              month={month}
              largest={largest}
              items={holdings.items.filter((item) => item.group === group.group)}
            />
          ))}
        </section>
      )}
      <Investments data={data.investments} />
      <Insurance insurance={insurance} summary={insuranceSummary} />
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
  );
}

export function HouseholdOverview({
  overview,
  insurance = null,
}: {
  overview?: OverviewResource;
  /** Premiums against benefits; the panel shows counts alone until this arrives. */
  insurance?: InsuranceSummary | null;
}) {
  const { state } = useAuth();
  return (
    <section aria-label="우리 집 보유 현황">
      <h2>우리 집 보유 현황</h2>
      {state.status === "authenticated" && overview ? (
        <Holdings overview={overview} insurance={insurance} />
      ) : (
        <p>로그인하면 등록한 자산·계좌·보험·가전을 한눈에 볼 수 있어요.</p>
      )}
    </section>
  );
}
